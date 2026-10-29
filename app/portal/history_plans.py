"""Past sessions retain source records and date-based order associations."""
from bisect import bisect_left
from datetime import date
from decimal import Decimal
import hashlib,json
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404,render,redirect
from django.utils import timezone
from django.views.decorators.http import require_GET,require_POST
from .models import HistoricalRoast,RoastPlan,PlanEvent,PlannedBatch,ImportOrder,IncomingOrderLine,RoastedStockAllocation


@transaction.atomic
def rebuild_history(actor,completed_plan_ids=()):
    if not actor.is_staff:raise ValidationError('An administrator is required.')
    # Lock existing plans before their records, as the production editor does.
    existing=list(RoastPlan.all_objects.select_for_update().order_by('pk'))
    past={p.date:p for p in existing if p.historical}
    restored=[];created=[];linked=0;assigned=0;skipped_current=[];released=[]
    for pk in completed_plan_ids:
        plan=next((p for p in existing if p.pk==pk),None)
        if not plan:raise ValidationError('The recorded plan no longer exists.')
        if plan.closed_at:raise ValidationError('Closed portal sessions stay in Completed plans; reopen before changing their classification.')
        if plan.historical:continue
        rows=PlannedBatch.objects.filter(group__plan=plan)
        if not rows.exists() or rows.filter(batch__isnull=True).exists() or rows.filter(batch__roasted_at__isnull=True).exists():
            raise ValidationError('Only a fully roasted plan can be moved into past plans.')
        if RoastedStockAllocation.objects.filter(line__group__plan=plan,status='reserved').exists():
            raise ValidationError('Resolve outstanding stock reservations before archiving the plan.')
        if plan.date in past:raise ValidationError('That roast date already has a historical plan. Review the duplicate before merging.')
        before={'removed_at':str(plan.removed_at) if plan.removed_at else None,'removed_by':plan.removed_by_id,'historical':False}
        plan.historical=True;plan.removed_at=None;plan.removed_by=None;plan.version+=1
        plan.save(update_fields=['historical','removed_at','removed_by','version'])
        PlanEvent.objects.create(plan=plan,actor=actor,action='history_restored',details={'before':before})
        past[plan.date]=plan;restored.append(plan.pk)
    records=list(HistoricalRoast.objects.select_for_update().filter(date__isnull=False).order_by('date','id'))
    for record in records:
        if record.date>timezone.localdate():continue
        if any(flag.startswith('Date outside ') for flag in record.flags):continue
        plan=past.get(record.date)
        if not plan:
            plan=RoastPlan.all_objects.create(date=record.date,created_by=actor,historical=True,use_roasted_stock=False)
            past[record.date]=plan;created.append(plan.pk)
            PlanEvent.objects.create(plan=plan,actor=actor,action='history_created',details={'basis':'Recorded roasting date; original workbook rows retained.'})
        if record.plan_id!=plan.pk:
            before=record.plan_id
            HistoricalRoast.objects.filter(pk=record.pk).update(plan=plan)
            PlanEvent.objects.create(plan=plan,actor=actor,action='history_row',details={'record':record.pk,'previous_plan':before,'source_key':record.source_key})
            linked+=1
    days=sorted(past)
    for order in ImportOrder.objects.select_for_update(of=('self',)).select_related('imported_plan').order_by('pk'):
        if not days:break
        if order.history_assignment_locked:continue
        day=timezone.localdate(order.received_at)
        if day<date(days[0].year,1,1):continue
        index=bisect_left(days,day)
        if index==len(days):continue
        destination=past[days[index]]
        previous=days[index-1] if index else None
        # User work in a current plan is never displaced by a history rebuild.
        if order.imported_plan_id and order.imported_plan_id!=destination.pk and not order.imported_plan.historical and order.imported_plan.removed_at is None:
            skipped_current.append(order.pk);continue
        if order.imported_plan_id==destination.pk and order.imported_at:continue
        old_lines=IncomingOrderLine.objects.select_for_update().filter(source__in=['shopify','store'],external_id__startswith=order.external_id+':').exclude(group__plan=destination)
        old_line_ids=list(old_lines.values_list('pk',flat=True))
        if old_line_ids:
            # Keep the old production links recoverable. Do not move actual
            # roasts or invent new order quantities from roasted output.
            old_lines.update(removed_at=timezone.now());released.extend(old_line_ids)
        before={'plan':order.imported_plan_id,'imported_at':str(order.imported_at) if order.imported_at else None,'removed_at':str(order.removed_at) if order.removed_at else None,'released_lines':old_line_ids}
        order.imported_plan=destination;order.imported_at=order.imported_at or timezone.now()
        order.save(update_fields=['imported_plan','imported_at'])
        PlanEvent.objects.create(plan=destination,actor=actor,action='history_order',details={'order':order.pk,'before':before,'basis':'Received date after previous roast date through this roast date, {{ portal_timezone }}. Includes same-day orders; not proof of fulfillment.','after_previous_date':str(previous) if previous else None,'through_date':str(destination.date)})
        assigned+=1
    return {'created_plans':created,'restored_plans':restored,'linked_workbook_rows':linked,'associated_orders':assigned,'released_old_lines':released,'current_orders_unchanged':skipped_current}


@staff_member_required
@require_POST
def associate_history(request):
    try:
        result=rebuild_history(request.user)
        messages.success(request,f"Associated {result['associated_orders']} orders with past roast dates. {len(result['current_orders_unchanged'])} orders in current plans were left in place. Original statuses and roast results are retained.")
    except ValidationError as error:messages.error(request,'; '.join(error.messages))
    return redirect('/plans/?history=1')


def association_token(order):
    event=PlanEvent.objects.filter(action__in=['history_move','history_move_undo'],details__order=order.pk).order_by('-pk').first()
    return hashlib.sha256(json.dumps([order.pk,order.imported_plan_id,order.history_assignment_locked,event.pk if event else None,list(IncomingOrderLine.all_objects.filter(source__in=['shopify','store'],external_id__startswith=order.external_id+':').order_by('pk').values_list('pk','group__plan_id','removed_at'))],default=str).encode()).hexdigest()


@staff_member_required
@require_POST
def move_history_order(request,pk):
    current=get_object_or_404(ImportOrder,pk=pk);return_plan=current.imported_plan_id
    try:
        with transaction.atomic():
            # Keep plan -> order lock ordering consistent with history rebuilds.
            plans={p.pk:p for p in RoastPlan.all_objects.select_for_update().filter(historical=True).order_by('pk')}
            order=get_object_or_404(ImportOrder.objects.select_for_update(),pk=pk)
            if order.imported_plan_id not in plans:raise ValidationError('Only orders already in past plans can be reassigned here.')
            if request.POST.get('revision')!=association_token(order):raise ValidationError('This order association changed. Reload before correcting it.')
            if request.POST.get('action')=='undo':
                old=PlanEvent.objects.filter(action__in=['history_move','history_move_undo'],details__order=pk).order_by('-pk').first()
                if not old or old.action!='history_move' or str(old.pk)!=request.POST.get('event') or order.imported_plan_id!=old.plan_id:raise ValidationError('This reassignment can no longer be undone here.')
                target=plans.get(old.details['before']['plan'])
                if not target:raise ValidationError('The original past plan is unavailable.')
                order.imported_plan=target;order.history_assignment_locked=old.details['before']['locked']
                for row in old.details['before']['lines']:
                    IncomingOrderLine.all_objects.filter(pk=row['id'],group__plan=target).update(removed_at=row['removed_at'])
                action='history_move_undo';details={'order':pk,'undoes':old.pk,'from_plan':old.plan_id,'to_plan':target.pk}
            else:
                try:target=plans.get(int(request.POST.get('target','')))
                except (TypeError,ValueError):target=None
                reason=request.POST.get('reason','').strip()[:300]
                if not target or target.removed_at or target.pk==order.imported_plan_id:raise ValidationError('Choose a different available past roast date.')
                if not reason:raise ValidationError('Add a brief reason for correcting the date association.')
                lines=IncomingOrderLine.objects.filter(source__in=['shopify','store'],external_id__startswith=order.external_id+':').exclude(group__plan=target)
                before={'plan':order.imported_plan_id,'locked':order.history_assignment_locked,'lines':list(lines.values('id','removed_at'))}
                lines.update(removed_at=timezone.now())
                order.imported_plan=target;order.history_assignment_locked=True
                action='history_move';details={'order':pk,'before':before,'reason':reason,'basis':'Manually confirmed association; original actual roast results unchanged.'}
            order.save(update_fields=['imported_plan','history_assignment_locked'])
            PlanEvent.objects.create(plan=target,actor=request.user,action=action,details=details);return_plan=target.pk
        messages.success(request,'Past order association corrected. Actual roasts and Shopify fulfillment are unchanged. Manual corrections are preserved during date-based rebuilds.')
    except ValidationError as error:messages.error(request,'; '.join(error.messages))
    return redirect('/plans/'+str(return_plan)+'/history/')


@login_required
@require_GET
def past_plan(request,pk):
    plan=get_object_or_404(RoastPlan.all_objects,historical=True,pk=pk)
    workbook=list(plan.workbook_roasts.order_by('workbook','sheet','row_number'))
    actual=list(PlannedBatch.all_objects.filter(group__plan=plan,batch__isnull=False).select_related('batch__operator','batch__coffee','batch__roaster','group').order_by('batch__roaster__name','id'))
    # Distinguish the workbook transcription from portal-recorded roasts. They
    # are independent source records; never silently sum possible duplicates.
    orders=list(ImportOrder.objects.filter(imported_plan=plan).order_by('received_at','id'))
    for order in orders:
        order.history_items=[{'title':str(item.get('title','Coffee details not supplied')),'quantity':item.get('quantity',1)} for item in order.lines]
        dated=PlanEvent.objects.filter(action='history_order',details__order=order.pk).exists()
        order.association_basis='Manually confirmed' if order.history_assignment_locked else 'Assigned by date' if dated else 'Recorded plan link'
        order.association_revision=association_token(order)
        event=PlanEvent.objects.filter(action__in=['history_move','history_move_undo'],details__order=order.pk).order_by('-pk').first()
        order.undo_association=event.pk if event and event.action=='history_move' and event.plan_id==plan.pk else None
    previous=RoastPlan.all_objects.filter(historical=True,date__lt=plan.date).order_by('-date').first()
    totals={name:sum((getattr(r,name) for r in workbook if getattr(r,name) is not None),Decimal(0)) for name in ['green_oz','roasted_oz']}
    return render(request,'portal/past_plan.html',{'plan':plan,'workbook_rows':workbook,'actual_rows':actual,'orders':orders,'previous':previous,'totals':totals,'events':plan.events.select_related('actor')[:20],'past_dates':RoastPlan.all_objects.filter(historical=True,removed_at__isnull=True).exclude(pk=plan.pk).order_by('-date')[:500]})
