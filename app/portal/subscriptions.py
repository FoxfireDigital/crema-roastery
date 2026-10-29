import csv,io,json
from pathlib import Path
from datetime import timedelta
from decimal import Decimal
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.shortcuts import render,redirect
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import SubscriptionContract,Coffee
from .order_import import infer_item

def clean(value):return (value or '').strip().lstrip("'")

def parse_contracts(raw):
    if len(raw)>5*1024*1024:raise ValidationError('Use an export smaller than 5 MB.')
    try:reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline=''))
    except UnicodeDecodeError:raise ValidationError('Use a UTF-8 subscription export.')
    if not {'handle','status','upcoming_billing_date','line_variant_id','line_quantity'}.issubset(reader.fieldnames or []):raise ValidationError('This is not a Shopify Subscriptions contract export.')
    variant_map=json.loads(Path(__file__).resolve().parent.parent.joinpath('shopify-variant-map.json').read_text())
    contracts={};current=None
    for index,row in enumerate(reader):
        if index>=10000:raise ValidationError('Use at most 10,000 export lines.')
        key=clean(row.get('handle')) or current
        if not key:raise ValidationError('Subscription line is missing its contract handle.')
        if key not in contracts:
            status=clean(row.get('status')).upper()
            if status not in ['ACTIVE','CANCELLED','PAUSED','EXPIRED','FAILED']:raise ValidationError('Subscription has an unknown status.')
            stamp=clean(row.get('upcoming_billing_date'));parsed=parse_datetime(stamp) if stamp else None
            if stamp and not parsed:raise ValidationError('Subscription has an invalid next billing date.')
            if parsed and timezone.is_naive(parsed):parsed=timezone.make_aware(parsed)
            try:interval_count=int(clean(row.get('cadence_interval_count')) or 1)
            except ValueError:raise ValidationError('Invalid subscription interval.')
            contracts[key]={'external_id':key,'customer':' '.join(filter(None,[clean(row.get('delivery_address_first_name')),clean(row.get('delivery_address_last_name'))]))[:120],'status':status,'next_billing_at':parsed,'interval':clean(row.get('cadence_interval')),'interval_count':interval_count,'delivery_method':clean(row.get('delivery_method_type')),'lines':[]}
        variant_id=clean(row.get('line_variant_id'))
        if variant_id:
            try:quantity=int(clean(row.get('line_quantity')))
            except ValueError:raise ValidationError('Invalid subscription quantity.')
            if quantity<=0:raise ValidationError('Subscription quantity must be positive.')
            resolved=variant_map.get(variant_id,{})
            title=' - '.join(filter(None,[resolved.get('product'),resolved.get('variant')])) or 'Unmapped variant '+variant_id
            item=infer_item(title,quantity,resolved.get('sku') or '',clean(row.get('line_selling_plan_name')))
            item['variant_id']=variant_id;item['product']=resolved.get('product','');item['variant']=resolved.get('variant','')
            item['needs_cycle_assignment']=resolved.get('handle')=='monthly-coffee-subscription'
            item['finished_oz']=str(Decimal(item['size_oz'])*quantity) if item['size_oz'] else None
            item['roast_review']=False
            if item['coffee']:
                coffee=Coffee.objects.get(pk=item['coffee'])
                item['roast_review']=bool((coffee.roast_locked or (item['finished_oz'] and Decimal(item['finished_oz'])<80)) and coffee.standard_roast!=item['roast_level'])
            contracts[key]['lines'].append(item)
        current=key
    return list(contracts.values())

def stage_contracts(raw):
    contracts=parse_contracts(raw)
    with transaction.atomic():
        for data in contracts:
            key=data.pop('external_id');SubscriptionContract.objects.update_or_create(external_id=key,defaults=data)
    return len(contracts)

@staff_member_required
def subscriptions(request):
    if request.method=='POST':
        try:
            uploaded=request.FILES.get('subscriptions_csv')
            if not uploaded:raise ValidationError('Choose a Shopify Subscriptions export.')
            if uploaded.size>5*1024*1024:raise ValidationError('Use an export smaller than 5 MB.')
            count=stage_contracts(uploaded.read());messages.success(request,f'Refreshed {count} subscription contracts. Production demand is unchanged.')
            return redirect('subscriptions')
        except ValidationError as error:messages.error(request,'; '.join(error.messages))
    status=request.GET.get('status','ACTIVE')
    contracts=SubscriptionContract.objects.all()
    if status!='ALL':contracts=contracts.filter(status=status)
    totals={s:SubscriptionContract.objects.filter(status=s).count() for s in ['ACTIVE','PAUSED','CANCELLED']}
    next_week=SubscriptionContract.objects.filter(status='ACTIVE',next_billing_at__gte=timezone.now(),next_billing_at__lte=timezone.now()+timedelta(days=7)).count()
    from .shopify import connection_status
    last_export=SubscriptionContract.objects.aggregate(last=Max('refreshed_at'))['last']
    return render(request,'portal/subscriptions.html',{'contracts':contracts,'selected_status':status,'totals':totals,'next_week':next_week,'last_export':last_export,'shopify_status':connection_status()})
