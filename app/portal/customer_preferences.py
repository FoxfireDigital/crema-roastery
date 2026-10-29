"""Explicit customer defaults; saving preferences never creates production."""
from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.contrib.auth import get_user_model
from .models import WholesaleCustomer,CustomerPreferenceEvent,GRIND_CHOICES


def customer_key(name):return ' '.join(name.strip().casefold().split())


class PreferenceForm(forms.Form):
    customer=forms.CharField(max_length=120)
    usual_grind=forms.ChoiceField(choices=[v for v in GRIND_CHOICES if v[0] in ('whole','regular','fine','coarse')],initial='whole')
    customer_version=forms.CharField(required=False)


@transaction.atomic
def save_preferences(actor,data,rows):
    from .wholesale import original_items
    get_user_model().objects.select_for_update().get(pk=actor.pk)
    key=customer_key(data['customer'])
    customer,created=WholesaleCustomer.objects.select_for_update().get_or_create(name_key=key,defaults={'name':data['customer'],'updated_by':actor})
    if not created and str(customer.version)!=str(data.get('customer_version','')):
        raise ValidationError('This customer’s preferences changed. Reload their usual order before saving new preferences.')
    if created and data.get('customer_version') not in ('',None):raise ValidationError('Choose the customer again before saving preferences.')
    before={} if created else {'name':customer.name,'grind':customer.default_grind,'items':customer.usual_items}
    customer.name=data['customer'];customer.default_grind=data['usual_grind'];customer.usual_items=original_items(rows);customer.updated_by=actor
    after={'name':customer.name,'grind':customer.default_grind,'items':customer.usual_items}
    if before!=after:
        customer.version+=1;customer.save()
        CustomerPreferenceEvent.objects.create(customer=customer,actor=actor,before=before,after=after)
    return customer
