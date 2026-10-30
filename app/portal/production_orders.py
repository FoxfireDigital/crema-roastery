"""A shipping fulfillment is not proof of production; retain explicit decisions."""
import hashlib,json
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect,render
from django.views.decorators.http import require_http_methods
from .models import ImportOrder,OrderReviewEvent,RoastPlan,IncomingOrderLine

SALT='crema-production-confirmation-v1'


def source_fingerprint(order):
    data=[order.pk,order.external_id,order.imported_plan_id,str(order.imported_at),order.source_signature,order.api_source_signature,order.latest_api_signature,order.source_changed,order.latest_lines,order.lines,order.financial_status,order.fulfillment_status,order.cancelled,order.source_flags,order.instructions,order.instructions_confirmed]
    return hashlib.sha256(json.dumps(data,sort_keys=True,default=str).encode()).hexdigest()


def last_confirmation(order):
    return order.review_events.filter(after__has_key='production_confirmation').first()


def production_confirmed(order):
    event=last_confirmation(order)
    decision=event.after['production_confirmation'] if event else {}
    return bool(order.imported_at and decision.get('state')=='confirmed' and decision.get('fingerprint')==source_fingerprint(order))


def invalidate_confirmation(order):
    event=last_confirmation(order)
    if event and event.after['production_confirmation'].get('state')=='confirmed' and not production_confirmed(order):
        # The actor owns the prior review; this event explicitly identifies the
        # automatic refresh, rather than attributing another click to that person.
        OrderReviewEvent.objects.create(order=order,actor=event.actor,before=event.after,after={'production_confirmation':{'state':'invalidated','automatic':True,'reason':'Source/order assignment changed after confirmation','fingerprint':source_fingerprint(order)}})


def source_hold_reason(order):
    if order.source_flags:return '; '.join(order.source_flags)
    if order.source_changed:return 'Source items changed — review refreshed items'
    if order.cancelled:return 'Cancelled source order — review required'
    if order.financial_status!='paid':return 'Payment / refund status needs review'
    if order.fulfillment_status=='unfulfilled':return ''
    if order.fulfillment_status=='fulfilled' and production_confirmed(order):return ''
    return 'Shipping marked fulfilled — confirm remaining production' if order.fulfillment_status=='fulfilled' else 'Delivery status / partial quantities need review'


def confirm_remaining_production(order,actor,reason,origin='portal'):
    if not actor.is_active or not actor.is_staff:raise ValidationError('Staff access is required.')
    reason=str(reason).strip()
    if not reason or len(reason)>300:raise ValidationError('Record a reason of 1–300 characters.')
    plan=order.imported_plan
    if not order.imported_at or not plan or plan.closed_at or plan.historical or plan.removed_at or order.dismissed_at:raise ValidationError('Use an existing order on an active plan; completed history cannot return to production here.')
    if order.fulfillment_status!='fulfilled' or order.cancelled or order.financial_status!='paid' or order.source_changed or order.source_flags:raise ValidationError('Only unchanged, paid orders marked fulfilled can be confirmed here. Review item, payment, cancellation or partial-delivery changes separately.')
    if not IncomingOrderLine.objects.filter(import_order=order,group__plan=plan).exists():raise ValidationError('This order has no active demand on that plan.')
    if production_confirmed(order):return False
    previous=last_confirmation(order)
    OrderReviewEvent.objects.create(order=order,actor=actor,before=previous.after if previous else {},after={'production_confirmation':{'state':'confirmed','fingerprint':source_fingerprint(order),'plan':plan.pk,'reason':reason,'origin':origin,'meaning':'Retain existing demand and recorded results; remaining production/packing is still needed.'}})
    return True


def review_token(order,user):
    return signing.dumps({'order':order.pk,'source':source_fingerprint(order),'plan_version':order.imported_plan.version,'actor':user.pk},salt=SALT)


@staff_member_required
@require_http_methods(['GET','POST'])
def review_production(request,pk):
    order=get_object_or_404(ImportOrder.objects.select_related('imported_plan'),pk=pk)
    if not order.imported_plan_id:return redirect('order_import')
    error='';status=200
    if request.method=='POST':
        try:
            with transaction.atomic():
                plan=RoastPlan.all_objects.select_for_update().get(pk=order.imported_plan_id)
                order=ImportOrder.objects.select_for_update(of=('self',)).select_related('imported_plan').get(pk=pk)
                if order.imported_plan_id!=plan.pk:raise ValidationError('This order moved to another plan. Reload before confirming.')
                supplied=signing.loads(request.POST.get('review_token',''),salt=SALT,max_age=1800)
                expected={'order':order.pk,'source':source_fingerprint(order),'plan_version':plan.version,'actor':request.user.pk}
                if supplied!=expected:raise ValidationError('The order or plan changed. Reload before confirming.')
                if request.POST.get('confirmed')!='on':raise ValidationError('Confirm that production/packing is still needed for the existing demand.')
                confirm_remaining_production(order,request.user,request.POST.get('reason',''))
            messages.success(request,'Remaining production confirmed. Existing results and demand were retained. Review and accept the plan to continue.')
            return redirect('/planning/?plan='+str(order.imported_plan_id))
        except (ValidationError,signing.BadSignature) as exc:error='; '.join(exc.messages) if isinstance(exc,ValidationError) else 'The review expired. Reload before confirming.';status=409
    return render(request,'portal/production_order_review.html',{'order':order,'error':error,'confirmed':production_confirmed(order),'review_token':review_token(order,request.user),'demand':IncomingOrderLine.objects.filter(import_order=order).select_related('group__coffee')},status=status)
