"""Explicit per-load corrections; automatic planning keeps configured limits."""
from decimal import Decimal,InvalidOperation
import json,hashlib
from django import forms
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404,render,redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import RoastPlan,PlannedBatch,Batch,PlanEvent


def authorized_weight(load):
    value=load.green_override
    if not isinstance(value,dict):return False
    try:
        return (value.get('roaster')==load.roaster_id and Decimal(value['weight'])==load.green_oz
                and isinstance(value.get('actor'),int) and value['actor']>0
                and bool(value.get('reason','').strip()) and value.get('confirmed') is True)
    except (InvalidOperation,ValueError,TypeError,KeyError,AttributeError):return False


def override_stamp(row):
    from .production import state_token
    payload=[row.pk,row.group.plan.version,row.roaster_id,str(row.green_oz),row.green_override,
             state_token(row.batch) if row.batch_id else None,str(row.roaster.minimum),str(row.roaster.capacity)]
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


class OverrideForm(forms.Form):
    revision=forms.CharField(widget=forms.HiddenInput)
    green_oz=forms.DecimalField(max_digits=8,decimal_places=1,min_value=Decimal('.1'),label='Actual / intended green input (oz)',widget=forms.NumberInput(attrs={'step':'.1'}))
    reason=forms.CharField(min_length=3,max_length=300,label='Reason for this correction',widget=forms.Textarea(attrs={'rows':2}))
    confirmed=forms.BooleanField(label='I checked this load and machine. Apply this weight even if it is outside the configured range.')


@staff_member_required
@require_http_methods(['GET','POST'])
def override_load(request,pk):
    row=get_object_or_404(PlannedBatch.objects.select_related('group__plan','group__coffee','roaster','batch'),pk=pk)
    error='';status=200
    form=OverrideForm(request.POST or None,initial={'revision':override_stamp(row),'green_oz':row.batch.green_oz if row.batch_id else row.green_oz})
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                plan=get_object_or_404(RoastPlan.all_objects.select_for_update(),pk=row.group.plan_id)
                row=get_object_or_404(PlannedBatch.objects.select_for_update(of=('self',)).select_related('group__plan','group__coffee','roaster','batch'),pk=pk)
                if plan.closed_at or plan.removed_at or plan.historical:raise ValidationError('Reopen an active plan before changing a load. Historical plans cannot be resized here.')
                if row.batch_id:row.batch=Batch.objects.select_for_update().get(pk=row.batch_id)
                if request.POST.get('revision')!=override_stamp(row):raise ValidationError('This load or plan changed. Reload and review before applying the override.')
                if not row.roaster.active:raise ValidationError('This machine is inactive.')
                if not row.group.orders.exists():raise ValidationError('This load has no active demand.')
                weight=form.cleaned_data['green_oz']
                if row.batch_id and (row.batch.removed_at or row.batch.merged_into_id):raise ValidationError('An excluded or merged input cannot be resized.')
                if row.batch_id and row.batch.roasted_oz is not None and weight<row.batch.roasted_oz:raise ValidationError('Green input cannot be less than the already recorded finished weight.')
                before={'draft_green':str(row.green_oz),'actual_green':str(row.batch.green_oz) if row.batch_id else None,'authorization':row.green_override,'batch':row.batch_id}
                authorization={'weight':str(weight),'roaster':row.roaster_id,'actor':request.user.pk,'reason':form.cleaned_data['reason'],'confirmed':True,'at':timezone.now().isoformat()}
                row.green_oz=weight;row.green_override=authorization
                # Batch.save reconciles existing measured green deductions using the saved recipe.
                if row.batch_id:
                    row.batch.green_oz=weight;row.batch.green_override=authorization
                    row.batch.save(update_fields=['green_oz','green_override'])
                row.save(update_fields=['green_oz','green_override'])
                row.group.auto_batches=False;row.group.save(update_fields=['auto_batches'])
                plan.version+=1;plan.save(update_fields=['version'])
                PlanEvent.objects.create(plan=plan,actor=request.user,action='load_override',details={'row':row.pk,'before':before,'after':authorization,'accepted_preserved':bool(plan.accepted_at),'results_and_packing_preserved':True})
            return redirect('/planning/?plan='+str(plan.pk)+'#production')
        except ValidationError as exc:error='; '.join(exc.messages);status=409
    elif request.method=='POST':status=400
    return render(request,'portal/load_override.html',{'row':row,'form':form,'error':error},status=status)
