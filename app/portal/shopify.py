"""Merchant-authorized connection and manual, read-only order staging."""
from datetime import timedelta
import hashlib,hmac,secrets,time
from urllib.parse import urlencode
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import render,redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import ShopifyConnection,ImportOrder
from . import shopify_client as api

from django.conf import settings
CALLBACK=settings.PORTAL_BASE_URL+'/shopify/callback/'

class ConnectionForm(forms.Form):
    shop_domain=forms.CharField(label='Store’s myshopify.com address',max_length=100)
    client_id=forms.CharField(label='App client ID',max_length=150)
    client_secret=forms.CharField(label='App client secret (leave blank to keep the saved secret)',required=False,widget=forms.PasswordInput(render_value=False),max_length=300)
    include_customer_names=forms.BooleanField(required=False,label='Include customer names (requires Shopify approval for protected customer data)')
    version=forms.IntegerField(widget=forms.HiddenInput,initial=0)
    def clean_shop_domain(self):
        value=api.shop_domain(self.cleaned_data['shop_domain'])
        from .models import StoreConnection
        if StoreConnection.objects.filter(platform='shopify',origin='https://'+value).exists():raise forms.ValidationError('That store already uses Connected stores. Edit its existing connection to preserve order identities.')
        return value


@transaction.atomic
def stage_orders(rows):
    """Refresh source status while retaining deliberate allocations and real work."""
    from .order_import import source_signature
    from .models import RoastPlan,PlanEvent
    from .plan_actions import mark_revised
    rows=list(rows)
    identities=[data['external_id'] for data in rows]
    plan_ids=ImportOrder.objects.filter(external_id__in=identities,imported_plan__isnull=False).values_list('imported_plan_id',flat=True)
    locked_plans={p.pk:p for p in RoastPlan.objects.select_for_update().filter(pk__in=plan_ids).order_by('pk')}
    count=0
    for data in rows:
        data=dict(data);identity=data.pop('external_id');signature=data.pop('api_signature')
        order=ImportOrder.objects.select_for_update().filter(external_id=identity).first()
        if not order:
            ImportOrder.objects.create(external_id=identity,api_source_signature=signature,**data);count+=1;continue
        old_baseline=order.api_source_signature
        same=old_baseline==signature if old_baseline else order.source_signature==data['source_signature']
        if not same and not old_baseline:
            # A CSV can omit selling-plan names. Compare original items with that
            # one field normalized, while keeping source titles/quantities exact.
            candidate=[]
            for item in data['lines']:
                item=dict(item)
                prior=next((l for l in order.lines if str(l.get('source_line',l.get('line_key')))==str(item['source_line'])),None)
                if prior:item['selling_plan']=prior.get('selling_plan','')
                candidate.append(item)
            same=order.source_signature==source_signature(candidate,data['instructions'])
        for field in ['financial_status','fulfillment_status','cancelled','subscription']:setattr(order,field,data[field])
        if data.get('customer'):order.customer=data['customer']
        if same:
            order.api_source_signature=signature
            order.source_changed=False;order.latest_lines=[];order.latest_api_signature=''
            by_id={l['api_line_id']:l for l in data['lines']}
            for item in order.lines:
                source=next((l for l in data['lines'] if str(l['source_line'])==str(item.get('source_line',item.get('line_key')))),None)
                match=by_id.get(item.get('api_line_id')) if item.get('api_line_id') else source
                if match:item.update(api_line_id=match['api_line_id'],fulfilled=match['fulfilled'])
        else:
            order.source_changed=True;order.latest_lines=data['lines'];order.latest_api_signature=signature
            if order.instructions!=data['instructions']:order.instructions_confirmed=False
            order.instructions=data['instructions']
        order.save();count+=1
        plan=locked_plans.get(order.imported_plan_id)
        if plan and plan.accepted_at and (order.source_changed or order.cancelled or order.financial_status!='paid' or order.fulfillment_status not in ('unfulfilled',)):
            if mark_revised(plan,plan.accepted_by or plan.created_by):
                plan.version+=1;plan.save(update_fields=['version'])
                PlanEvent.objects.create(plan=plan,actor=plan.created_by,action='shopify_changed',details={'order':order.pk,'reason':'Shopify source or status changed; recorded production retained.'})
    return count


def sync_orders(user):
    with transaction.atomic():
        connection=ShopifyConnection.objects.select_for_update().get(pk=1)
        if connection.sync_started_at and connection.sync_started_at>timezone.now()-timedelta(minutes=10):raise ValidationError('An order refresh is already running. Wait before trying again.')
        if not connection.access_token_cipher:raise ValidationError('Connect Shopify first.')
        connection.sync_started_at=timezone.now();lease=connection.sync_started_at;version=connection.version
        if not connection.sync_cursor:
            connection.sync_since=max(timezone.now()-timedelta(days=59),connection.last_sync_until-timedelta(minutes=10)) if connection.last_sync_until else timezone.now()-timedelta(days=59)
            connection.sync_until=timezone.now()
        connection.save()
    try:
        raw,cursor,more=api.fetch_batch(connection,connection.sync_since,connection.sync_until,connection.sync_cursor)
        try:normalized=[api.normalize_order(node) for node in raw]
        except (KeyError,TypeError,ValueError,ArithmeticError):raise ValidationError('Shopify returned incomplete order details. Reviewed items were preserved. Retry the refresh.')
        with transaction.atomic():
            current=ShopifyConnection.objects.select_for_update().get(pk=1)
            if current.version!=version or current.sync_started_at!=lease:raise ValidationError('The connection changed during refresh. Try again.')
            count=stage_orders(normalized)
            current.last_sync_at=timezone.now();current.last_count=count;current.sync_cursor=cursor;current.last_error='';current.sync_started_at=None
            if not more:current.last_sync_until=current.sync_until
            current.save()
        return count,more
    except Exception:
        ShopifyConnection.objects.filter(pk=1,version=version,sync_started_at=lease).update(sync_started_at=None,last_error='Refresh stopped. Reviewed allocations and production work were preserved. Retry or check the connection.')
        raise


def connection_status():
    """Only display-safe fields; never attach saved credentials to the page."""
    connection=ShopifyConnection.objects.filter(pk=1).values('connected_at','last_sync_at','last_count','sync_cursor','sync_started_at','last_error','shop_domain').first()
    if not connection:return {'connected':False}
    return {**connection,'connected':bool(connection['connected_at']),'more':bool(connection['sync_cursor']),
            'busy':bool(connection['sync_started_at'] and connection['sync_started_at']>timezone.now()-timedelta(minutes=10))}


@staff_member_required
@require_POST
def refresh(request):
    try:
        count,more=sync_orders(request.user)
        messages.success(request,f'Refreshed {count} Shopify orders. '+('More orders remain; refresh again to continue.' if more else 'Review and select orders before adding them to a plan.'))
    except (ValidationError,ShopifyConnection.DoesNotExist) as error:
        messages.error(request,'; '.join(error.messages) if isinstance(error,ValidationError) else 'Set up Shopify on the connection page first.')
    return redirect('/imports/')


@staff_member_required
def connection_page(request):
    connection=ShopifyConnection.objects.filter(pk=1).first()
    initial={key:getattr(connection,key) for key in ['shop_domain','client_id','include_customer_names','version']} if connection else {}
    form=ConnectionForm(request.POST if request.method=='POST' and request.POST.get('action')=='save' else None,initial=initial)
    try:
        if request.method=='POST':
            action=request.POST.get('action')
            if action=='save' and form.is_valid():
                with transaction.atomic():
                    current=ShopifyConnection.objects.select_for_update().filter(pk=1).first()
                    if current and current.version!=form.cleaned_data['version']:raise ValidationError('The connection changed. Reload before saving.')
                    current=current or ShopifyConnection(pk=1,updated_by=request.user)
                    values=form.cleaned_data
                    changed=current.shop_domain!=values['shop_domain'] or current.client_id!=values['client_id'] or bool(values['client_secret'])
                    if not values['client_secret'] and (changed or not current.client_secret_cipher):raise ValidationError('Enter the client secret for this app.')
                    current.shop_domain=values['shop_domain'];current.client_id=values['client_id'];current.include_customer_names=values['include_customer_names'];current.updated_by=request.user
                    if values['client_secret']:current.client_secret_cipher=api.encrypt(values['client_secret'])
                    if changed:
                        current.access_token_cipher='';current.refresh_token_cipher='';current.refresh_token_expires_at=None;current.connected_at=None;current.granted_scopes=[];current.token_expires_at=None
                        current.sync_cursor='';current.last_sync_until=None;current.sync_started_at=None
                        current.sync_since=None;current.sync_until=None;current.last_sync_at=None;current.last_count=0;current.last_error=''
                    current.version+=1;current.save()
                messages.success(request,'App details saved. Authorize the app from the computer where you can access Shopify.');return redirect('/shopify/')
            elif action in ['authorize','client_credentials']:
                if not connection or not connection.client_secret_cipher:raise ValidationError('Save the store and app details first.')
                if action=='client_credentials':
                    grant=api.request_json(connection.shop_domain,'/admin/oauth/access_token',{'grant_type':'client_credentials','client_id':connection.client_id,'client_secret':api.decrypt(connection.client_secret_cipher)})
                    api.save_grant(connection,grant,'client_credentials');messages.success(request,'Shopify connected. Refresh orders to load the review list.');return redirect('/shopify/')
                state=secrets.token_urlsafe(32)
                request.session['shopify_authorization']={'state':state,'version':connection.version,'user':request.user.pk,'at':time.time()}
                return redirect('https://'+connection.shop_domain+'/admin/oauth/authorize?'+urlencode({'client_id':connection.client_id,'scope':'read_orders,read_products','redirect_uri':CALLBACK,'state':state}))
            elif action!='save':raise ValidationError('Unknown connection action.')
    except ValidationError as error:messages.error(request,'; '.join(error.messages))
    from .shopify_automatic import automatic_status
    return render(request,'portal/shopify.html',{'form':form,'connection':connection,'callback':CALLBACK,'automatic':automatic_status()})


@staff_member_required
def callback(request):
    packet=request.session.pop('shopify_authorization',None)
    connection=ShopifyConnection.objects.filter(pk=1).first()
    try:
        params=request.GET
        if any(len(params.getlist(key))!=1 for key in params):raise ValidationError('Duplicate authorization fields.')
        if not packet or not connection or packet['user']!=request.user.pk or packet['version']!=connection.version or not 0<=time.time()-packet['at']<600:raise ValidationError('Authorization expired. Start again from the Shopify connection page.')
        if not hmac.compare_digest(params.get('state',''),packet['state']) or params.get('shop')!=connection.shop_domain:raise ValidationError('Authorization verification failed.')
        if abs(time.time()-int(params.get('timestamp','0')))>600:raise ValidationError('Authorization expired. Start again.')
        query='&'.join(key+'='+params[key] for key in sorted(params) if key!='hmac')
        expected=hmac.new(api.decrypt(connection.client_secret_cipher).encode(),query.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,params.get('hmac','')) or not params.get('code'):raise ValidationError('Authorization signature verification failed.')
        grant=api.request_json(connection.shop_domain,'/admin/oauth/access_token',{'client_id':connection.client_id,'client_secret':api.decrypt(connection.client_secret_cipher),'code':params['code'],'expiring':1})
        # Avoid storing an exchanged token against credentials changed meanwhile.
        with transaction.atomic():
            current=ShopifyConnection.objects.select_for_update().get(pk=1)
            if current.version!=packet['version']:raise ValidationError('App details changed during authorization. Start again.')
            api.save_grant(current,grant,'oauth')
        messages.success(request,'Shopify connected. Refresh orders to review real deliveries.')
        return redirect('/shopify/')
    except (ValidationError,ValueError,KeyError) as error:
        return HttpResponseBadRequest('; '.join(error.messages) if isinstance(error,ValidationError) else 'Invalid Shopify authorization. Start again from the connection page.')
