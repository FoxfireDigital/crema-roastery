from decimal import Decimal
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.http import require_POST,require_http_methods
from .models import RoastPlan,PlanEvent,PlannedBatch,ImportOrder,Roaster

ROAST_ORDER={'Light':0,'Light/Medium':1,'Medium':2,'Medium/Dark':3,'Dark':4,'French':5}
ROAST_NAMES={'Light':'City / Light','Light/Medium':'Light / Medium','Medium':'Full City / Medium','Medium/Dark':'Medium / Dark','Dark':'Vienna / Dark','French':'French'}


def mark_revised(plan,actor):
    if plan.accepted_at is not None and plan.removed_at is None and plan.closed_at is None:
        plan.accepted_at=None;plan.accepted_by=None
        plan.save(update_fields=['accepted_at','accepted_by'])
        PlanEvent.objects.create(plan=plan,actor=actor,action='revised')
        return True
    return False


@staff_member_required
@require_POST
def accept_plan(request,pk):
    from .planning import summary
    try:
        with transaction.atomic():
            plan=get_object_or_404(RoastPlan.objects.select_for_update(),pk=pk)
            if request.POST.get('version')!=str(plan.version):raise ValidationError('The plan changed. Refresh and review the latest weights before accepting it.')
            groups=[g for g in plan.groups.all() if g.orders.exists()]
            if not groups:raise ValidationError('Add at least one order before accepting this plan.')
            imported=ImportOrder.objects.filter(imported_plan=plan,imported_at__isnull=False)
            if imported.exclude(source_flags=[]).exists() or imported.filter(source_changed=True).exists() or imported.exclude(financial_status='paid',fulfillment_status='unfulfilled',cancelled=False).exists():raise ValidationError('Review the changed or held source orders before accepting this plan.')
            for group in groups:
                data=summary(group,plan.estimated_loss_pct)
                if data['expected']+Decimal('.05')<data['required_target']:raise ValidationError(f'{group.coffee}: reserve stock or size the drafts to cover '+('the customer’s ordered coffee before accepting.' if data['started_work'] else 'the coffee plus its spillage allowance before accepting.'))
                if not group.coffee.flavor_base_eligible and group.orders.filter(product_coffee__kind='flavored').exists():raise ValidationError('This coffee cannot supply flavored orders. Review the flavor base before accepting this plan.')
                for row in data['rows']:
                    if row.batch_id:continue
                    if not row.roaster.active:raise ValidationError('Choose active roasters for all unstarted drafts.')
                    row.full_clean()
            if not plan.accepted_at:
                plan.accepted_at=timezone.now();plan.accepted_by=request.user;plan.version+=1
                plan.save(update_fields=['accepted_at','accepted_by','version'])
                PlanEvent.objects.create(plan=plan,actor=request.user,action='accepted')
        messages.success(request,'Plan accepted. Its roasts are on the front page by machine capacity, largest first, then light to dark.')
        return redirect('/')
    except ValidationError as error:
        messages.error(request,'; '.join(error.messages));return redirect('/planning/?plan='+str(pk))


@staff_member_required
def plans(request):
    from django.db.models import Count
    from django.core.paginator import Paginator
    deleted=request.GET.get('deleted')=='1'
    historical=request.GET.get('history')=='1' and not deleted
    closed=request.GET.get('closed')=='1' and not deleted and not historical
    rows=RoastPlan.all_objects.filter(removed_at__isnull=not deleted,historical=historical).select_related('accepted_by','removed_by').order_by('-date','-id')
    rows=rows.filter(closed_at__isnull=not closed)
    years=list(rows.dates('date','year',order='DESC')) if historical else []
    year=request.GET.get('year','')
    if historical and year in [str(day.year) for day in years]:rows=rows.filter(date__year=int(year))
    rows=rows.annotate(workbook_count=Count('workbook_roasts',distinct=True),order_count=Count('importorder',distinct=True))
    page=Paginator(rows,50).get_page(request.GET.get('page'))
    return render(request,'portal/plans.html',{'plans':page,'page':page,'deleted':deleted,'historical':historical,'closed':closed,'years':years,'year':year})


@staff_member_required
@require_http_methods(['GET','POST'])
def delete_plan(request,pk,restore=False):
    qs=RoastPlan.all_objects.filter(removed_at__isnull=not restore,historical=False,closed_at__isnull=True)
    plan=get_object_or_404(qs,pk=pk);error='';status=200
    if request.method=='POST':
        from .order_import import remove_import,readiness,add_selected
        from .autobatches import sync_plan
        try:
            with transaction.atomic():
                plan=get_object_or_404(qs.select_for_update(),pk=pk)
                if request.POST.get('version')!=str(plan.version):raise ValidationError('This plan changed. Reopen this page to review its current state before continuing.')
                if restore:
                    plan.removed_at=None;plan.removed_by=None;plan.accepted_at=None;plan.accepted_by=None
                    plan.save(update_fields=['removed_at','removed_by','accepted_at','accepted_by'])
                    eligible=[]
                    for order in ImportOrder.objects.filter(pk__in=plan.released_imports):
                        if readiness(order)[0]:eligible.append(order.pk)
                    if eligible:add_selected(plan,eligible,request.user);plan.refresh_from_db()
                    sync_plan(plan,request.user)
                    messages.success(request,'Plan restored as a draft. Review and accept it to return it to the front page. Orders now assigned elsewhere or held keep their current state.')
                else:
                    plan.removed_at=timezone.now();plan.removed_by=request.user;plan.released_imports=[]
                    plan.save(update_fields=['removed_at','removed_by','released_imports'])
                    for order in ImportOrder.objects.filter(imported_plan=plan,imported_at__isnull=False):
                        # Coffee totals are shared; never release an order when
                        # any of its coffee profiles has already started.
                        from .models import IncomingOrderLine
                        groups=IncomingOrderLine.objects.filter(source__in=['shopify','store'],external_id__startswith=order.external_id+':').values_list('group_id',flat=True)
                        from .models import RoastedStockAllocation
                        if PlannedBatch.objects.filter(group_id__in=groups,batch__isnull=False).exists() or RoastedStockAllocation.objects.filter(line__group_id__in=groups,status='used').exists():continue
                        remove_import(order.pk,request.user);plan.released_imports.append(order.pk)
                    plan.refresh_from_db(fields=['version'])
                    plan.save(update_fields=['released_imports'])
                    from .roasted_stock import release_plan
                    release_plan(plan,request.user)
                    messages.success(request,'Plan deleted. Unstarted orders without recorded production return to review; started batches and history are preserved. Restore the plan under Deleted plans if needed.')
                plan.version+=1;plan.save(update_fields=['version'])
                PlanEvent.objects.create(plan=plan,actor=request.user,action='restored' if restore else 'deleted')
            return redirect('/planning/?plan='+str(pk) if restore else '/plans/')
        except ValidationError as exception:error='; '.join(exception.messages);status=400
    return render(request,'portal/delete_plan.html',{'plan':plan,'restore':restore,'error':error,'has_started':PlannedBatch.all_objects.filter(group__plan=plan,batch__isnull=False).exists()},status=status)


def accepted_boards(include_completed=False):
    from .production import state_token
    rows=PlannedBatch.objects.filter(group__plan__removed_at__isnull=True,group__plan__historical=False,group__plan__closed_at__isnull=True,group__plan__accepted_at__isnull=False).select_related('group__coffee','group__label_variant','group__plan','roaster','batch').order_by('id')
    grouped={}
    for row in rows:
        if not include_completed and row.batch_id and row.batch.sealed_at:continue
        if not row.group.orders.exists():continue
        row.roast_name=ROAST_NAMES.get(row.group.roast_level,row.group.roast_level)
        row.references=list(row.group.orders.values_list('reference',flat=True))
        if row.batch_id:row.batch_revision=state_token(row.batch)
        grouped.setdefault(row.roaster.name,[]).append(row)
    result=[]
    for name,items in sorted(grouped.items(),key=lambda pair:(-next((r.capacity or Decimal(0) for r in Roaster.objects.filter(name=pair[0])),Decimal(0)),pair[0])):
        items.sort(key=lambda row:(ROAST_ORDER.get(row.group.roast_level,99),row.group.plan.date,row.group.coffee.name,row.pk))
        result.append({'roaster':name,'rows':items})
    return result
