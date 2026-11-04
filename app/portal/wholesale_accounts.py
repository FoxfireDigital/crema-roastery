"""Saved business accounts; creating one never creates an order or a plan."""
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction,IntegrityError
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.http import require_http_methods
from .models import WholesaleCustomer,CustomerPreferenceEvent,GRIND_CHOICES
from .customer_preferences import customer_key


class AccountForm(forms.Form):
    name=forms.CharField(max_length=120,label='Business / account name')
    default_grind=forms.ChoiceField(choices=[c for c in GRIND_CHOICES if c[0] in ('whole','regular','fine','coarse')],initial='whole',label='Usual grind')
    notes=forms.CharField(max_length=500,required=False,widget=forms.Textarea(attrs={'rows':2}))
    active=forms.BooleanField(required=False,initial=True,label='Offer this account on new wholesale orders')
    version=forms.CharField(required=False,widget=forms.HiddenInput)
    def clean_name(self):return ' '.join(self.cleaned_data['name'].split())


@staff_member_required
@require_http_methods(['GET','POST'])
def accounts(request,pk=None):
    account=get_object_or_404(WholesaleCustomer,pk=pk) if pk else None
    form=AccountForm(request.POST or None,initial={'name':account.name,'default_grind':account.default_grind,'notes':account.notes,'active':account.active,'version':account.version} if account else {})
    error='';status=200
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                key=customer_key(form.cleaned_data['name'])
                from django.contrib.auth import get_user_model
                get_user_model().objects.select_for_update().get(pk=request.user.pk)
                if account:
                    account=WholesaleCustomer.objects.select_for_update().get(pk=account.pk)
                    if str(account.version)!=form.cleaned_data['version']:raise ValidationError('This account changed. Reload before saving.')
                if WholesaleCustomer.objects.filter(name_key=key).exclude(pk=account.pk if account else None).exists():raise ValidationError('That account already exists. Open its saved account rather than creating a duplicate.')
                before={'name':account.name,'grind':account.default_grind,'active':account.active,'notes':account.notes} if account else {}
                if not account:account=WholesaleCustomer(updated_by=request.user)
                for field in ('name','default_grind','notes','active'):setattr(account,field,form.cleaned_data[field])
                account.name_key=key;account.updated_by=request.user;account.version+=1;account.save()
                CustomerPreferenceEvent.objects.create(customer=account,actor=request.user,before=before,after={'name':account.name,'grind':account.default_grind,'active':account.active,'notes':account.notes})
            messages.success(request,'Wholesale account saved. Existing orders and usual coffee choices were retained.')
            return redirect('/wholesale/accounts/')
        except ValidationError as exc:error='; '.join(exc.messages);status=409
        except IntegrityError:error='That account was created in another tab. Reload the saved accounts before continuing.';status=409
    elif request.method=='POST':status=400
    return render(request,'portal/wholesale_accounts.html',{'account':account,'accounts':WholesaleCustomer.objects.all(),'form':form,'error':error},status=status)
