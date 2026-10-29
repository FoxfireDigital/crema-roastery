from datetime import datetime,time,timedelta
from decimal import Decimal
import uuid
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q,Sum
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from .models import HoursPayment,Shift


def hours_balance(user):
    from .views import seconds_worked
    total=sum(seconds_worked(shift) for shift in Shift.objects.filter(user=user,removed_at__isnull=True).prefetch_related('breaks'))
    paid=HoursPayment.objects.filter(payee=user,voided_at__isnull=True).aggregate(total=Sum('credited_seconds'))['total'] or 0
    return {'hours':round(total/3600,2),'unpaid_hours':round(max(0,total-paid)/3600,2),'paid_hours':round(paid/3600,2),'credit_hours':round(max(0,paid-total)/3600,2),'total_seconds':total,'paid_seconds':paid}


class PaymentForm(forms.Form):
    payer=forms.ModelChoiceField(queryset=get_user_model().objects.none(),label='Paid by')
    payee=forms.ModelChoiceField(queryset=get_user_model().objects.none(),label='Paid to')
    paid_on=forms.DateField(label='Payment date',widget=forms.DateInput(attrs={'type':'date'}))
    through_date=forms.DateField(label='Hours paid through',widget=forms.DateInput(attrs={'type':'date'}),help_text='Include work through the end of this date. For today, include work recorded up to the moment you save.')
    amount=forms.DecimalField(max_digits=12,decimal_places=2,min_value=Decimal('.01'),required=False,label='Amount (USD, optional)')
    note=forms.CharField(max_length=300,required=False,label='Note (optional)')
    request_key=forms.UUIDField(widget=forms.HiddenInput)
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        users=get_user_model().objects.filter(is_active=True).order_by('username')
        self.fields['payer'].queryset=users
        self.fields['payee'].queryset=users if user.is_staff else users.filter(pk=user.pk)
    def clean(self):
        data=super().clean()
        if data.get('payer') and data.get('payer')==data.get('payee'):self.add_error('payee','Choose two different people.')
        for key in ['paid_on','through_date']:
            if data.get(key) and data[key]>timezone.localdate():self.add_error(key,'Choose today or an earlier date.')
        return data


@login_required
def payments(request):
    initial={'payee':request.user.pk,'paid_on':timezone.localdate(),'through_date':timezone.localdate(),'request_key':uuid.uuid4()}
    from .payroll import manager,estimate
    from .models import PayrollAccess
    employer=PayrollAccess.objects.filter(manages_rates=True,user__is_active=True).select_related('user').first()
    if employer:initial['payer']=employer.user_id
    if manager(request.user) and request.GET.get('payee','').isdigit():initial['payee']=request.GET['payee']
    form=PaymentForm(request.POST if request.method=='POST' else None,user=request.user,initial=initial)
    status=200
    if request.method=='POST':
        if form.is_valid():
            data=form.cleaned_data
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=data['payee'].pk)
                existing=HoursPayment.objects.filter(request_key=data['request_key']).first()
                if existing:
                    messages.info(request,'That payment record was already saved. No additional hours were marked paid.')
                    return redirect('payments')
                cutoff=min(timezone.now(),timezone.make_aware(datetime.combine(data['through_date']+timedelta(days=1),time.min)))
                from .views import seconds_worked
                accrued=sum(seconds_worked(s,end=cutoff) for s in Shift.objects.filter(user=data['payee'],removed_at__isnull=True,started_at__lt=cutoff).prefetch_related('breaks'))
                already=HoursPayment.objects.filter(payee=data['payee'],voided_at__isnull=True).aggregate(total=Sum('credited_seconds'))['total'] or 0
                due=estimate(data['payee'],cutoff,already)
                HoursPayment.objects.create(request_key=data['request_key'],payer=data['payer'],payee=data['payee'],paid_on=data['paid_on'],through_date=data['through_date'],covered_until=cutoff,credited_seconds=max(0,accrued-already),amount=data['amount'],estimated_gross=due['gross'],pay_calculation=due['calculation'],note=data['note'],recorded_by=request.user)
            messages.success(request,'Payment recorded. The recipient’s hours through the selected date are marked paid.')
            return redirect('payments')
        status=400
    rows=HoursPayment.objects.select_related('payer','payee','recorded_by')
    if not request.user.is_staff:rows=rows.filter(Q(payee=request.user)|Q(payer=request.user))
    users=list(get_user_model().objects.filter(is_active=True).order_by('username')) if request.user.is_staff else [request.user]
    balances=[{'person':u,**hours_balance(u)} for u in users]
    return render(request,'portal/payments.html',{'form':form,'payments':rows[:200],'balances':balances},status=status)


@login_required
def void_payment(request,pk):
    qs=HoursPayment.objects.filter(voided_at__isnull=True)
    if not request.user.is_staff:qs=qs.filter(recorded_by=request.user,payee=request.user)
    payment=get_object_or_404(qs.select_related('payer','payee'),pk=pk)
    if request.method=='POST':
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=payment.payee_id)
            payment=get_object_or_404(qs.select_for_update(),pk=pk)
            payment.voided_at=timezone.now();payment.voided_by=request.user;payment.save(update_fields=['voided_at','voided_by'])
        messages.success(request,'Payment record voided. Those hours return to the unpaid balance; the original record is retained.')
        return redirect('payments')
    return render(request,'portal/void_payment.html',{'payment':payment})
