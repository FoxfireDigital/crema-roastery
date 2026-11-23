"""Store-scoped staging; refreshes never add or remove production demand."""
import copy,hashlib,json,uuid
from datetime import timedelta
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction,IntegrityError
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods,require_POST
from .models import StoreConnection,StoreProductMapping,StoreSyncRun,StoreEvent,ImportOrder,RoastPlan,PlanEvent
from .shopify_client import encrypt,decrypt,shop_domain
from .store_http import origin
from .store_adapters import fetch_page

def credentials(store):
    try:
        value=json.loads(decrypt(store.credentials_cipher)) if store.credentials_cipher else {}
        if not isinstance(value,dict):raise ValueError()
        return value
    except (ValueError,TypeError):raise ValidationError('The stored connection cannot be read. Restore its instance key or enter fresh credentials.')

def source_key(store,identity):return 's'+store.pk.hex+'_'+hashlib.sha256(identity.encode()).hexdigest()[:48]

def mapped_lines(store,lines):
    rows={m.product_key:m for m in StoreProductMapping.objects.filter(store=store).select_related('coffee','label_variant')}
    result=copy.deepcopy(lines)
    for line in result:
        mapping=rows.get(line.get('store_product_key'))
        if not mapping or line.get('cycle_choice') or line.get('frac_bag') or line.get('bundle_id'):continue
        if mapping.skip:line['skip']=True;continue
        if not mapping.coffee or not mapping.coffee.active or mapping.label_variant and not mapping.label_variant.active:continue
        line.update(coffee=mapping.coffee_id,label_variant=mapping.label_variant_id,size_oz=str(mapping.size_oz),grind=mapping.grind,roast_level=line.get('roast_level') or mapping.coffee.standard_roast,mapping_saved=True)
        line['source_total']=str(mapping.size_oz*line['quantity']) if line.get('source_total') is None else line['source_total']
    return result

@transaction.atomic
def stage(store,rows):
    rows=list(rows);keys=[source_key(store,r['external_id']) for r in rows]
    if len(set(keys))!=len(keys):raise ValidationError('The store returned repeated order identities. This page was not applied.')
    plan_ids=list(ImportOrder.objects.filter(external_id__in=keys,imported_plan__isnull=False).values_list('imported_plan_id',flat=True))
    plans={p.pk:p for p in RoastPlan.all_objects.select_for_update().filter(pk__in=plan_ids).order_by('pk')}
    from .order_import import source_signature
    from .plan_actions import mark_revised
    for raw in rows:
        data=copy.deepcopy(raw);source_id=data.pop('external_id');key=source_key(store,source_id);signature=data.pop('api_signature')
        order=ImportOrder.objects.select_for_update().filter(external_id=key).first()
        if order and order.source_updated_at and data['source_updated_at']<order.source_updated_at:
            continue  # Overlapping windows must never rewind a newer source fact.
        lines=mapped_lines(store,data['lines']);data['lines']=lines;data['source_signature']=source_signature(lines,data['instructions'])
        if order is None:
            ImportOrder.objects.create(store=store,source_order_id=source_id,external_id=key,api_source_signature=signature,**data);continue
        if order.store_id!=store.pk or order.source_order_id!=source_id:raise ValidationError('A source identity conflicts with existing records. No orders were changed.')
        same=order.api_source_signature==signature
        for name in ['financial_status','fulfillment_status','cancelled','subscription','source_updated_at','source_flags']:setattr(order,name,data[name])
        if store.include_customer_names:order.customer=data['customer']
        if same:
            current={l['api_line_id']:l for l in lines}
            for line in order.lines:
                original=current.get(line.get('api_line_id'))
                if original:line['fulfilled']=original.get('fulfilled',False)
            order.source_changed=False;order.latest_lines=[];order.latest_api_signature=''
        else:
            order.source_changed=True;order.latest_lines=lines;order.latest_api_signature=signature
            if order.instructions!=data['instructions']:order.instructions_confirmed=False
            order.instructions=data['instructions']
        order.save()
        plan=plans.get(order.imported_plan_id)
        from .production_orders import invalidate_confirmation,source_hold_reason
        invalidate_confirmation(order)
        if plan and not plan.closed_at and not plan.historical and plan.accepted_at and source_hold_reason(order):
            if mark_revised(plan,store.updated_by):
                plan.version+=1;plan.save(update_fields=['version'])
                PlanEvent.objects.create(plan=plan,actor=store.updated_by,action='source_changed',details={'order':order.pk,'store':str(store.pk),'reason':'Source changed; actual roasting, packing and stock retained.'})
    return len(rows)

def synchronize(pk,actor=None):
    now=timezone.now()
    with transaction.atomic():
        store=StoreConnection.objects.select_for_update().get(pk=pk)
        if not store.active or store.platform=='csv':raise ValidationError('Choose an active API connection.')
        if store.lease_at and store.lease_at>now-timedelta(minutes=10):raise ValidationError('This store is already refreshing. Wait before retrying.')
        data=credentials(store)
        if not data:raise ValidationError('Save store credentials before refreshing.')
        store.lease=uuid.uuid4();store.lease_at=now;store.last_attempt_at=now;lease=store.lease;version=store.version
        if not store.cursor:
            store.window_start=max(now-timedelta(days=59),store.watermark-timedelta(minutes=10)) if store.watermark else now-timedelta(days=59)
            store.window_end=now
        store.save();run=StoreSyncRun.objects.create(store=store,actor=actor)
    total=0
    try:
        seen=set();cursor=copy.deepcopy(store.cursor)
        for _ in range(5):
            stamp=json.dumps(cursor,sort_keys=True)
            if stamp in seen:raise ValidationError('The store pagination stopped advancing. Retry from the saved position.')
            seen.add(stamp)
            try:rows,nxt=fetch_page(store,data,store.window_start,store.window_end,cursor)
            except (KeyError,TypeError,ValueError,ArithmeticError):raise ValidationError('The store returned incomplete order details. Reviewed work was preserved.')
            if not isinstance(nxt,dict) or len(json.dumps(nxt))>4096 or nxt and not rows or nxt==cursor and nxt:raise ValidationError('The store pagination did not advance safely.')
            for row in rows:
                updated=row.get('source_updated_at')
                if not updated or updated<store.window_start-timedelta(seconds=1) or updated>store.window_end+timedelta(seconds=1):raise ValidationError('The store returned an order outside the refresh window. Its page was not applied.')
            with transaction.atomic():
                current=StoreConnection.objects.select_for_update().get(pk=pk)
                if current.lease!=lease or current.version!=version or not current.active:raise ValidationError('The connection changed during refresh. Retry with the current settings.')
                total+=stage(current,rows);current.cursor=nxt;current.last_count=total;current.last_error=''
                if not nxt:current.watermark=store.window_end;current.last_success_at=timezone.now()
                current.save();cursor=nxt
            if not cursor:break
        with transaction.atomic():
            current=StoreConnection.objects.select_for_update().get(pk=pk)
            if current.lease!=lease:raise ValidationError('The refresh lease changed. Review the saved status.')
            current.lease=None;current.lease_at=None;current.save(update_fields=['lease','lease_at'])
            run.state='partial' if cursor else 'complete';run.count=total;run.finished_at=timezone.now();run.message='More orders remain; continue from the saved position.' if cursor else 'Orders refreshed for review; production demand unchanged.';run.save()
        return total,bool(cursor)
    except Exception as exc:
        message='; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Refresh failed. Already reviewed work and the saved refresh position were preserved.'
        StoreConnection.objects.filter(pk=pk,lease=lease).update(lease=None,lease_at=None,last_error=message[:300])
        StoreSyncRun.objects.filter(pk=run.pk).update(state='failed',count=total,finished_at=timezone.now(),message=message[:300])
        raise ValidationError(message) from None

class StoreForm(forms.ModelForm):
    version=forms.IntegerField(min_value=0,initial=0,widget=forms.HiddenInput)
    token=forms.CharField(max_length=2000,required=False,widget=forms.PasswordInput, label='Access token / API key (leave blank to retain)')
    key=forms.CharField(max_length=150,required=False,widget=forms.PasswordInput,label='WooCommerce consumer key (leave blank to retain)')
    secret=forms.CharField(max_length=150,required=False,widget=forms.PasswordInput,label='WooCommerce consumer secret (leave blank to retain)')
    class Meta:
        model=StoreConnection
        fields=['name','platform','origin','site_id','active','automatic','include_customer_names']
        labels={'origin':'Store HTTPS address','site_id':'Wix site ID (Wix only)','automatic':'Check this store automatically every five minutes','include_customer_names':'Import customer names (optional; appropriate store permissions required)'}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from .marketplaces import selection
        chosen=selection()
        allowed=set(chosen)|{'csv'}
        if not self.instance._state.adding:allowed.add(self.instance.platform)
        self.fields['platform'].choices=[('', 'Choose a selected marketplace')]+[(k,v) for k,v in StoreConnection.PLATFORMS if k in allowed]
        online=[key for key in chosen if key!='manual']
        if self.instance._state.adding and len(online)==1:self.initial.setdefault('platform',online[0])
    def clean(self):
        v=super().clean();platform=v.get('platform');url=v.get('origin','')
        if platform=='shopify':
            try:v['origin']='https://'+shop_domain(url)
            except ValidationError as exc:self.add_error('origin',exc)
        elif platform=='woocommerce':
            try:v['origin']=origin(url)
            except ValidationError as exc:self.add_error('origin',exc)
        elif url:
            try:v['origin']=origin(url)
            except ValidationError as exc:self.add_error('origin',exc)
        if platform=='wix' and not v.get('site_id'):self.add_error('site_id','Enter the exact Wix site ID for this connection.')
        if platform=='squarespace' and not url:self.add_error('origin','Enter the merchant website address to identify this store.')
        if platform=='csv':v['automatic']=False
        for name in ['token','key','secret']:
            if any(ord(c)<32 for c in v.get(name,'')):self.add_error(name,'Credential values cannot contain control characters.')
        return v

def save_connection(post,actor,selected=None):
    with transaction.atomic():
        from .models import PortalConfiguration
        config,_=PortalConfiguration.objects.get_or_create(pk=1)
        PortalConfiguration.objects.select_for_update().get(pk=config.pk)
        current=StoreConnection.objects.select_for_update().get(pk=selected.pk) if selected else StoreConnection(updated_by=actor)
        old_version=current.version;old_identity=(current.platform,current.origin,current.site_id)
        old_credentials=credentials(current);form=StoreForm(post,instance=current)
        if not form.is_valid():raise ValidationError([str(e) for errors in form.errors.values() for e in errors])
        v=form.cleaned_data
        from .marketplaces import selection
        if v['platform']!='csv' and v['platform'] not in selection() and (not selected or v.get('active')):raise ValidationError('Select this marketplace above before adding or activating its connection.')
        if v['version']!=old_version:raise ValidationError('This connection changed. Reload before saving.')
        if selected and current.orders.exists() and old_identity!=(v['platform'],v['origin'],v['site_id']):raise ValidationError('This connection already owns orders. Add a separate connection for another store or platform.')
        value={name:v[name] or old_credentials.get(name,'') for name in ['token','key','secret']}
        others=StoreConnection.objects.exclude(pk=current.pk)
        if v['platform'] in ['shopify','woocommerce','squarespace'] and others.filter(platform=v['platform'],origin=v['origin']).exists():raise ValidationError('That store already has a connection. Edit it instead of creating a second order inbox for the same store.')
        if v['platform']=='wix' and others.filter(platform='wix',site_id=v['site_id']).exists():raise ValidationError('That Wix site already has a connection. Edit its existing settings.')
        if v['platform']=='shopify':
            from .models import ShopifyConnection
            legacy=ShopifyConnection.objects.filter(shop_domain=v['origin'].removeprefix('https://')).exists()
            if legacy:raise ValidationError('This Shopify store already uses the existing Shopify connection. Keep using that screen so earlier orders retain their identities.')
            if not ShopifyConnection.objects.exists() and ImportOrder.objects.filter(store__isnull=True).exists():raise ValidationError('Earlier Shopify exports already own legacy order identities. Establish their existing Shopify connection first; do not add the same store twice.')
        if v['platform']!='csv':
            for other in others.filter(platform=v['platform']):
                saved=credentials(other)
                same=all(value.get(n) and value[n]==saved.get(n) for n in (['key','secret'] if v['platform']=='woocommerce' else ['token']))
                if same:raise ValidationError('These credentials already belong to another connection. Edit that store to avoid duplicate orders.')
        if v['platform']=='woocommerce' and not all(value[name] for name in ['key','secret']):raise ValidationError('Enter the WooCommerce read-only consumer key and secret.')
        if v['platform'] not in ['woocommerce','csv'] and not value['token']:raise ValidationError('Enter the merchant-authorized token or API key for this store.')
        obj=form.save(commit=False);obj.credentials_cipher=encrypt(json.dumps(value)) if v['platform']!='csv' else '';obj.updated_by=actor;obj.version=old_version+1;obj.lease=None;obj.lease_at=None;obj.cursor={};obj.save()
        StoreEvent.objects.create(store=obj,actor=actor,action='connection_saved',details={'name':obj.name,'platform':obj.platform,'active':obj.active,'automatic':obj.automatic,'credentials_updated':any(v[n] for n in ['token','key','secret'])})
        return obj

@staff_member_required
@require_http_methods(['GET','POST'])
def connections(request):
    from .marketplaces import MarketplaceForm,selection,selection_token,save_selection
    marketplace_form=MarketplaceForm(initial={'marketplaces':selection(),'selection_token':selection_token()})
    if request.method=='POST' and request.POST.get('action')=='marketplaces':
        marketplace_form,saved=save_selection(request.POST)
        if saved:
            messages.success(request,'Marketplace choices saved. Add a connection for each store you use.');return redirect('/stores/')
    try:selected=get_object_or_404(StoreConnection,pk=uuid.UUID(request.GET['edit'])) if request.GET.get('edit') else None
    except ValueError:
        from django.http import Http404
        raise Http404('Choose a saved connection.')
    editing=request.method=='POST' and request.POST.get('action')!='marketplaces'
    form=StoreForm(request.POST if editing else None,instance=selected,initial={'version':selected.version if selected else 0});error='';status=400 if marketplace_form.is_bound else 200
    if editing:
        try:save_connection(request.POST,request.user,selected);messages.success(request,'Connection saved. Refresh to check access and load orders for review.');return redirect('/stores/')
        except (ValidationError,IntegrityError) as exc:error='; '.join(exc.messages) if isinstance(exc,ValidationError) else 'That connection name is already used.';status=400
    rows=list(StoreConnection.objects.all())
    for row in rows:row.busy=bool(row.lease_at and row.lease_at>timezone.now()-timedelta(minutes=10))
    labels=dict(StoreConnection.PLATFORMS,manual='Manual orders / CSV only')
    return render(request,'portal/stores.html',{'form':form,'selected':selected,'stores':rows,'error':error,'marketplace_form':marketplace_form,'selected_platform_names':[labels[key] for key in selection()],'has_marketplace_choice':bool(selection()),'runs':StoreSyncRun.objects.select_related('store').order_by('-pk')[:30]},status=status)

@staff_member_required
@require_POST
def refresh_store(request,pk):
    get_object_or_404(StoreConnection,pk=pk)
    try:
        count,more=synchronize(pk,request.user);messages.success(request,f'Checked {count} orders. '+('More remain; continue the refresh.' if more else 'Review orders before adding them to production.'))
    except ValidationError as exc:messages.error(request,'; '.join(exc.messages))
    return redirect('/stores/')

def tick_stores():
    from .store_csv import expire_previews
    expire_previews()
    due=timezone.now()-timedelta(minutes=5)
    from django.db.models import Q
    for store in StoreConnection.objects.filter(active=True,automatic=True).exclude(platform='csv').filter(Q(last_attempt_at__isnull=True)|Q(last_attempt_at__lt=due)).order_by('last_attempt_at','pk')[:4]:
        try:synchronize(store.pk)
        except ValidationError:pass

def remember_mapping(order,line,actor):
    if not order.store_id or not line.get('store_product_key'):return False
    StoreProductMapping.objects.update_or_create(store_id=order.store_id,product_key=line['store_product_key'],defaults={'title':line['title'][:500],'sku':line.get('sku','')[:150],
        'coffee_id':line.get('coffee') if not line.get('skip') else None,'label_variant_id':line.get('label_variant') if not line.get('skip') else None,'size_oz':line.get('size_oz') or None,
        'grind':line.get('grind') or 'unknown','skip':line.get('skip',False),'updated_by':actor})
    return True
