"""Effective-dated straight-time estimates; payment records remain explicit."""
import csv,hashlib,json,uuid
from datetime import datetime,time,timedelta,timezone as dt_timezone
from decimal import Decimal,ROUND_HALF_UP
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import HourlyRate,PayrollAccess,Shift

CENT=Decimal('.01')
def money(value):return value.quantize(CENT,rounding=ROUND_HALF_UP)
def manager(user):return user.is_staff and PayrollAccess.objects.filter(user=user,manages_rates=True).exists()
def payroll_context(request):return {'payroll_manager':manager(request.user) if request.user.is_authenticated else False}

def work_rows(user,start=None,end=None):
    from .views import seconds_worked
    now=timezone.now();end=min(end,now) if end else now
    rates=list(HourlyRate.objects.filter(user=user).order_by('effective_on','id'))
    shifts=Shift.objects.filter(user=user,removed_at__isnull=True,started_at__lt=end).prefetch_related('breaks').order_by('started_at','id')
    out=[]
    for shift in shifts:
        lo=max(shift.started_at,start) if start else shift.started_at
        hi=min(shift.ended_at or now,end)
        if hi<=lo:continue
        cursor=lo;pieces=[]
        while cursor<hi:
            day=timezone.localdate(cursor);edge=timezone.make_aware(datetime.combine(day+timedelta(days=1),time.min));stop=min(hi,edge)
            seconds=seconds_worked(shift,start=cursor.astimezone(dt_timezone.utc),end=stop.astimezone(dt_timezone.utc))
            eligible=[r for r in rates if r.effective_on<=day];rate=eligible[-1] if eligible else None
            if seconds:pieces.append({'shift':shift.pk,'date':day,'start':timezone.localtime(cursor),'end':timezone.localtime(stop),'seconds':seconds,'hours':Decimal(seconds)/3600,'rate':rate.amount if rate else None,'rate_id':rate.pk if rate else None,'open':shift.ended_at is None})
            cursor=stop
        # Preserve the existing clock's whole-second total across midnight.
        total=seconds_worked(shift,start=lo.astimezone(dt_timezone.utc),end=hi.astimezone(dt_timezone.utc))
        if pieces:pieces[-1]['seconds']+=total-sum(p['seconds'] for p in pieces)
        for p in pieces:
            p['hours']=Decimal(p['seconds'])/3600;p['gross']=money(p['hours']*p['rate']) if p['rate'] is not None else None
        out+=pieces
    return out

def estimate(user,cutoff=None,paid_seconds=None):
    from .payments import hours_balance
    rows=work_rows(user,end=cutoff);skip=hours_balance(user)['paid_seconds'] if paid_seconds is None else paid_seconds
    pieces=[];unrated=0;total=Decimal(0);seconds=0
    for row in rows:
        take=min(skip,row['seconds']);skip-=take;remaining=row['seconds']-take
        if not remaining:continue
        seconds+=remaining
        gross=money(Decimal(remaining)/3600*row['rate']) if row['rate'] is not None else None
        if gross is None:unrated+=remaining
        else:total+=gross
        pieces.append({'shift':row['shift'],'date':str(row['date']),'seconds':remaining,'rate':str(row['rate']) if row['rate'] is not None else None,'rate_id':row['rate_id'],'gross':str(gross) if gross is not None else None})
    return {'gross':None if unrated else total,'rated_gross':total,'unrated_hours':Decimal(unrated)/3600,'seconds':seconds,'hours':Decimal(seconds)/3600,'calculation':{'method':'Chronological net hours after existing paid-hour credits; effective daily rates; straight-time estimate before deductions.','segments':pieces}}

class RateForm(forms.Form):
    employee=forms.ModelChoiceField(queryset=get_user_model().objects.filter(is_active=True),label='Employee')
    effective_on=forms.DateField(widget=forms.DateInput(attrs={'type':'date'}),label='Effective date')
    amount=forms.DecimalField(max_digits=8,decimal_places=2,min_value=Decimal('.01'),max_value=10000,label='Hourly rate (USD)')
    reason=forms.CharField(max_length=300,label='Reason / note')
    request_key=forms.UUIDField(widget=forms.HiddenInput)

def selected(request):
    if not manager(request.user):
        if request.GET.get('employee') and request.GET['employee']!=str(request.user.pk):raise PermissionDenied
        return request.user
    wanted=request.GET.get('employee')
    if wanted and not wanted.isdigit():raise PermissionDenied
    default=request.user
    return get_object_or_404(get_user_model(),pk=wanted,is_active=True) if wanted else default

@login_required
@require_http_methods(['GET','POST'])
def payroll_page(request):
    employee=selected(request);can_manage=manager(request.user);status=200
    form=RateForm(request.POST if request.method=='POST' else None,initial={'employee':employee.pk,'effective_on':timezone.localdate(),'request_key':uuid.uuid4()})
    if request.method=='POST':
        if not can_manage:raise PermissionDenied
        if form.is_valid():
            data=form.cleaned_data;fingerprint=hashlib.sha256(json.dumps({k:str(v.pk if hasattr(v,'pk') else v) for k,v in data.items() if k!='request_key'},sort_keys=True).encode()).hexdigest()
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=data['employee'].pk)
                prior=HourlyRate.objects.filter(request_key=data['request_key']).first()
                if prior and prior.request_hash!=fingerprint:form.add_error(None,'This saved form has different values. Reload before changing a rate.')
                else:
                    if not prior:HourlyRate.objects.create(user=data['employee'],effective_on=data['effective_on'],amount=data['amount'],reason=data['reason'],request_key=data['request_key'],request_hash=fingerprint,created_by=request.user)
                    messages.success(request,'Hourly rate saved with its effective date. Earlier rate revisions and payment calculations are retained.')
                    return redirect('/payroll/?employee='+str(data['employee'].pk))
        status=400
    from .payments import hours_balance
    rows=work_rows(employee);due=estimate(employee)
    current=HourlyRate.objects.filter(user=employee,effective_on__lte=timezone.localdate()).first()
    employees=[{'person':u,'due':estimate(u)} for u in get_user_model().objects.filter(is_active=True).exclude(username='admin')] if can_manage else []
    return render(request,'portal/payroll.html',{'employee':employee,'can_manage':can_manage,'employees':employees,'form':form,'due':due,'current_rate':current,'rates':HourlyRate.objects.filter(user=employee).select_related('created_by')[:50],'rows':rows[-200:],'balance':hours_balance(employee),'today':timezone.localdate(),'clock_timezone':timezone.get_current_timezone_name()},status=status)

@login_required
@require_http_methods(['GET'])
def export_payroll(request):
    employee=selected(request)
    from django.utils.dateparse import parse_date
    try:
        start=parse_date(request.GET.get('start','')) if request.GET.get('start') else None
        end=parse_date(request.GET.get('end','')) if request.GET.get('end') else None
        if end and end.year==9999:raise ValueError()
    except ValueError:return HttpResponse('Choose a valid date range.',status=400)
    if request.GET.get('start') and start is None or request.GET.get('end') and end is None or start and end and start>end:return HttpResponse('Choose a valid date range.',status=400)
    lo=timezone.make_aware(datetime.combine(start,time.min)) if start else None
    hi=timezone.make_aware(datetime.combine(end+timedelta(days=1),time.min)) if end else None
    rows=work_rows(employee,lo,hi)
    response=HttpResponse(content_type='text/csv; charset=utf-8');response['Content-Disposition']='attachment; filename="coffee-timeclock-'+str(employee.pk)+'.csv"';response.write('\ufeff')
    writer=csv.writer(response)
    zone=timezone.get_current_timezone_name()
    writer.writerow(['Employee',f'Work date ({zone})',f'Clock segment start ({zone})',f'Clock segment end ({zone})','Net seconds (breaks excluded)','Net hours','Hourly rate USD','Gross estimate USD','Status'])
    from .recovery import csv_cell
    for row in rows:writer.writerow([csv_cell(employee.username),row['date'],row['start'].isoformat(),row['end'].isoformat(),row['seconds'],f"{row['hours']:.4f}",row['rate'] if row['rate'] is not None else 'Rate needed',row['gross'] if row['gross'] is not None else '', 'Open — estimate' if row['open'] else 'Closed'])
    writer.writerow(['TOTAL','','','','',f"{sum((r['hours'] for r in rows),Decimal(0)):.4f}",'',sum((r['gross'] for r in rows),Decimal(0)) if all(r['gross'] is not None for r in rows) else 'Incomplete — rate needed','Straight-time estimate before deductions'])
    return response
