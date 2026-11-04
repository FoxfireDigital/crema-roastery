"""Explicit early production, separate from billing; never infer renewal identities."""
import copy,hashlib,json
from datetime import datetime,time,timedelta
from decimal import Decimal,InvalidOperation
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404,render,redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import SubscriptionContract,SubscriptionCycle,RoastPlan,ImportOrder,IncomingOrderLine,PlanEvent,OrderReviewEvent


def window(plan):
    start=max(timezone.now(),timezone.make_aware(datetime.combine(plan.date,time.min)))
    return start,start+timedelta(days=4)


def upcoming(plan):
    start,end=window(plan)
    return SubscriptionContract.objects.filter(status='ACTIVE',next_billing_at__gte=start,next_billing_at__lte=end).order_by('next_billing_at','pk')


def schedule_token(contract,plan):
    return hashlib.sha256(json.dumps([plan.pk,plan.version,contract.pk,contract.status,str(contract.next_billing_at),str(contract.refreshed_at),contract.lines],sort_keys=True).encode()).hexdigest()


def forecast_cycle(order):
    return SubscriptionCycle.objects.filter(forecast_order_id=order.pk).select_related('plan','contract','renewal_order').first()


def pending_cycles():
    # Unmatched history is deliberately retained until a human identifies the renewal.
    return SubscriptionCycle.objects.filter(renewal_order__isnull=True,forecast_order__dismissed_at__isnull=True,plan__removed_at__isnull=True).select_related('plan','contract','forecast_order').order_by('pk')


def renewal_signature(order):
    from .production_orders import source_fingerprint
    return source_fingerprint(order)


def renewal_review_needed(order):
    if order.subscription!='recurring' or forecast_cycle(order) or SubscriptionCycle.objects.filter(renewal_order=order).exists():return False
    ids=list(pending_cycles().values_list('pk',flat=True))
    if not ids:return False
    last=order.review_events.filter(after__has_key='early_subscription_review').first()
    saved=last.after['early_subscription_review'] if last else {}
    return saved!={'source':renewal_signature(order),'unrelated_cycles':ids}


def forecast_hold(order):
    cycle=forecast_cycle(order)
    if not cycle:return None
    if order.cancelled or order.source_flags or order.source_changed:return 'Early delivery changed — review its saved production choices'
    if cycle.renewal_order_id:
        actual=cycle.renewal_order
        if actual.cancelled or actual.source_flags or actual.source_changed or actual.financial_status!='paid' or actual.fulfillment_status not in ('unfulfilled','fulfilled'):
            return 'Linked subscription renewal changed or is unpaid — review its source status'
        linked=cycle.plan.events.filter(action='subscription_linked',details__cycle=cycle.pk).first()
        if not linked or linked.details.get('items')!=renewal_items(actual):return 'Linked renewal items changed after matching — review early production before continuing'
    elif cycle.contract.status!='ACTIVE':return 'Subscription is no longer active — review early production'
    if cycle.plan.removed_at:return 'The early-production plan was removed — restore and review it'
    return ''


def renewal_items(order):
    lines=[{k:v for k,v in item.items() if k!='fulfilled'} for item in order.lines]
    return hashlib.sha256(json.dumps([order.source_signature,order.api_source_signature,lines,order.instructions],sort_keys=True).encode()).hexdigest()


@staff_member_required
@require_http_methods(['GET','POST'])
def review_upcoming(request,pk):
    plan=get_object_or_404(RoastPlan,pk=pk,historical=False,closed_at__isnull=True)
    error='';status=200
    if request.method=='POST':
        try:
            with transaction.atomic():
                plan=get_object_or_404(RoastPlan.objects.select_for_update(),pk=pk,historical=False,closed_at__isnull=True)
                if request.POST.get('version')!=str(plan.version):raise ValidationError('This plan changed. Reload before choosing subscriptions.')
                contract=get_object_or_404(SubscriptionContract.objects.select_for_update(),pk=request.POST.get('contract'))
                if request.POST.get('schedule')!=schedule_token(contract,plan) or not upcoming(plan).filter(pk=contract.pk).exists():raise ValidationError('This subscription schedule changed or is outside the next four days. Reload before continuing.')
                if request.POST.get('confirmed')!='on':raise ValidationError('Confirm that you want to prepare this delivery before its charge date.')
                cycle=SubscriptionCycle.objects.filter(contract=contract,due_at=contract.next_billing_at).first()
                if cycle and cycle.plan_id!=plan.pk:raise ValidationError('This delivery already belongs to another plan. Open that plan rather than adding it twice.')
                if not cycle:
                    from .order_import import source_signature,expand_frac_line
                    lines=[]
                    for index,raw in enumerate(contract.lines,1):
                        item=copy.deepcopy(raw);size=item.get('size_oz');quantity=item.get('quantity')
                        try:
                            total=Decimal(str(size))*int(quantity)
                            if not total.is_finite() or total<=0 or total>160000:raise ValueError()
                        except (InvalidOperation,ValueError,TypeError):raise ValidationError('This contract needs a confirmed bag size and quantity. Refresh its export before preparing it.')
                        item.update(source_line=str(index),line_key=str(index),source_total=str(total),source_quantity=quantity,fulfilled=False)
                        if item.get('needs_cycle_assignment') or item.get('cycle_choice'):
                            item.update(coffee=None,label_variant=None,roast_level='',target_finish_temp_f=None,cycle_choice=True)
                        lines.extend(expand_frac_line(item))
                    if not lines:raise ValidationError('This subscription has no known delivery items. Refresh its export first.')
                    key='advance_'+hashlib.sha256(f'{contract.pk}:{contract.next_billing_at.isoformat()}'.encode()).hexdigest()
                    order=ImportOrder.objects.create(external_id=key,reference=f'Subscription {contract.pk} · {timezone.localtime(contract.next_billing_at):%b %d}',customer=contract.customer,received_at=contract.next_billing_at,due_on=timezone.localtime(contract.next_billing_at).date(),financial_status='scheduled',fulfillment_status='unfulfilled',subscription='recurring',lines=lines,source_signature=source_signature(lines,''))
                    cycle=SubscriptionCycle.objects.create(contract=contract,due_at=contract.next_billing_at,plan=plan,forecast_order=order,schedule_refreshed_at=contract.refreshed_at)
                    PlanEvent.objects.create(plan=plan,actor=request.user,action='subscription_staged',details={'cycle':cycle.pk,'contract':contract.pk,'due':contract.next_billing_at.isoformat(),'meaning':'Early production only. No payment, billing or Shopify order was created.'})
            messages.success(request,'Delivery prepared for review. Choose this cycle’s coffees and bag sizes before adding it to the plan. No billing or payment changed.')
            return redirect('/imports/'+str(cycle.forecast_order_id)+'/review/')
        except ValidationError as exc:error='; '.join(exc.messages);status=409
    rows=[]
    for contract in upcoming(plan):
        rows.append({'contract':contract,'schedule':schedule_token(contract,plan),'cycle':SubscriptionCycle.objects.filter(contract=contract,due_at=contract.next_billing_at).select_related('forecast_order','plan').first()})
    return render(request,'portal/subscription_planning.html',{'plan':plan,'rows':rows,'cycles':plan.subscription_cycles.select_related('contract','forecast_order','renewal_order'),'error':error},status=status)


def original_total(order):
    from .allocations import source_groups
    try:
        groups=source_groups(order)
        if not groups or any(g['expected_oz'] is None for g in groups):return None
        return sum((Decimal(str(g['expected_oz'])) for g in groups),Decimal(0))
    except (TypeError,ValueError,InvalidOperation):return None


@staff_member_required
@require_http_methods(['GET','POST'])
def reconcile_renewal(request,pk):
    order=get_object_or_404(ImportOrder,pk=pk);error='';status=200
    def candidates():
        from django.db.models import Q
        return SubscriptionCycle.objects.filter(Q(pk__in=pending_cycles().values('pk'))|Q(renewal_order=order)).select_related('plan','contract','forecast_order').order_by('pk')
    cycles=list(candidates())
    revision=hashlib.sha256(json.dumps([renewal_signature(order),[(c.pk,c.plan.version,c.forecast_order.lines) for c in cycles]],sort_keys=True).encode()).hexdigest()
    if request.method=='POST':
        try:
            with transaction.atomic():
                # Serialize against adding/removing early deliveries or closing their plans.
                list(RoastPlan.all_objects.select_for_update().filter(pk__in=[c.plan_id for c in cycles]).order_by('pk'))
                order=ImportOrder.objects.select_for_update().get(pk=pk)
                fresh=list(candidates())
                current=hashlib.sha256(json.dumps([renewal_signature(order),[(c.pk,c.plan.version,c.forecast_order.lines) for c in fresh]],sort_keys=True).encode()).hexdigest()
                if request.POST.get('revision')!=current or revision!=current:raise ValidationError('An order or early plan changed. Reload before linking.')
                if request.POST.get('confirmed')!='on':raise ValidationError('Review the customer, delivery, coffee quantities and date before confirming.')
                if order.imported_at or forecast_cycle(order) or order.subscription!='recurring':raise ValidationError('Use an unassigned recurring renewal order.')
                choice=request.POST.get('cycle','')
                prior=SubscriptionCycle.objects.filter(renewal_order=order).first()
                if prior and str(prior.pk)!=choice:raise ValidationError('This renewal is already linked. Keep that delivery; reassignment needs a separate production review.')
                if choice=='unrelated':
                    OrderReviewEvent.objects.create(order=order,actor=request.user,before={},after={'early_subscription_review':{'source':renewal_signature(order),'unrelated_cycles':[c.pk for c in fresh]}})
                else:
                    cycle=next((c for c in fresh if str(c.pk)==choice),None)
                    if not cycle:raise ValidationError('Choose an existing early delivery or confirm that this is a different delivery.')
                    if order.cancelled or order.source_flags or order.source_changed or order.financial_status!='paid':raise ValidationError('Review item changes, cancellation and payment before linking this renewal.')
                    total=original_total(order)
                    if total is None or total!=original_total(cycle.forecast_order):raise ValidationError('The original delivery totals differ or are unknown. Review the source items before linking; no demand was changed.')
                    cycle=SubscriptionCycle.objects.select_for_update().get(pk=cycle.pk)
                    if cycle.renewal_order_id and cycle.renewal_order_id!=order.pk:raise ValidationError('This delivery was already linked. Reload before continuing.')
                    cycle.renewal_order=order;cycle.save(update_fields=['renewal_order'])
                    PlanEvent.objects.create(plan=cycle.plan,actor=request.user,action='subscription_linked',details={'cycle':cycle.pk,'renewal':order.pk,'reference':order.reference,'items':renewal_items(order),'meaning':'Renewal covers the existing early demand. No extra orders, roasts, packing or stock use were added.'})
                    OrderReviewEvent.objects.create(order=order,actor=request.user,before={},after={'early_subscription_cycle':cycle.pk,'plan':cycle.plan_id})
            messages.success(request,'Subscription renewal reviewed. Existing early production was retained without adding it again.')
            return redirect('/imports/')
        except ValidationError as exc:error='; '.join(exc.messages);status=409
    return render(request,'portal/subscription_renewal.html',{'order':order,'cycles':cycles,'revision':revision,'error':error,'total':original_total(order)},status=status)
