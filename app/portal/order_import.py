"""Read-only order staging; importing never changes Shopify payment/fulfillment."""
from .order_payment import payment_allows_production
import csv,io,re,copy,hashlib,json
from decimal import Decimal,InvalidOperation
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST
from .models import ImportOrder,IncomingOrderLine,RoastPlan,Coffee,LabelVariant,ProductMapping
from .planning import IncomingForm,group_for

def mapping_key(title,sku):
    return hashlib.sha256(json.dumps([title.strip().casefold(),sku.strip().casefold()]).encode()).hexdigest()


def infer_grind(title):
    text=title.casefold()
    if re.search(r'\bwhole[ -]*beans?\b',text):return 'whole'
    if re.search(r'\bfrench[ -]*press\b',text):return 'coarse'
    for word in ['coarse','fine','regular']:
        if re.search(r'\b'+word+r'\b',text):return word
    return 'ground' if re.search(r'\bground\b',text) else 'unknown'

def source_signature(lines,instructions):
    original=[];seen=set()
    for line in lines:
        if line.get('bundle_key'):
            if line['bundle_key'] in seen:continue
            seen.add(line['bundle_key'])
        facts={key:line.get(key) for key in ['title','sku','quantity','selling_plan']}
        if line.get('bundle_key'):facts['quantity']=line.get('bundle_pack_count',line.get('quantity'))
        original.append(facts)
    return hashlib.sha256(json.dumps({'items':original,'instructions':instructions},sort_keys=True).encode()).hexdigest()


def expand_frac_line(line):
    """One sold pack contains four individually labeled 2.5 oz bags."""
    from .product_bundles import expand_bundle_line
    configured=expand_bundle_line(line)
    if configured is not None:return configured
    if not re.search(r'\b(?:frac|fraq)\s*(?:packs?|pacs?)\b',line['title'],re.I):return [line]
    result=[]
    from .instance import assortment_names
    names=assortment_names()
    if len(names)!=4:return [line]
    for index,name in enumerate(names,1):
        coffee=Coffee.objects.filter(name=name,active=True).first()
        item=copy.deepcopy(line)
        item.update(bundle_key=str(line['source_line']),line_key=str(line['source_line'])+'.f'+str(index),
                    source_total=str(Decimal(10)*int(line['quantity'])),size_oz='2.5',coffee=coffee.pk if coffee else None,
                    label_variant=None,roast_level=coffee.standard_roast if coffee else '',target_finish_temp_f=None,
                    cycle_choice=False,needs_cycle_assignment=False,skip=False,frac_bag=True,per_sheet=8,
                    bundle_pack_count=int(line['quantity']))
        result.append(item)
    return result


def same_legacy_items(old,new):
    # Earlier releases retained original titles and source totals, including on
    # split assortments, but had no source fingerprint. Compare those facts
    # before assigning the first fingerprint; never infer that changed items match.
    def original(lines):
        result={}
        for index,line in enumerate(lines):
            key=str(line.get('source_line',line.get('line_key',index+1)))
            total=line.get('source_total')
            try:total=str(Decimal(str(total)).normalize()) if total is not None else None
            except InvalidOperation:return None
            value=[line.get('title',''),line.get('sku',''),line.get('selling_plan',''),total]
            if key in result and result[key]!=value:return None
            result[key]=value
        return result
    before=original(old)
    return before is not None and before==original(new)


def infer_item(name,quantity,sku='',selling_plan='',use_saved=False):
    text=name.casefold().strip();coffee=None;label=None
    labels=LabelVariant.objects.filter(active=True,coffee__active=True).select_related('coffee')
    for candidate in sorted(labels,key=lambda l:len(l.name),reverse=True):
        if coffee:break
        if text==candidate.name.casefold() or text.startswith(candidate.name.casefold()+' -'):
            label=candidate;coffee=label.coffee;break
    if not coffee:
        for candidate in sorted(Coffee.objects.filter(active=True,experimental=False),key=lambda c:len(c.name),reverse=True):
            if text==candidate.name.casefold() or text.startswith(candidate.name.casefold()+' -') or text.startswith(candidate.name.casefold()+' /'):
                coffee=candidate;break
    size=None
    match=re.search(r'(\d+(?:\.\d+)?)\s*(?:lbs?\b|pounds?\b)',text)
    if match:size=str(Decimal(match[1])*16)
    else:
        match=re.search(r'(\d+(?:\.\d+)?)\s*(?:oz\b|ounces?\b)',text)
        if match:size=str(Decimal(match[1]))
    roast=coffee.standard_roast if coffee else ''
    # Distinguish a requested roast from descriptive tasting notes. Only explicit
    # variant-style labels are considered; conflicts must be reviewed by staff.
    roast_text=re.sub(r'\bfrench[ -]*press\b','',text)
    for pattern,value in [('french','French'),('vienna','Dark'),('full city','Medium'),('city/light','Light')]:
        if pattern in roast_text:roast=value;break
    item={'title':name,'sku':sku,'quantity':quantity,'size_oz':size,'coffee':coffee.pk if coffee else None,'label_variant':label.pk if label else None,'roast_level':roast,'target_finish_temp_f':None,'selling_plan':selling_plan,'skip':False,'cycle_choice':'monthly coffee subscription' in text,'grind':infer_grind(name)}
    if use_saved and not item['cycle_choice']:
        saved=ProductMapping.objects.filter(fingerprint=mapping_key(name,sku)).select_related('coffee','label_variant').first()
        if saved and (saved.skip or saved.coffee and saved.coffee.active and (not saved.label_variant or saved.label_variant.active)):
            item.update(coffee=saved.coffee_id,label_variant=saved.label_variant_id,size_oz=str(saved.size_oz) if saved.size_oz else size,skip=saved.skip,mapping_saved=True)
            if not item['roast_level'] and saved.coffee:item['roast_level']=saved.coffee.standard_roast
    return item

def parse_export(raw):
    if len(raw)>5*1024*1024:raise ValidationError('Use an orders CSV smaller than 5 MB.')
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:raise ValidationError('Export the orders CSV as UTF-8.')
    reader=csv.DictReader(io.StringIO(text,newline=''))
    required={'Name','Id','Lineitem name','Lineitem quantity','Created at'}
    if not required.issubset(reader.fieldnames or []):raise ValidationError('Choose an export from Shopify Orders. Subscription contracts and product exports belong outside the order queue.')
    grouped={};last_id=None;last_reference=None
    for n,row in enumerate(reader):
        if n>=10000:raise ValidationError('Import at most 10,000 CSV lines at a time.')
        reference=(row.get('Name') or '').strip()
        external=(row.get('Id') or '').strip()
        if not external and (not reference or reference==last_reference):external=last_id
        if not external:raise ValidationError('Every order needs its Shopify Id. Re-export the orders with that column.')
        external=external.removeprefix('gid://shopify/Order/')
        if not external.isdigit():raise ValidationError('Shopify exports require the numeric Shopify order Id. Other stores use the general CSV importer.')
        if external not in grouped:
            stamp=parse_datetime((row.get('Created at') or '').strip())
            if not stamp:raise ValidationError(f'Order {reference or external} has no usable created timestamp.')
            if timezone.is_naive(stamp):stamp=timezone.make_aware(stamp)
            subscription='prepaid' if 'prepaid' in ' '.join([row.get('Tags',''),row.get('Selling Plan',''),row.get('Lineitem name','')]).casefold() else 'recurring' if (row.get('Selling Plan') or '').strip() or 'subscription' in (row.get('Tags') or '').casefold() else 'unknown'
            grouped[external]={'external_id':external,'reference':reference or external,'customer':(row.get('Billing Name') or row.get('Shipping Name') or '')[:120],'received_at':stamp,'financial_status':(row.get('Financial Status') or '').lower(),'fulfillment_status':(row.get('Fulfillment Status') or '').lower(),'cancelled':bool((row.get('Cancelled at') or '').strip()),'subscription':subscription,'lines':[]}
        item=grouped[external]
        item['instructions']='\n'.join(value.strip() for value in [row.get('Notes',''),row.get('Note Attributes','')] if value and value.strip())[:2000] if 'instructions' not in item else item['instructions']
        if (row.get('Canceled at') or '').strip():item['cancelled']=True
        title=(row.get('Lineitem name') or '').strip()
        if title:
            try:qty=int(row.get('Lineitem quantity') or '')
            except ValueError:raise ValidationError(f'Invalid item quantity on {item["reference"]}.')
            if qty<=0:raise ValidationError('Order item quantities must be positive.')
            line=infer_item(title,qty,row.get('Lineitem sku') or row.get('Lineitem SKU') or '',row.get('Selling Plan') or '',use_saved=True)
            line['line_key']=str(len({x['source_line'] for x in item['lines']})+1)
            line['source_line']=line['line_key']
            line['source_total']=str(Decimal(line['size_oz'])*qty) if line['size_oz'] else None
            line['fulfilled']=(row.get('Lineitem fulfillment status') or '').lower()=='fulfilled'
            item['lines'].extend(expand_frac_line(line))
        last_id=external;last_reference=reference or item['reference']
    for item in grouped.values():
        item['source_signature']=source_signature(item['lines'],item['instructions'])
    return list(grouped.values())

def stage_export(raw):
    from .models import StoreConnection
    if StoreConnection.objects.filter(platform='shopify').exists():raise ValidationError('Choose the owning Shopify store in the general CSV importer. This older export screen cannot distinguish several stores.')
    rows=parse_export(raw);count=0
    with transaction.atomic():
        ids=list(ImportOrder.objects.filter(external_id__in=[data['external_id'] for data in rows],imported_plan__isnull=False).values_list('imported_plan_id',flat=True))
        plans={plan.pk:plan for plan in RoastPlan.all_objects.select_for_update().filter(pk__in=ids).order_by('pk')}
        for data in rows:
            external=data.pop('external_id')
            order=ImportOrder.objects.select_for_update().filter(external_id=external).first()
            if order and not order.source_signature and not data['instructions'] and same_legacy_items(order.lines,data['lines']):order.source_signature=data['source_signature']
            if order and order.imported_at:
                for field in ['financial_status','fulfillment_status','cancelled']:setattr(order,field,data[field])
                order.source_changed=order.source_signature!=data['source_signature']
                order.latest_lines=data['lines'] if order.source_changed else []
                if order.instructions!=data['instructions']:order.instructions_confirmed=False
                order.instructions=data['instructions']
                order.save()
                from .production_orders import invalidate_confirmation
                invalidate_confirmation(order)
                from .production_orders import source_hold_reason
                from .plan_actions import mark_revised
                plan=plans.get(order.imported_plan_id)
                if not plan:raise ValidationError('An order moved between plans during refresh. Retry the export.')
                if not plan.closed_at and not plan.historical and plan.accepted_at and source_hold_reason(order):
                    if mark_revised(plan,plan.created_by):plan.version+=1;plan.save(update_fields=['version'])
                continue
            if order and order.source_signature and order.source_signature==data['source_signature']:
                # Preserve this cycle's deliberate assortment on identical refreshes.
                for line in order.lines:
                    original=str(line.get('source_line',line.get('line_key','')))
                    match=next((x for x in data['lines'] if x['line_key']==original),None)
                    if match:line['fulfilled']=match['fulfilled']
                for field in ['financial_status','fulfillment_status','cancelled','subscription']:setattr(order,field,data[field])
                order.save();count+=1;continue
            # A new export is a new source snapshot; display any changed mapping
            # for review rather than silently retaining a previous override.
            if order:
                for field,value in data.items():setattr(order,field,value)
                order.api_source_signature='';order.latest_api_signature='';order.source_changed=False;order.latest_lines=[]
                order.instructions_confirmed=False
                order.save()
            else:ImportOrder.objects.create(external_id=external,**data)
            count+=1
    return count

def line_data(line):
    if line.get('skip') or line.get('fulfilled'):return None
    try:
        size=Decimal(str(line.get('size_oz')));qty=int(line['quantity'])
        if not size.is_finite() or size<=0 or qty<=0:raise ValueError()
    except (InvalidOperation,ValueError,TypeError):raise ValidationError('Confirm the bag size and quantity for each coffee item.')
    return {'reference':'','customer':'','coffee':line.get('coffee') or '', 'label_variant':line.get('label_variant') or '', 'bags_1lb':0,'bags_5lb':0,'extra_oz':str(size*qty),'roast_level':line.get('roast_level') or '', 'target_finish_temp_f':line.get('target_finish_temp_f') or ''}

def readiness(order):
    from .subscription_planning import forecast_cycle,forecast_hold,renewal_review_needed
    from .models import SubscriptionCycle
    linked=SubscriptionCycle.objects.filter(renewal_order=order).first()
    if linked:return False,'Already covered by early subscription plan #'+str(linked.plan_id)
    if order.imported_at:return False,'Already added to plan #'+str(order.imported_plan_id)
    if renewal_review_needed(order):return False,'Review this renewal against early subscription production'
    cycle=forecast_cycle(order)
    if cycle and forecast_hold(order):return False,forecast_hold(order)
    if order.source_flags:return False,'; '.join(order.source_flags)
    if order.dismissed_at:return False,'Dismissed — restore this order before adding it'
    if order.imported_at:return False,'Already added to plan #'+str(order.imported_plan_id)
    if order.source_changed:return False,'Source items changed — review the refreshed items first'
    if order.cancelled:return False,'Cancelled'
    if order.fulfillment_status=='fulfilled':return False,'Already fulfilled'
    if order.fulfillment_status in ('partial','partially_fulfilled'):return False,'Partially fulfilled — review remaining quantities before export'
    if order.fulfillment_status!='unfulfilled':return False,'Not a currently unfulfilled delivery — review its schedule/status'
    if not payment_allows_production(order) and not (cycle and order.financial_status=='scheduled'):return False,'Payment / refund status needs review'
    if order.subscription=='prepaid':return False,'Prepaid subscription: delivery scheduling must be connected before import'
    if order.instructions and not order.instructions_confirmed:return False,'Review the order’s instructions before adding it'
    if any(line.get('bundle_id') and line.get('bundle_grind_explicit') and line.get('grind')=='unknown' for line in order.lines):return False,'Confirm the coffee box’s grind choice'
    if any(line.get('cycle_choice') and not line.get('coffee') and not line.get('skip') for line in order.lines):return False,'Choose this cycle’s coffees'
    expected={};actual={}
    for line in order.lines:
        if line.get('source_total') is not None:
            key=line.get('source_line',line.get('line_key'))
            try:
                expected[key]=Decimal(str(line['source_total']))
                actual[key]=actual.get(key,Decimal(0))+Decimal(str(line.get('size_oz')))*int(line['quantity'])
            except (InvalidOperation,TypeError,ValueError):return False,'Confirm each split’s finished quantity'
    if any(actual[key]!=value for key,value in expected.items()):return False,'Split portions must still equal the original ordered quantity'
    count=0
    for line in order.lines:
        try:data=line_data(line)
        except ValidationError as e:return False,e.messages[0]
        if data is None:continue
        form=IncomingForm(data)
        if not form.is_valid():return False,next(iter(form.errors.values()))[0]
        count+=1
    if not count:return False,'No unfulfilled coffee items selected'
    return True,'Ready'

def add_selected(plan,ids,user):
    if not ids:raise ValidationError('Select at least one order.')
    if len(ids)>250:raise ValidationError('Add at most 250 orders at a time.')
    try:ids=[int(value) for value in ids]
    except (TypeError,ValueError):raise ValidationError('Select valid orders from the list.')
    with transaction.atomic():
        plan=RoastPlan.objects.select_for_update().get(pk=plan.pk)
        orders=list(ImportOrder.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
        if len(orders)!=len(set(ids)):raise ValidationError('The selected orders changed. Refresh the list.')
        # Validate the whole selection before changing production demand.
        for order in orders:
            from .subscription_planning import forecast_cycle
            cycle=forecast_cycle(order)
            if cycle and cycle.plan_id!=plan.pk:raise ValidationError('This early delivery belongs to plan #'+str(cycle.plan_id)+'. Open its original plan.')
            ready,reason=readiness(order)
            if not ready:raise ValidationError(f'{order.reference}: {reason}')
        for order in orders:
            for index,line in enumerate(order.lines):
                data=line_data(line)
                if data is None:continue
                form=IncomingForm(data);assert form.is_valid()
                clean=form.cleaned_data;group=group_for(plan,clean)
                from .flavoring import import_packaging
                IncomingOrderLine.all_objects.update_or_create(source='store' if order.store_id else 'shopify',external_id=f'{order.external_id}:{line.get("line_key",index+1)}',defaults={'import_order':order,'group':group,'product_coffee':clean['coffee'],'product_label':clean.get('label_variant'),'packaging':import_packaging(line),'grind':line.get('grind') or infer_grind(line.get('title','')),'reference':order.reference,'customer':order.customer,'received_at':order.received_at,'finished_oz':clean['finished_oz'],'removed_at':None})
            order.imported_plan=plan;order.imported_at=timezone.now();order.removed_at=None;order.save()
        from .autobatches import sync_plan
        sync_plan(plan,user)
        from .plan_actions import mark_revised
        mark_revised(plan,user)
        plan.version+=1;plan.save(update_fields=['version'])
    return len(orders)

def remove_import(pk,user=None):
    with transaction.atomic():
        order=ImportOrder.objects.get(pk=pk)
        if not order.imported_plan_id:raise ValidationError('This order is not in a plan.')
        plan=RoastPlan.all_objects.select_for_update().get(pk=order.imported_plan_id)
        if plan.closed_at:raise ValidationError('This order belongs to a closed plan. Reopen the plan before changing its recorded demand.')
        if plan.historical:raise ValidationError('This order belongs to a reconstructed past plan. Review its recorded association instead of returning it to production.')
        order=ImportOrder.objects.select_for_update().get(pk=pk)
        lines=IncomingOrderLine.objects.filter(source__in=['shopify','store'],external_id__startswith=order.external_id+':')
        groups=list({line.group for line in lines.select_related('group')})
        from .roasted_stock import used_for
        if any(group.planned_batches.filter(batch__isnull=False).exists() or used_for(group) for group in groups):raise ValidationError('Production or stock usage has started for this coffee profile. Keep its recorded demand and review corrections separately.')
        lines.update(removed_at=timezone.now())
        order.imported_at=None;order.removed_at=timezone.now();order.save()
        if order.source_changed:
            order.lines=order.latest_lines;order.source_signature=source_signature(order.lines,order.instructions);order.source_changed=False;order.latest_lines=[]
            order.api_source_signature=order.latest_api_signature;order.latest_api_signature='';order.save()
        from .autobatches import sync_plan
        sync_plan(plan,user or plan.created_by)
        from .plan_actions import mark_revised
        mark_revised(plan,user or plan.created_by)
        plan.version+=1;plan.save(update_fields=['version'])

@staff_member_required
def order_import(request):
    plan_id=request.POST.get('plan') or request.GET.get('plan')
    plan=None if plan_id=='new' else get_object_or_404(RoastPlan,pk=plan_id) if plan_id else RoastPlan.objects.first()
    try:
        if request.method=='POST':
            if request.POST.get('remove_order'):
                remove_import(request.POST['remove_order'],request.user);messages.success(request,'Removed the order’s unstarted demand from its plan. Review any remaining draft batch sizes.')
            elif request.POST.get('action')=='upload':
                upload=request.FILES.get('orders_csv')
                if not upload:raise ValidationError('Choose a Shopify orders CSV.')
                if upload.size>5*1024*1024:raise ValidationError('Use a file smaller than 5 MB.')
                count=stage_export(upload.read());messages.success(request,f'Refreshed {count} orders from the export. Review and select orders below.')
            elif request.POST.get('action')=='add':
                if not plan:raise ValidationError('Create a roast plan before adding orders.')
                ids=request.POST.getlist('orders');count=add_selected(plan,ids,request.user)
                messages.success(request,f'Added {count} orders to roast plan #{plan.pk}.')
                return redirect('/planning/?plan='+str(plan.pk))
            elif request.POST.get('action')=='create_selected':
                from .workflow import create_selected_plan
                plan=create_selected_plan(request.POST.getlist('orders'),request.POST.get('new_plan_date'),request.POST.get('creation_key'),request.user)
                messages.success(request,'Plan created with your selected orders and suggested batches. Review the loads before accepting.')
                return redirect('/planning/?plan='+str(plan.pk))
            else:raise ValidationError('Unknown import action.')
            return redirect('/imports/'+('?plan='+str(plan.pk) if plan else ''))
    except ValidationError as error:messages.error(request,'; '.join(error.messages))
    from .shopify import connection_status
    dismissed=request.GET.get('dismissed')=='1'
    import uuid
    return render(request,'portal/order_import.html',{'rows':import_rows(dismissed=dismissed),'dismissed':dismissed,'dismissed_count':ImportOrder.objects.filter(dismissed_at__isnull=False).count(),'plan':plan,'plans':RoastPlan.objects.all()[:25],'shopify_status':connection_status(),'creation_key':request.POST.get('creation_key') or str(uuid.uuid4()),'today':timezone.localdate()})


def import_rows(dismissed=False):
    rows=[]
    coffee_names={str(pk):name for pk,name in Coffee.objects.values_list('pk','name')}
    for order in ImportOrder.objects.filter(dismissed_at__isnull=not dismissed).select_related('imported_plan','store')[:1000]:
        ready,reason=readiness(order)
        actionable=not order.source_flags and not order.dismissed_at and not order.imported_at and not order.cancelled and (payment_allows_production(order) or order.financial_status=='scheduled' and hasattr(order,'forecast_cycle')) and order.fulfillment_status=='unfulfilled' and order.subscription!='prepaid'
        weight=Decimal(0);allocations=[];mapped=True;source_items=[];seen_bundles=set()
        for line in order.lines:
            bundle=line.get('bundle_key')
            if not bundle or bundle not in seen_bundles:
                original=dict(line)
                if bundle:
                    original['quantity']=line.get('bundle_pack_count',line['quantity']);seen_bundles.add(bundle)
                source_items.append(original)
            if line.get('skip') or line.get('fulfilled'):continue
            try:
                value=Decimal(str(line.get('size_oz') or 0))*int(line['quantity'])
                if value.is_finite() and value>0:
                    weight+=value
                    name=coffee_names.get(str(line.get('coffee')))
                    if name:allocations.append({'coffee':name,'pounds':value/16,'ounces':value,'frac':bool(line.get('frac_bag')),'bags':line['quantity'],'size':line.get('size_oz'),'roast':line.get('roast_level','')})
                    else:mapped=False
                else:mapped=False
            except (InvalidOperation,ValueError,TypeError):mapped=False
        rows.append({'order':order,'ready':ready,'reason':reason,'actionable':actionable,'weight':weight,'category':'imported' if order.imported_at else 'ready' if ready else 'review' if actionable else 'held'})
        rows[-1]['allocations']=allocations if mapped else []
        rows[-1]['source_items']=source_items
        historical=order.imported_plan_id and order.imported_plan.historical
        closed=order.imported_plan_id and order.imported_plan.closed_at
        if closed:rows[-1]['reason']='In closed plan #'+str(order.imported_plan_id)
        if historical:rows[-1]['reason']='Associated with past roast date'
        from .production_orders import source_hold_reason,production_confirmed
        rows[-1]['alert']=source_hold_reason(order) if not historical and order.imported_at else ''
        rows[-1]['production_confirmed']=production_confirmed(order) if order.imported_at else False
        rows[-1]['production_review_url']=f'/imports/{order.pk}/production/' if order.imported_at and order.fulfillment_status=='fulfilled' and not historical and not closed else ''
        if closed:
            from .subscription_planning import forecast_hold
            early=forecast_hold(order)
            rows[-1]['alert']=early if early is not None else 'Source changed after closure — completed snapshot retained' if order.source_changed or order.cancelled or not payment_allows_production(order) else ''
    return rows


@staff_member_required
@require_POST
def order_visibility(request,pk):
    action=request.POST.get('order_visibility')
    try:
        order=get_object_or_404(ImportOrder,pk=pk)
        set_order_visibility([pk],action,request.user)
        messages.success(request,f'{order.reference} dismissed. Shopify refreshes and CSV uploads will keep it out of the import list.' if action=='dismiss' else f'{order.reference} restored. Review its current status before adding it to a plan.')
    except ValidationError as error:messages.error(request,'; '.join(error.messages))
    return visibility_redirect(request,dismissed=action=='restore')


def set_order_visibility(ids,action,user):
    from .models import ImportOrderVisibilityEvent
    if action not in ('dismiss','restore'):raise ValidationError('Choose Dismiss or Restore for this order.')
    if not ids:raise ValidationError('Select at least one order.')
    if len(ids)>1000:raise ValidationError('Dismiss at most 1,000 orders at a time.')
    try:ids=set(int(value) for value in ids)
    except (TypeError,ValueError):raise ValidationError('Select valid orders from the list.')
    with transaction.atomic():
        orders=list(ImportOrder.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
        if len(orders)!=len(ids):raise ValidationError('The selected orders changed. Refresh the list before dismissing them.')
        # Validate the entire selection before changing anything. The lock also
        # serializes dismissal with adding to a plan and source refreshes.
        if action=='dismiss' and any(order.imported_at for order in orders):
            raise ValidationError('A selected order is already in a roast plan. Remove its unstarted demand from the plan first. No selected orders were dismissed.')
        count=0
        for order in orders:
            if (action=='dismiss') != bool(order.dismissed_at):
                order.dismissed_at=timezone.now() if action=='dismiss' else None
                order.dismissed_by=user if action=='dismiss' else None
                order.save(update_fields=['dismissed_at','dismissed_by'])
                ImportOrderVisibilityEvent.objects.create(order=order,actor=user,action=action)
                count+=1
        return count


@staff_member_required
@require_POST
def dismiss_selected(request):
    try:
        count=set_order_visibility(request.POST.getlist('orders'),'dismiss',request.user)
        messages.success(request,f'Dismissed {count} orders. Shopify refreshes and CSV uploads will keep them out of the import list. Restore them under Dismissed orders if needed.')
    except ValidationError as error:messages.error(request,'; '.join(error.messages))
    return visibility_redirect(request)


def visibility_redirect(request,dismissed=False):
    params={}
    plan=request.POST.get('plan','')
    if plan.isdecimal():params['plan']=plan
    if dismissed:params['dismissed']='1'
    from urllib.parse import urlencode
    return redirect('/imports/'+('?' + urlencode(params) if params else ''))

@staff_member_required
def review_import(request,pk):
    from .subscription_planning import forecast_cycle
    def return_to_orders(order):
        cycle=forecast_cycle(order)
        return redirect('/imports/?plan='+str(cycle.plan_id) if cycle else '/imports/')
    order=get_object_or_404(ImportOrder,pk=pk)
    if order.imported_at or order.dismissed_at:return return_to_orders(order)
    if request.method=='POST':
        with transaction.atomic():
            order=ImportOrder.objects.select_for_update().get(pk=pk)
            if order.imported_at or order.dismissed_at:return return_to_orders(order)
            if request.POST.get('action')=='adopt_source':
                revision=hashlib.sha256(json.dumps([order.latest_lines,order.latest_api_signature,order.instructions],sort_keys=True).encode()).hexdigest()
                if not order.source_changed or request.POST.get('source_revision')!=revision:
                    messages.error(request,'The refreshed items changed again. Reload before accepting them.');return redirect('review_import',pk=pk)
                order.lines=order.latest_lines;order.source_signature=source_signature(order.lines,order.instructions)
                order.api_source_signature=order.latest_api_signature;order.latest_api_signature='';order.source_changed=False;order.latest_lines=[];order.save()
                messages.success(request,'Refreshed source accepted. Review these coffee allocations before adding the order.');return redirect('review_import',pk=pk)
            if order.source_changed:
                messages.error(request,'Review and accept the refreshed source items before editing the mapping.');return redirect('review_import',pk=pk)
            if request.POST.get('action')=='save_allocations':
                from .allocations import save_allocations
                try:
                    try:payload=json.loads(request.POST.get('allocations_json',''))
                    except (ValueError,TypeError):raise ValidationError('Choose valid coffee allocations before saving.')
                    save_allocations(order,payload,request.POST.get('review_revision'),request.user,request.POST.get('instructions_confirmed')=='on')
                    messages.success(request,'Assortment saved. Quantities match the original order; roast and packaging rules were checked.')
                    return return_to_orders(order)
                except ValidationError as error:
                    messages.error(request,'; '.join(error.messages));return redirect('review_import',pk=pk)
            order.instructions_confirmed=request.POST.get('instructions_confirmed')=='on'
            for index,line in enumerate(order.lines):
                prefix=f'line-{index}-'
                line['skip']=request.POST.get(prefix+'skip')=='on'
                line['coffee']=request.POST.get(prefix+'coffee') or None
                line['label_variant']=request.POST.get(prefix+'label') or None
                line['size_oz']=request.POST.get(prefix+'size') or None
                line['roast_level']=request.POST.get(prefix+'roast') or ''
                line['target_finish_temp_f']=request.POST.get(prefix+'temp') or None
                if prefix+'grind' in request.POST:
                    from .models import GRIND_CHOICES
                    value=request.POST[prefix+'grind'];line['grind']=value if value in dict(GRIND_CHOICES) else 'unknown'
            if request.POST.get('split_index') is not None:
                try:
                    index=int(request.POST['split_index']);line=order.lines[index]
                    total=Decimal(str(line.get('size_oz')))*int(line['quantity'])
                    if not total.is_finite() or total<=0 or total>800:raise ValueError()
                except (ValueError,TypeError,IndexError,InvalidOperation):
                    messages.error(request,'Enter a valid bag size first. Split at most 50 lb at a time.')
                    return redirect('review_import',pk=order.pk)
                portions=[];left=total;position=1
                while left>0:
                    item=copy.deepcopy(line);weight=min(Decimal(16),left)
                    item.update(quantity=1,size_oz=str(weight),coffee=None,label_variant=None,roast_level='',target_finish_temp_f=None,skip=False,line_key=str(line.get('line_key',index+1))+'.p'+str(position))
                    item['source_line']=line.get('source_line',line.get('line_key',str(index+1)))
                    item['source_total']=line.get('source_total') or str(total)
                    portions.append(item);left-=weight;position+=1
                order.lines=order.lines[:index]+portions+order.lines[index+1:]
                order.save();messages.success(request,'Split into 1 lb portions. Choose each portion’s coffee and standard roast for this cycle.')
                return redirect('review_import',pk=order.pk)
            order.save()
            for index,line in enumerate(order.lines):
                if request.POST.get(f'line-{index}-remember')!='on' or line.get('cycle_choice') or line.get('frac_bag') or line.get('bundle_id') or '.p' in str(line.get('line_key')):continue
                try:data=line_data(line)
                except ValidationError:continue
                if data is not None and not IncomingForm(data).is_valid():continue
                from .stores import remember_mapping
                if remember_mapping(order,line,request.user):continue
                ProductMapping.objects.update_or_create(fingerprint=mapping_key(line['title'],line.get('sku','')),defaults={'title':line['title'][:500],'sku':line.get('sku','')[:150],'coffee_id':line.get('coffee') if not line.get('skip') else None,'label_variant_id':line.get('label_variant') if not line.get('skip') else None,'size_oz':line.get('size_oz') or None,'skip':line.get('skip',False),'updated_by':request.user})
        messages.success(request,'Mapping saved. The order must pass quantity and roast checks before it can be added.')
        return return_to_orders(order)
    from .models import ROAST_LEVELS,GRIND_CHOICES
    from .subscription_planning import renewal_review_needed
    revision=hashlib.sha256(json.dumps([order.latest_lines,order.latest_api_signature,order.instructions],sort_keys=True).encode()).hexdigest()
    from .allocations import source_groups,review_token
    coffees=list(Coffee.objects.filter(active=True,experimental=False))
    return render(request,'portal/review_import.html',{'order':order,'source_revision':revision,'review_revision':review_token(order),'early_renewal_review':renewal_review_needed(order),'allocation_groups':source_groups(order),'allocation_coffees':[{'id':c.pk,'name':c.name,'roast':c.standard_roast,'locked':c.roast_locked} for c in coffees],'allocation_labels':list(LabelVariant.objects.filter(active=True).values('id','name','coffee_id')),'coffees':coffees,'labels':LabelVariant.objects.filter(active=True),'roasts':ROAST_LEVELS,'grinds':GRIND_CHOICES})
