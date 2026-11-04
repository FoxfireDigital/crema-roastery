"""Explicit, audited plan closure without releasing orders or rewriting results."""
from decimal import Decimal,InvalidOperation
import json
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404,render,redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import RoastPlan,PlanEvent,IncomingOrderLine,PlannedBatch,Batch,PackingProgress,RoastedStockAllocation,ImportOrder


def completion_checks(plan):
    from .packing import applicable_steps
    from .finished_coverage import plan_coverage
    coverage={item['group_id']:item for item in plan_coverage(plan)['rows']}
    issues=[];lines=list(IncomingOrderLine.objects.filter(group__plan=plan).select_related('group__coffee','product_coffee','product_label'))
    if not lines:issues.append('Add orders before closing a plan; use Delete for an empty draft.')
    progress={p.line_id:p for p in PackingProgress.objects.filter(line__in=lines)}
    for line in lines:
        label=line.reference or f'Order row #{line.pk}';accounted=Decimal(0)
        try:
            for pack in line.packaging:
                size=Decimal(str(pack['size_oz']));bags=Decimal(str(pack['bags']))
                if not size.is_finite() or size<=0 or not bags.is_finite() or bags<=0 or bags!=bags.to_integral_value():raise ValueError()
                accounted+=size*bags
        except (ValueError,KeyError,TypeError,InvalidOperation):accounted=Decimal(0)
        if not line.packaging or accounted!=line.finished_oz or line.grind not in ('whole','regular','fine','coarse'):issues.append(label+': confirm bag sizes, counts and grind.')
        p=progress.get(line.pk)
        if not p or any(not getattr(p,key) for key,_ in applicable_steps(line)):issues.append(label+': finish the customer’s packing checklist.')
    for group in plan.groups.select_related('coffee'):
        group_lines=[line for line in lines if line.group_id==group.pk]
        if not group_lines:continue
        ordered=sum((line.finished_oz for line in group_lines),Decimal(0))
        if coverage[group.pk]['recorded_total']<ordered:issues.append(f'{group.coffee.name}: new roast results plus bulk actually used do not yet cover the ordered coffee. Reserved bulk must be recorded as used first.')
    rows=list(PlannedBatch.objects.filter(group__plan=plan).select_related('batch'))
    if any(not row.batch_id for row in rows):issues.append('Finish or remove remaining unstarted draft loads.')
    actual=list(Batch.objects.filter(planned_group__plan=plan,merged_into__isnull=True))
    if any(b.roasted_oz is None or not all(getattr(b,key) for key in ('measured_at','roasted_at','cooled_at')) for b in actual):issues.append('Record finished weights and complete Measured, Roasted and Cooled for each roast. Finish bagging and sealing on the customer packing checklists.')
    if RoastedStockAllocation.objects.filter(line__group__plan=plan,status='reserved').exists():issues.append('Mark the bulk stock actually taken as used, or resolve unused reservations first.')
    for order in ImportOrder.objects.filter(imported_plan=plan,imported_at__isnull=False):
        from .subscription_planning import forecast_hold
        early=forecast_hold(order)
        if early is not None:
            if early:issues.append(order.reference+': '+early)
            continue
        if order.source_flags or order.source_changed or order.cancelled or order.financial_status!='paid' or order.fulfillment_status not in ('unfulfilled','fulfilled'):
            issues.append(order.reference+': review the changed source items, payment or fulfillment status before closing.')
    return list(dict.fromkeys(issues))


def completion_snapshot(plan):
    from .packing import applicable_steps
    from .finished_coverage import plan_coverage
    lines=list(IncomingOrderLine.objects.filter(group__plan=plan).select_related('product_coffee','product_label','group__coffee'))
    progress={p.line_id:p for p in PackingProgress.objects.filter(line__in=lines)}
    result={'date':plan.date,'orders':[{'id':line.pk,'reference':line.reference,'customer':line.customer,'coffee':line.ordered_coffee.name,
        'label':line.ordered_label.name if line.ordered_label else 'Standard label','roast':line.group.roast_level,'finished_oz':line.finished_oz,
        'grind':line.get_grind_display(),'packaging':line.packaging,'packing':{key:getattr(progress[line.pk],key) for key,_ in applicable_steps(line)}} for line in lines],
        'batches':[{'id':b.pk,'coffee':b.coffee.name,'roaster':b.roaster.name,'roast':b.roast_level,'green_oz':b.green_oz,'roasted_oz':b.roasted_oz,'operator':b.operator.username,'measured_at':b.measured_at,'roasted_at':b.roasted_at,'cooled_at':b.cooled_at,'sealed_at':b.sealed_at,'merged_into':b.merged_into_id} for b in Batch.objects.filter(planned_group__plan=plan).select_related('coffee','roaster','operator').order_by('pk')],
        'shopify_orders':list(ImportOrder.objects.filter(imported_plan=plan,imported_at__isnull=False).values('pk','reference','external_id')),
        'stock':[{'stock_id':a.stock_id,'line_id':a.line_id,'amount_oz':a.amount_oz,'source_coffee':a.stock.coffee.name,'ordered_coffee':a.line.ordered_coffee.name} for a in RoastedStockAllocation.objects.filter(line__group__plan=plan,status='used').select_related('stock__coffee','line__product_coffee','line__group__coffee')]}
    result['finished_coverage']=plan_coverage(plan)
    return json.loads(json.dumps(result,default=str))


@staff_member_required
@require_http_methods(['GET','POST'])
def close_plan(request,pk,reopen=False):
    plan=get_object_or_404(RoastPlan.all_objects,pk=pk,historical=False,removed_at__isnull=True)
    error='';status=200
    if request.method=='POST':
        try:
            with transaction.atomic():
                plan=get_object_or_404(RoastPlan.all_objects.select_for_update(),pk=pk,historical=False,removed_at__isnull=True)
                if not reopen and plan.closed_at:return redirect('/plans/'+str(pk)+'/completed/')
                if reopen and not plan.closed_at:return redirect('/planning/?plan='+str(pk))
                if request.POST.get('version')!=str(plan.version):raise ValidationError('This plan changed. Reload the completion review before continuing.')
                if reopen:
                    reason=request.POST.get('reason','').strip()
                    if not reason or len(reason)>300:raise ValidationError('Enter a brief reason for reopening, up to 300 characters.')
                    before={'closed_at':plan.closed_at,'closed_by':plan.closed_by_id}
                    plan.closed_at=None;plan.closed_by=None
                    # Explicit reopening authorizes correction of already completed
                    # work. New demand still uses the ordinary revision checks.
                    changed=ImportOrder.objects.filter(imported_plan=plan,imported_at__isnull=False).exclude(source_changed=False,cancelled=False,financial_status='paid',fulfillment_status__in=['unfulfilled','fulfilled']).exists()
                    if changed:plan.accepted_at=None;plan.accepted_by=None
                    elif not plan.accepted_at:plan.accepted_at=timezone.now();plan.accepted_by=request.user
                    details={'before':json.loads(json.dumps(before,default=str)),'reason':reason};action='reopened'
                else:
                    issues=completion_checks(plan)
                    if issues:raise ValidationError(issues)
                    details={'snapshot':completion_snapshot(plan)};action='closed'
                    plan.closed_at=timezone.now();plan.closed_by=request.user
                plan.version+=1;plan.save(update_fields=['closed_at','closed_by','accepted_at','accepted_by','version'])
                PlanEvent.objects.create(plan=plan,actor=request.user,action=action,details=details)
            messages.success(request,'Plan reopened for corrections. Original closure history is retained.' if reopen else 'Plan closed. Its order links, weights and packing history are retained under Completed plans.')
            return redirect('/planning/?plan='+str(pk) if reopen else '/plans/'+str(pk)+'/completed/')
        except ValidationError as exc:error='; '.join(exc.messages);status=400
    issues=[] if reopen or plan.closed_at else completion_checks(plan)
    from .finished_coverage import plan_coverage
    return render(request,'portal/close_plan.html',{'plan':plan,'coverage':plan_coverage(plan),'reopen':reopen,'issues':issues,'error':error},status=status)


@staff_member_required
def completed_plan(request,pk):
    plan=get_object_or_404(RoastPlan.all_objects.select_related('closed_by'),pk=pk,closed_at__isnull=False,historical=False)
    event=plan.events.filter(action='closed').first()
    snapshot=event.details.get('snapshot',{}) if event else {}
    from .finished_coverage import snapshot_coverage
    return render(request,'portal/completed_plan.html',{'plan':plan,'snapshot':snapshot,'coverage':snapshot_coverage(snapshot,plan.pk),'events':plan.events.select_related('actor')[:30]})
