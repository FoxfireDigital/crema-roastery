"""Measured production steps, recoverable changes, and opt-in yield estimates."""
from decimal import Decimal
import hashlib,json
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import Batch,BatchProgressEvent,HistoricalRoast,Coffee,RoastPlan

FIELDS=['roasted_oz','actual_finish_temp_f','measured_at','roasted_at','cooled_at','bagged_at','sealed_at']

def batch_state(batch):
    result={}
    for key in FIELDS:
        value=getattr(batch,key)
        result[key]=value.isoformat() if value is not None and key.endswith('_at') else str(value.quantize(Decimal('.1') if key=='actual_finish_temp_f' else Decimal('.01'))) if value is not None else None
    return result
def state_token(batch):return hashlib.sha256(json.dumps([batch_state(batch),str(batch.green_oz),batch.coffee_id,batch.roast_level,batch.merged_into_id],sort_keys=True).encode()).hexdigest()


class RoastResultForm(forms.Form):
    roasted_oz=forms.DecimalField(max_digits=9,decimal_places=1,min_value=Decimal('.1'),label='Actual roasted weight (oz)')
    actual_finish_temp_f=forms.DecimalField(max_digits=5,decimal_places=1,min_value=Decimal('.1'),required=False,label='Actual finish temperature (°F)')
    def __init__(self,*args,batch,**kwargs):
        super().__init__(*args,**kwargs);self.batch=batch
        self.fields['roasted_oz'].widget.attrs.update({'step':'.1','max':str(batch.green_oz)})
        custom=(batch.order_id and batch.order.target_finish_temp_f is not None) or (batch.planned_group_id and batch.planned_group.target_finish_temp_f is not None)
        self.fields['actual_finish_temp_f'].required=bool(custom)
    def clean_roasted_oz(self):
        value=self.cleaned_data['roasted_oz']
        if value>self.batch.green_oz:raise forms.ValidationError('Roasted weight cannot exceed the measured green input. Check the weight and units.')
        return value


@login_required
def batch_detail(request,pk):
    batch=get_object_or_404(Batch.all_objects.select_related('coffee','roaster','operator','planned_group','order','label_variant'),pk=pk)
    if batch.removed_at:return render(request,'portal/deleted_batch.html',{'batch':batch})
    if batch.merged_into_id:
        messages.info(request,'This measured input was combined into the linked base-coffee batch. Its original record is preserved.')
        return redirect('batch_detail',pk=batch.merged_into_id)
    closed_plan=batch.planned_group.plan if batch.planned_group_id else None
    if request.method=='POST' and closed_plan and closed_plan.closed_at:
        messages.error(request,'This plan is closed. Reopen it before correcting production records.')
        return redirect('/plans/'+str(closed_plan.pk)+'/completed/')
    status=200;form=RoastResultForm(batch=batch)
    if request.method=='POST':
        with transaction.atomic():
            plan=RoastPlan.all_objects.select_for_update().get(pk=batch.planned_group.plan_id) if batch.planned_group_id else None
            batch=Batch.objects.select_for_update().get(pk=pk)
            if plan and plan.closed_at:
                messages.error(request,'This plan was closed. Reopen it before correcting records.')
                return redirect('/plans/'+str(plan.pk)+'/completed/')
            if batch.merged_into_id:return redirect('batch_detail',pk=batch.merged_into_id)
            before=batch_state(batch);action=request.POST.get('action')
            if request.POST.get('revision')!=state_token(batch):
                messages.error(request,'This batch changed in another tab. Check its current step before saving.');status=400
            elif action=='undo' and request.user.is_staff:
                event=batch.progress_events.exclude(action='undo').filter(reversal__isnull=True).first()
                if not event or event.after!={key:before.get(key) for key in event.after}:
                    messages.error(request,'There is no matching step to undo. Earlier production history has been preserved.');status=400
                else:
                    for key,value in event.before.items():setattr(batch,key,parse_datetime(value) if key.endswith('_at') and value else Decimal(value) if value is not None else None)
                    batch.save(update_fields=FIELDS)
                    BatchProgressEvent.objects.create(batch=batch,actor=request.user,action='undo',before=before,after=batch_state(batch),undoes=event)
                    messages.success(request,'Last production step undone. Previous values remain in the change history.')
            elif action=='roast' and batch.measured_at and (not batch.roasted_at or batch.roasted_oz is None):
                form=RoastResultForm(request.POST,batch=batch)
                if form.is_valid():
                    batch.roasted_oz=form.cleaned_data['roasted_oz'];batch.actual_finish_temp_f=form.cleaned_data['actual_finish_temp_f'];batch.roasted_at=timezone.now()
                    batch.save(update_fields=FIELDS)
                    BatchProgressEvent.objects.create(batch=batch,actor=request.user,action=action,before=before,after=batch_state(batch))
                else:status=400
            elif action in ['bag','seal'] and ((action=='bag' and batch.roasted_at and not batch.bagged_at) or (action=='seal' and batch.bagged_at and not batch.sealed_at)):
                setattr(batch,'bagged_at' if action=='bag' else 'sealed_at',timezone.now());batch.save(update_fields=FIELDS)
                BatchProgressEvent.objects.create(batch=batch,actor=request.user,action=action,before=before,after=batch_state(batch))
            else:messages.error(request,'Complete the preceding step first.');status=400
            if status==200 and plan and not plan.accepted_at:
                from .autobatches import sync_plan
                if sync_plan(plan):plan.version+=1;plan.save(update_fields=['version'])
        if status==200:
            if request.POST.get('back')=='workspace':return redirect('/planning/'+('?plan='+str(batch.planned_group.plan_id) if batch.planned_group_id and plan.removed_at is None else '')+'#production')
            return redirect('batch_detail',pk=pk)
    can_undo=request.user.is_staff and batch.progress_events.exclude(action='undo').filter(reversal__isnull=True).exists()
    from .finished_coverage import plan_coverage,NUMBERS
    coverage=None
    if batch.planned_group_id:
        coverage=plan_coverage(batch.planned_group.plan)
        coverage['rows']=[item for item in coverage['rows'] if item['group_id']==batch.planned_group_id]
        coverage['totals']={key:sum((item[key] for item in coverage['rows']),Decimal(0)) for key in NUMBERS}
    from .batch_photos import photo_context
    from .artisan_uploads import batch_log_context
    return render(request,'portal/batch.html',{**(photo_context(batch) if request.user.is_staff else {}),**(batch_log_context(batch,request.GET.get('logs_page')) if request.user.is_staff else {}),'batch':batch,'coverage':coverage,'result_form':form,'revision':state_token(batch),'closed_plan':closed_plan if closed_plan and closed_plan.closed_at else None,'can_undo':can_undo and not (closed_plan and closed_plan.closed_at),'events':batch.progress_events.select_related('actor')[:15],'merge_events':batch.merge_events.select_related('source','actor')},status=status)


def yield_suggestion(group,roaster=None,green_oz=None,current_loss=None):
    from .yield_learning import suggestion
    return suggestion(group,roaster,green_oz,current_loss)


@login_required
def historical_roasts(request):
    if request.method=='POST' and request.user.is_staff:
        name=request.POST.get('original_name','');coffee=get_object_or_404(Coffee,pk=request.POST.get('coffee'))
        count=HistoricalRoast.objects.filter(coffee_name=name).update(coffee=coffee)
        messages.success(request,f'Matched {count} historical records to {coffee.name}. Original workbook names are retained.')
        return redirect('/history/roasting-sheet/')
    rows=HistoricalRoast.objects.select_related('coffee').all();q=request.GET.get('q','').strip()[:100]
    if q:rows=rows.filter(Q(coffee_name__icontains=q)|Q(operator_name__icontains=q)|Q(sheet__icontains=q))
    if request.GET.get('review')=='1':rows=rows.filter(coffee__isnull=True)|rows.exclude(flags=[])
    from django.core.paginator import Paginator
    page=Paginator(rows,75).get_page(request.GET.get('page'))
    return render(request,'portal/historical_roasts.html',{'page':page,'q':q,'review':request.GET.get('review')=='1','total':HistoricalRoast.objects.count(),'unmatched':HistoricalRoast.objects.filter(coffee__isnull=True).order_by('coffee_name').values_list('coffee_name',flat=True).distinct(),'coffees':Coffee.objects.all()})
