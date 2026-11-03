"""The accepted production sheet: fixed recipes, editable results and checkboxes."""
from decimal import Decimal
import hashlib,json
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404,render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import Batch,BatchProgressEvent,PlannedBatch,RoastPlan
from .production import batch_state

STEPS=('measured_at','roasted_at','cooled_at')


def sheet_state(batch):
    return {**batch_state(batch),'measured_at':batch.measured_at.isoformat() if batch.measured_at else None}


def row_token(row):
    data=[row.pk,row.group.plan.version,str(row.green_oz),row.roaster_id,str(row.roaster.minimum),str(row.roaster.capacity),row.batch_id,sheet_state(row.batch) if row.batch_id else None]
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def photo_url(batch):
    if batch and not batch.removed_at and not batch.merged_into_id and (batch.roasted_at or batch.roasted_oz is not None):return '/batches/'+str(batch.pk)+'/photos/'
    return ''

def artisan_upload_url(batch):
    if photo_url(batch):return '/batches/'+str(batch.pk)+'/artisan/upload/'
    return ''


def artisan_logs_url(batch):
    return '/batches/'+str(batch.pk)+'/#artisan-logs' if batch else ''


def row_result(row):
    batch=row.batch if row.batch_id else None
    from .finished_coverage import plan_coverage
    return {'photo_url':photo_url(batch),'artisan_upload_url':artisan_upload_url(batch),'artisan_logs_url':artisan_logs_url(batch),'revision':row_token(row),'weight':str(batch.roasted_oz.quantize(Decimal('.1'))) if batch and batch.roasted_oz is not None else '',
            'steps':{key:bool(batch and getattr(batch,key)) for key in STEPS},'operator':batch.operator.username if batch else '—','undo_event':undo_event(row),'coverage':plan_coverage(row.group.plan)}


def undo_event(row):
    if not row.batch_id:return None
    event=row.batch.progress_events.order_by('-pk').first()
    if event and event.action=='sheet' and not BatchProgressEvent.objects.filter(undoes=event).exists() and event.after==sheet_state(row.batch):return event.pk
    return None


@login_required
def roast_sheet(request):
    from .plan_actions import accepted_boards
    from .views import clock_context
    boards=accepted_boards(include_completed=True)
    from .finished_coverage import plan_coverage
    plans=list(RoastPlan.objects.filter(accepted_at__isnull=False).order_by('date','pk'))
    coverages=[plan_coverage(plan) for plan in plans]
    from .packing import packing_context
    packing_lists=[packing_context(plan) for plan in plans]
    for board in boards:
        for row in board['rows']:
            batch=row.batch if row.batch_id else None
            row.sheet_revision=row_token(row);row.undo_event=undo_event(row);row.sheet_photo_url=photo_url(batch);row.artisan_upload_url=artisan_upload_url(batch);row.artisan_logs_url=artisan_logs_url(batch)
    return render(request,'portal/roast_sheet.html',{'accepted_boards':boards,'coverages':coverages,'packing_lists':packing_lists,'roast_sheet':True,**clock_context(request.user)})


class SheetResultForm(forms.Form):
    roasted_oz=forms.DecimalField(max_digits=9,decimal_places=1,min_value=Decimal('.1'),required=False)
    measured_at=forms.BooleanField(required=False)
    roasted_at=forms.BooleanField(required=False)
    cooled_at=forms.BooleanField(required=False)

    def clean(self):
        data=super().clean()
        for previous,current in zip(STEPS,STEPS[1:]):
            if data.get(current) and not data.get(previous):raise forms.ValidationError('Check the preceding steps first.')
        return data


@login_required
@require_POST
def save_roast_row(request,pk):
    # Lock the plan before its row, matching the planner and batch-detail lock order.
    initial=get_object_or_404(PlannedBatch.objects.select_related('group'),pk=pk)
    try:
        with transaction.atomic():
            plan=get_object_or_404(RoastPlan.objects.select_for_update(),pk=initial.group.plan_id)
            # Only lock the planned row here. Label variants are optional: locking
            # every joined table makes PostgreSQL reject the nullable outer join.
            row=get_object_or_404(PlannedBatch.objects.select_for_update(of=('self',)).select_related('group__coffee','group__label_variant','group__plan','roaster'),pk=pk)
            if not plan.accepted_at:raise ValidationError('This plan is now a draft. Review and accept it on Plans before recording production.')
            if not row.group.orders.exists():raise ValidationError('This roast no longer has active orders. Review its plan.')
            if row.batch_id:row.batch=Batch.objects.select_for_update().get(pk=row.batch_id)
            if row.batch_id and row.batch.merged_into_id:return JsonResponse({'error':'This input was combined into its base-coffee batch. Reload the roast sheet.'},status=409)
            if request.POST.get('revision')!=row_token(row):
                return JsonResponse({'error':'This row changed in another tab or its plan was edited. Reload the page before making this correction.'},status=409)
            form=SheetResultForm(request.POST)
            if not form.is_valid():raise ValidationError([str(error) for errors in form.errors.values() for error in errors])
            data=form.cleaned_data
            previous_weight=row.batch.roasted_oz if row.batch_id else None
            if data['roasted_oz'] is not None and data['roasted_oz']!=previous_weight:
                data['measured_at']=True;data['roasted_at']=True
            if data['roasted_oz'] is not None and data['roasted_oz']>(row.batch.green_oz if row.batch_id else row.green_oz):raise ValidationError('Finished weight cannot exceed the green input. Check the weight and units.')
            if not row.batch_id and not any(data.get(key) for key in STEPS) and data['roasted_oz'] is None:return JsonResponse(row_result(row))
            if not row.batch_id:
                if not row.roaster.active:raise ValidationError('This roaster is inactive. Review the plan first.')
                row.full_clean()
                batch=Batch(date=plan.date,operator=request.user,roaster=row.roaster,coffee=row.group.coffee,label_variant=row.group.label_variant,
                            green_oz=row.green_oz,roast_level=row.group.roast_level,planned_group=row.group)
                before=sheet_state(batch)
            else:batch=row.batch;before=sheet_state(batch)
            now=timezone.now()
            batch.roasted_oz=data['roasted_oz']
            for key in STEPS:setattr(batch,key,(getattr(batch,key) or now) if data[key] else None)
            batch.save()
            if not row.batch_id:row.batch=batch;row.save(update_fields=['batch'])
            after=sheet_state(batch)
            if before!=after:BatchProgressEvent.objects.create(batch=batch,actor=request.user,action='sheet',before=before,after=after)
            # Accepted green weights remain the reviewed schedule. Actual results do
            # not silently resize its remaining rows or create additional drafts.
            return JsonResponse(row_result(row))
    except ValidationError as error:
        return JsonResponse({'error':'; '.join(error.messages)},status=400)


@login_required
@require_POST
def undo_roast_row(request,pk):
    from django.utils.dateparse import parse_datetime
    initial=get_object_or_404(PlannedBatch.objects.select_related('group'),pk=pk)
    try:
        with transaction.atomic():
            plan=get_object_or_404(RoastPlan.objects.select_for_update(),pk=initial.group.plan_id)
            row=get_object_or_404(PlannedBatch.objects.select_for_update(of=('self',)).select_related('group__plan'),pk=pk)
            if not plan.accepted_at:raise ValidationError('Review and accept the latest plan before correcting its roast sheet.')
            if row.batch_id:row.batch=Batch.objects.select_for_update().get(pk=row.batch_id)
            if request.POST.get('revision')!=row_token(row):return JsonResponse({'error':'This roast changed. Reload before undoing.'},status=409)
            event_id=undo_event(row)
            if not event_id or str(event_id)!=request.POST.get('event'):raise ValidationError('The last change can no longer be undone here. Review its batch history.')
            event=BatchProgressEvent.objects.get(pk=event_id)
            if not request.user.is_staff and event.actor_id!=request.user.pk:raise ValidationError('Only the person who made this change or an administrator can undo it.')
            before=sheet_state(row.batch)
            for key,value in event.before.items():setattr(row.batch,key,parse_datetime(value) if value and key.endswith('_at') else Decimal(value) if value is not None else None)
            row.batch.save()
            BatchProgressEvent.objects.create(batch=row.batch,actor=request.user,action='sheet_undo',before=before,after=sheet_state(row.batch),undoes=event)
            return JsonResponse(row_result(row))
    except ValidationError as error:return JsonResponse({'error':'; '.join(error.messages)},status=400)
