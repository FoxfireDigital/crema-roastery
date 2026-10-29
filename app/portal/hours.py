"""Self-service corrections share the time-clock employee lock and calculations."""
import hashlib,json
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.forms import inlineformset_factory
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import Shift,WorkBreak,TimeAdjustment,TimeEvent


def snapshot(shift):
    def stamp(value):return value.isoformat() if value else None
    return {'started_at':stamp(shift.started_at),'ended_at':stamp(shift.ended_at),'removed_at':stamp(shift.removed_at),
            'breaks':[{'id':b.pk,'started_at':stamp(b.started_at),'ended_at':stamp(b.ended_at)} for b in shift.breaks.order_by('started_at','pk')]}


def revision(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def date_widget():
    return forms.DateTimeInput(format='%Y-%m-%dT%H:%M:%S',attrs={'type':'datetime-local','step':'1'})


def overlaps(shift,start,end):
    others=Shift.objects.filter(user_id=shift.user_id,removed_at__isnull=True).exclude(pk=shift.pk)
    if end:others=others.filter(started_at__lt=end)
    return others.filter(Q(ended_at__isnull=True)|Q(ended_at__gt=start)).exists()


@transaction.atomic
def transfer_hours(source,target,actor):
    """Reassign ownership without changing times, breaks or the original actors."""
    from django.core.exceptions import ValidationError
    from .models import HoursPayment
    if not actor.is_staff or source.pk==target.pk:raise ValidationError('Choose two different employees and an administrator.')
    list(get_user_model().objects.select_for_update().filter(pk__in=[source.pk,target.pk]).order_by('pk'))
    shifts=list(Shift.objects.select_for_update().filter(user=source).order_by('pk'))
    if not shifts:return []
    if HoursPayment.objects.filter(payee=source,voided_at__isnull=True).exists():
        raise ValidationError('Reconcile the source employee’s recorded payments before transferring hours.')
    for shift in shifts:
        if shift.removed_at:continue
        others=Shift.objects.filter(user=target,removed_at__isnull=True)
        if shift.ended_at:others=others.filter(started_at__lt=shift.ended_at)
        if others.filter(Q(ended_at__isnull=True)|Q(ended_at__gt=shift.started_at)).exists():
            raise ValidationError('The transferred hours would overlap the recipient’s existing hours.')
    for shift in shifts:
        before={**snapshot(shift),'user_id':source.pk,'username':source.username}
        Shift.objects.filter(pk=shift.pk).update(user=target)
        after={**snapshot(shift),'user_id':target.pk,'username':target.username}
        TimeAdjustment.objects.create(shift=shift,actor=actor,before=before,after=after,note=f'Hours reassigned from {source.username} to {target.username}. Times, breaks and deletion status preserved.')
        TimeEvent.objects.create(shift=shift,user=actor,action='ownership_transfer')
    return [shift.pk for shift in shifts]


class ShiftForm(forms.ModelForm):
    note=forms.CharField(max_length=300,required=False,label='Note (optional)',widget=forms.TextInput(attrs={'placeholder':'For example: forgot to clock out'}))
    class Meta:
        model=Shift
        fields=['started_at','ended_at']
        labels={'started_at':'Clock in','ended_at':'Clock out'}
        widgets={'started_at':date_widget(),'ended_at':date_widget()}
        help_texts={'ended_at':'Leave blank only if you are still working.'}
    def clean(self):
        data=super().clean();start=data.get('started_at');end=data.get('ended_at');now=timezone.now()
        if start and start>now:self.add_error('started_at','Clock-in cannot be in the future.')
        if end and end>now:self.add_error('ended_at','Clock-out cannot be in the future.')
        if start and end and end<=start:self.add_error('ended_at','Clock-out must be after clock-in.')
        if start and not self.errors:
            if overlaps(self.instance,start,end):raise forms.ValidationError('These hours overlap another shift. Correct that entry first.')
        return data


class BreakForm(forms.ModelForm):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if not self.instance.pk:
            # Model defaults are useful for the live clock, but an unused extra
            # row in the correction form must stay completely empty.
            self.initial['started_at']=None
            self.fields['started_at'].initial=None
    class Meta:
        model=WorkBreak
        fields=['started_at','ended_at']
        labels={'started_at':'Break start','ended_at':'Break end'}
        widgets={'started_at':date_widget(),'ended_at':date_widget()}


BreakForms=inlineformset_factory(Shift,WorkBreak,form=BreakForm,extra=1,can_delete=True,max_num=100,validate_max=True,absolute_max=120)


def validate_breaks(form,breaks):
    start=form.cleaned_data['started_at'];end=form.cleaned_data.get('ended_at');now=timezone.now()
    intervals=[]
    for item in breaks.forms:
        data=item.cleaned_data
        if not data or data.get('DELETE'):continue
        lo=data.get('started_at');hi=data.get('ended_at')
        # Closing a forgotten shift also closes a break that was left running.
        if lo and hi is None and end is not None:
            hi=end;data['ended_at']=end;item.instance.ended_at=end
            if 'ended_at' not in item.changed_data:item.changed_data.append('ended_at')
        if lo is None:continue
        if lo<start or lo>now or (end and lo>=end):item.add_error('started_at','The break must start within this shift.')
        if hi is not None and (hi<=lo or hi>now or (end and hi>end)):item.add_error('ended_at','The break must end after it starts and within this shift.')
        intervals.append((lo,hi or now,item))
    intervals.sort(key=lambda x:x[0])
    for previous,current in zip(intervals,intervals[1:]):
        if current[0]<previous[1]:current[2].add_error('started_at','Breaks cannot overlap.')
    return not any(item.errors for item in breaks.forms)


@login_required
def edit_hours(request,pk=None):
    qs=Shift.objects.filter(removed_at__isnull=True)
    if not request.user.is_staff:qs=qs.filter(user=request.user)
    shift=get_object_or_404(qs,pk=pk) if pk else Shift(user=request.user)
    status=200
    with transaction.atomic():
        if request.method=='POST':
            # Clock in/out uses this same lock, including when no shift exists yet.
            get_user_model().objects.select_for_update().get(pk=shift.user_id)
            if pk:shift=get_object_or_404(qs.select_for_update(),pk=pk)
        before=snapshot(shift) if pk else {}
        token=revision(before)
        form=ShiftForm(request.POST if request.method=='POST' else None,instance=shift)
        breaks=BreakForms(request.POST if request.method=='POST' else None,instance=shift,prefix='breaks')
        if request.method=='POST':
            form_ok=form.is_valid();breaks_ok=breaks.is_valid()
            stale=pk and request.POST.get('revision')!=token
            if pk and {item.instance.pk for item in breaks.initial_forms}!={row['id'] for row in before['breaks']}:
                stale=True
            if stale:form.add_error(None,'This entry changed while you were editing. Reopen it before saving your correction.')
            if form_ok and breaks_ok and not stale and validate_breaks(form,breaks):
                updated=form.save();breaks.instance=updated;breaks.save()
                after=snapshot(updated)
                if before!=after:
                    TimeAdjustment.objects.create(shift=updated,actor=request.user,before=before,after=after,note=form.cleaned_data['note'])
                    TimeEvent.objects.create(shift=updated,user=request.user,action='manual_edit' if pk else 'manual_add')
                messages.success(request,'Hours saved. Your totals and exports now use the corrected times.')
                return redirect('timesheets')
            status=400
        # Keep the original revision on a failed POST; do not bless a stale form.
        token=request.POST.get('revision','') if request.method=='POST' and pk else token
        history=shift.adjustments.select_related('actor')[:20] if pk else []
        return render(request,'portal/edit_hours.html',{'form':form,'breaks':breaks,'shift':shift,'editing':bool(pk),'revision':token,'corrections':history},status=status)


@login_required
@require_http_methods(['GET','POST'])
def remove_hours(request,pk,restore=False):
    qs=Shift.objects.filter(removed_at__isnull=not restore)
    if not request.user.is_staff:qs=qs.filter(user=request.user)
    shift=get_object_or_404(qs,pk=pk);error='';status=200
    with transaction.atomic():
        if request.method=='POST':
            get_user_model().objects.select_for_update().get(pk=shift.user_id)
            shift=get_object_or_404(qs.select_for_update(),pk=pk)
        before=snapshot(shift);token=revision(before)
        if request.method=='POST':
            if request.POST.get('revision')!=token:
                error='This entry changed. Reopen it to check the current times before continuing.'
            elif restore and overlaps(shift,shift.started_at,shift.ended_at):
                error='This entry overlaps another shift. Correct that entry before restoring these hours.'
            else:
                shift.removed_at=None if restore else timezone.now();shift.save(update_fields=['removed_at'])
                TimeAdjustment.objects.create(shift=shift,actor=request.user,before=before,after=snapshot(shift))
                TimeEvent.objects.create(shift=shift,user=request.user,action='manual_restore' if restore else 'manual_delete')
                messages.success(request,'Time entry restored. Totals and exports have updated.' if restore else 'Time entry deleted from your hours and exports. You can restore it under Deleted entries.')
                return redirect('timesheets')
            status=400
        token=request.POST.get('revision','') if request.method=='POST' else token
        return render(request,'portal/remove_hours.html',{'shift':shift,'restore':restore,'revision':token,'error':error},status=status)
