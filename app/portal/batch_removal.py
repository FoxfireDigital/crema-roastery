"""Remove mistaken production records without destroying their evidence."""
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404,render,redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import Batch,PlannedBatch,RoastPlan,BatchProgressEvent,PlanEvent
from .production import state_token,batch_state

def retire_batch(batch,actor,reason):
    if batch.removed_at:return False
    if not reason.strip() or len(reason)>300:raise ValidationError('Enter why this record should be excluded, up to 300 characters.')
    if batch.merged_into_id or batch.merge_events.exists():raise ValidationError('This load has combined inputs. Review its merge history before deleting it.')
    before={**batch_state(batch),'green_oz':str(batch.green_oz)}
    batch.removed_at=timezone.now();batch.removed_by=actor;batch.removal_reason=reason.strip()
    batch.save(update_fields=['removed_at','removed_by','removal_reason'])
    PlannedBatch.all_objects.filter(batch=batch,removed_at__isnull=True).update(removed_at=batch.removed_at)
    BatchProgressEvent.objects.create(batch=batch,actor=actor,action='deleted',before=before,after={'removed_at':batch.removed_at.isoformat(),'reason':reason})
    if batch.planned_group_id:
        group=batch.planned_group;group.auto_batches=False;group.save(update_fields=['auto_batches'])
        PlanEvent.objects.create(plan=group.plan,actor=actor,action='batch_deleted',details={'batch':batch.pk,'group':group.pk,'reason':reason,'before':before})
    return True

@staff_member_required
@require_http_methods(['GET','POST'])
def delete_batch(request,pk):
    batch=get_object_or_404(Batch.all_objects.select_related('coffee','planned_group__plan','roaster'),pk=pk)
    if batch.removed_at:return redirect('/history/?deleted=1')
    error='';status=200;plan=batch.planned_group.plan if batch.planned_group_id else None
    if request.method=='POST':
        try:
            with transaction.atomic():
                if plan:plan=RoastPlan.all_objects.select_for_update().get(pk=plan.pk)
                batch=Batch.all_objects.select_for_update().get(pk=pk)
                if batch.removed_at:return redirect('/history/?deleted=1')
                if plan and plan.closed_at:raise ValidationError('Reopen the completed plan before deleting one of its batch records.')
                if request.POST.get('revision')!=state_token(batch) or plan and request.POST.get('plan_version')!=str(plan.version):raise ValidationError('This batch or plan changed. Reload before deleting.')
                if request.POST.get('confirmed')!='on':raise ValidationError('Confirm that this is an incorrect or duplicate record.')
                retire_batch(batch,request.user,request.POST.get('reason',''))
                if plan:
                    from .plan_actions import mark_revised
                    mark_revised(plan,request.user);plan.version+=1;plan.save(update_fields=['version'])
            messages.success(request,'Batch excluded from production totals. Its original values and deletion reason remain in Deleted batches. Review any customer shortage; no replacement batch was added.')
            return redirect('/planning/?plan='+str(plan.pk) if plan else '/history/?deleted=1')
        except ValidationError as exc:error='; '.join(exc.messages);status=400
    return render(request,'portal/delete_batch.html',{'batch':batch,'plan':plan,'revision':state_token(batch),'error':error},status=status)
