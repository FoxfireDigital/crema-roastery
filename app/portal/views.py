import csv
from datetime import datetime,time,timedelta
from decimal import Decimal,InvalidOperation
from django import forms
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction,IntegrityError
from django.http import HttpResponse,HttpResponseBadRequest
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import Batch,Coffee,LabelVariant,Roaster,CustomOrder,Shift,WorkBreak,TimeEvent

class CatalogFormMixin:
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        coffees=Coffee.objects.filter(active=True)
        labels=LabelVariant.objects.filter(active=True,coffee__active=True)
        self.fields['coffee'].queryset=coffees
        self.fields['label_variant'].queryset=labels
        self.fields['coffee'].widget.attrs['data-coffee-policies']=__import__('json').dumps({str(c.pk):{'locked':c.roast_locked,'roast':c.standard_roast,'experimental':c.experimental} for c in coffees})
        self.fields['label_variant'].widget.attrs['data-coffee-labels']=__import__('json').dumps({str(l.pk):l.coffee_id for l in labels})
        self.fields['roast_level'].help_text='Flavored coffees are Medium. Blends retain their standard roast, including 5 lb bags.'
        if 'target_finish_temp_f' in self.fields:
            self.fields['target_finish_temp_f'].help_text='Optional, for single-origin orders of 5 lb or more only. Smaller orders use the standard roast.'

class BatchForm(CatalogFormMixin,forms.ModelForm):
    green_oz=forms.DecimalField(max_digits=9,decimal_places=1,min_value=Decimal('.1'),label='Green input (oz)',widget=forms.NumberInput(attrs={'step':'.1'}))
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['coffee'].queryset=self.fields['coffee'].queryset.filter(roast_base__isnull=True)
        from .models import GreenBeanItem
        self.fields['green_item'].queryset=GreenBeanItem.objects.filter(active=True)
        self.fields['experimental_origin'].label='Experimental origin / lot'
        self.fields['roast_level'].help_text='Experimental batches may use any roast at any weight. Normal coffees keep their existing rules.'
    class Meta:
        model=Batch
        fields=['date','coffee','experimental_origin','label_variant','roaster','green_item','green_oz','roast_level','note']
        widgets={'date':forms.DateInput(attrs={'type':'date'}),'note':forms.Textarea(attrs={'rows':2})}
    def clean_green_oz(self):
        weight=self.cleaned_data['green_oz']
        if weight<=0: raise forms.ValidationError('Weight must be positive.')
        return weight

class CustomOrderForm(CatalogFormMixin,forms.ModelForm):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['coffee'].queryset=self.fields['coffee'].queryset.filter(experimental=False)
    class Meta:
        model=CustomOrder
        fields=['customer_name','order_reference','coffee','label_variant','roast_level','target_finish_temp_f','bags_5lb','estimated_loss_pct','due_date','notes']
        widgets={'due_date':forms.DateInput(attrs={'type':'date'}),'notes':forms.Textarea(attrs={'rows':3})}
    def clean_bags_5lb(self):
        n=self.cleaned_data['bags_5lb']
        if n < 1 or n > 100: raise forms.ValidationError('Choose 1 to 100 five-pound bags.')
        return n
    def clean_estimated_loss_pct(self):
        n=self.cleaned_data['estimated_loss_pct']
        if n < 0 or n >= 50: raise forms.ValidationError('Enter a loss estimate from 0 to less than 50%.')
        return n
    def clean_target_finish_temp_f(self):
        n=self.cleaned_data['target_finish_temp_f']
        if n is not None and n <= 0: raise forms.ValidationError('Provide a positive temperature in degrees F.')
        return n

def seconds_worked(shift,start=None,end=None):
    if shift.removed_at is not None:return 0
    finish=shift.ended_at or timezone.now()
    lo=max(shift.started_at,start) if start else shift.started_at
    hi=min(finish,end) if end else finish
    total=max(0,(hi-lo).total_seconds())
    for b in shift.breaks.all():
        b_lo=max(b.started_at,lo)
        b_hi=min(b.ended_at or timezone.now(),hi)
        total-=max(0,(b_hi-b_lo).total_seconds())
    return max(0,int(total))

def week_bounds():
    monday=timezone.localdate()-timedelta(days=timezone.localdate().weekday())
    beginning=timezone.make_aware(datetime.combine(monday,time.min))
    ending=beginning+timedelta(days=7)
    return beginning,ending

def healthz(request):
    from django.db import connection
    try:
        with connection.cursor() as cur: cur.execute('SELECT 1')
        return HttpResponse('ok',content_type='text/plain')
    except Exception:
        return HttpResponse('database not ready',status=503,content_type='text/plain')

def clock_context(user):
    current=Shift.objects.filter(user=user,ended_at__isnull=True,removed_at__isnull=True).prefetch_related('breaks').first()
    on_break=bool(current and current.breaks.filter(ended_at__isnull=True).exists())
    from .payments import hours_balance
    return {'current':current,'on_break':on_break,**hours_balance(user)}


@login_required
def home(request):
    from .roast_sheet import roast_sheet
    return roast_sheet(request)

def models_overlap(start):
    from django.db.models import Q
    return Q(ended_at__isnull=True)|Q(ended_at__gt=start)

@login_required
@require_POST
def clock(request):
    action=request.POST.get('action')
    destination='timesheets' if request.POST.get('return')=='hours' else 'home'
    if action not in {'in','out','break_start','break_end'}: return HttpResponseBadRequest('Unknown action')
    with transaction.atomic():
        # Lock the employee row even when there is no active shift.
        from django.contrib.auth import get_user_model
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        shift=Shift.objects.select_for_update().filter(user=request.user,ended_at__isnull=True,removed_at__isnull=True).first()
        now=timezone.now()
        if action=='in' and shift is None:
            shift=Shift.objects.create(user=request.user,started_at=now)
        elif action=='out' and shift:
            WorkBreak.objects.filter(shift=shift,ended_at__isnull=True).update(ended_at=now)
            shift.ended_at=now; shift.save(update_fields=['ended_at'])
        elif action=='break_start' and shift and not WorkBreak.objects.filter(shift=shift,ended_at__isnull=True).exists():
            WorkBreak.objects.create(shift=shift,started_at=now)
        elif action=='break_end' and shift and WorkBreak.objects.filter(shift=shift,ended_at__isnull=True).exists():
            WorkBreak.objects.filter(shift=shift,ended_at__isnull=True).update(ended_at=now)
        else:
            messages.error(request,'That action is not valid for your current shift.')
            return redirect(destination)
        TimeEvent.objects.create(user=request.user,shift=shift,action=action,at=now)
    messages.success(request,{'in':'Clocked in','out':'Clocked out','break_start':'Break started','break_end':'Break ended'}[action])
    return redirect(destination)

@login_required
def new_batch(request):
    form=BatchForm(request.POST or None,initial={'date':timezone.localdate()})
    if request.method=='POST' and form.is_valid():
        b=form.save(commit=False); b.operator=request.user; b.measured_at=timezone.now(); b.save()
        messages.success(request,'Batch measured and logged.')
        return redirect('batch_detail',pk=b.pk)
    return render(request,'portal/new_batch.html',{'form':form})

@login_required
def batch_detail(request,pk):
    batch=get_object_or_404(Batch.objects.select_related('coffee','roaster','operator'),pk=pk)
    if request.method=='POST':
        if batch.sealed_at: return HttpResponseBadRequest('Already sealed')
        action=request.POST.get('action')
        now=timezone.now()
        if action=='roast' and batch.measured_at and not batch.roasted_at:
            try: weight=Decimal(request.POST.get('roasted_oz',''))
            except (InvalidOperation, TypeError): weight=Decimal('0')
            if weight<=0 or weight>Decimal('9999999'):
                messages.error(request,'Enter a positive roasted weight in ounces.')
            else:
                if (batch.order_id and batch.order.target_finish_temp_f is not None) or (batch.planned_group_id and batch.planned_group.target_finish_temp_f is not None):
                    try: actual_temp=Decimal(request.POST.get('actual_finish_temp_f',''))
                    except (InvalidOperation,TypeError): actual_temp=Decimal('0')
                    if actual_temp<=0 or actual_temp>9999:
                        messages.error(request,'Enter the actual finish temperature in °F for this custom roast.')
                        return redirect('batch_detail',pk=pk)
                    batch.actual_finish_temp_f=actual_temp
                batch.roasted_oz=weight; batch.roasted_at=now
                batch.save(update_fields=['roasted_oz','roasted_at','actual_finish_temp_f'])
        elif action=='bag' and batch.roasted_at and not batch.bagged_at:
            batch.bagged_at=now; batch.save(update_fields=['bagged_at'])
        elif action=='seal' and batch.bagged_at and not batch.sealed_at:
            batch.sealed_at=now; batch.save(update_fields=['sealed_at'])
        else:
            messages.error(request,'Complete the preceding step first.')
        return redirect('batch_detail',pk=pk)
    return render(request,'portal/batch.html',{'batch':batch})

@login_required
def orders(request):
    # Customer details visible only to managers; operators use linked batch pages.
    if not request.user.is_staff: return HttpResponse('Managers only',status=403)
    qs=CustomOrder.objects.select_related('coffee','created_by').prefetch_related('batches')[:150]
    return render(request,'portal/orders.html',{'orders':qs})

@staff_member_required
def new_order(request):
    form=CustomOrderForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        order=form.save(commit=False); order.created_by=request.user; order.save()
        messages.success(request,'Custom roast order created.')
        return redirect('order_detail',pk=order.pk)
    return render(request,'portal/new_order.html',{'form':form})

@login_required
def order_detail(request,pk):
    if not request.user.is_staff: return HttpResponse('Managers only',status=403)
    order=get_object_or_404(CustomOrder.objects.select_related('coffee').prefetch_related('batches__roaster'),pk=pk)
    if request.method=='POST':
        action=request.POST.get('action')
        if order.fulfilled_at or order.cancelled_at:
            return HttpResponseBadRequest('This order is closed.')
        if action=='add_batch':
            try: weight=Decimal(request.POST.get('green_oz',''))
            except (InvalidOperation,TypeError): weight=Decimal('0')
            roaster=Roaster.objects.filter(pk=request.POST.get('roaster_id'),active=True).first()
            if weight<=0 or weight>999999 or not roaster:
                messages.error(request,'Choose an active roaster and positive measured green weight in ounces.')
            else:
                batch=Batch(operator=request.user,order=order,coffee=order.coffee,label_variant=order.label_variant,roaster=roaster,green_oz=weight,roast_level=order.roast_level,measured_at=timezone.now(),date=timezone.localdate(),note=f'Custom order #{order.pk}; '+(f'requested {order.target_finish_temp_f}°F' if order.target_finish_temp_f is not None else f'standard {order.roast_level} roast'))
                try: batch.save()
                except ValidationError as error:
                    messages.error(request,'; '.join(error.messages))
                    return redirect('order_detail',pk=order.pk)
                return redirect('batch_detail',pk=batch.pk)
        elif action=='fulfill':
            if order.status!='Ready':
                messages.error(request,'Not ready: sealed roasted batches must total at least the ordered finished weight.')
            else:
                order.fulfilled_at=timezone.now(); order.save(update_fields=['fulfilled_at'])
                messages.success(request,'Order marked fulfilled.')
        elif action=='cancel':
            order.cancelled_at=timezone.now(); order.save(update_fields=['cancelled_at'])
            messages.success(request,'Order cancelled; previous batches are retained.')
        else:
            return HttpResponseBadRequest('Unknown action')
        return redirect('order_detail',pk=pk)
    return render(request,'portal/order_detail.html',{'order':order,'roasters':Roaster.objects.filter(active=True)})

@login_required
def history(request):
    deleted=request.GET.get('deleted')=='1'
    qs=Batch.all_objects.filter(removed_at__isnull=not deleted).select_related('coffee','roaster','operator')
    q=request.GET.get('q','').strip()[:80]
    if q:
        from django.db.models import Q
        qs=qs.filter(Q(coffee__name__icontains=q)|Q(experimental_origin__icontains=q)|Q(note__icontains=q)|Q(operator__username__icontains=q))
    return render(request,'portal/history.html',{'batches':qs[:200],'q':q,'deleted':deleted})

@login_required
def timesheets(request):
    everyone=request.user.is_staff and request.GET.get('scope')=='all'
    deleted=request.GET.get('deleted')=='1'
    qs=Shift.objects.filter(removed_at__isnull=not deleted)
    if everyone:
        shifts=qs.select_related('user').prefetch_related('breaks')[:100]
    else:
        shifts=qs.filter(user=request.user).prefetch_related('breaks')[:100]
    return render(request,'portal/timesheets.html',{'entries':[(s,round(seconds_worked(s)/3600,2)) for s in shifts],'everyone':everyone,'deleted':deleted,**clock_context(request.user)})

@staff_member_required
def export_timesheets(request):
    response=HttpResponse(content_type='text/csv')
    response['Content-Disposition']='attachment; filename="coffee-timesheets.csv"'
    writer=csv.writer(response)
    writer.writerow(['Employee','Clock in (UTC)','Clock out (UTC)','Net hours','Status'])
    for s in Shift.objects.filter(removed_at__isnull=True).select_related('user').prefetch_related('breaks').order_by('started_at'):
        writer.writerow([s.user.username,s.started_at.isoformat(),s.ended_at.isoformat() if s.ended_at else '',f'{seconds_worked(s)/3600:.2f}','Closed' if s.ended_at else 'Open'])
    return response
