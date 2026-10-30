"""Explicit platform choices; never disconnect a store or rewrite its orders."""
import hashlib,json
from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from .models import PortalConfiguration,StoreConnection,ShopifyConnection

CHOICES=[(key,label) for key,label in StoreConnection.PLATFORMS if key!='csv']

def selection(config=None):
    config=config if config is not None else PortalConfiguration.objects.filter(pk=1).first()
    if config and config.marketplaces is not None:return list(config.marketplaces)
    # Existing installations retain every saved connection until deliberately changed.
    found=set(StoreConnection.objects.exclude(platform='csv').values_list('platform',flat=True))
    if ShopifyConnection.objects.exists():found.add('shopify')
    return [key for key,_ in CHOICES if key in found]

def selection_token(config=None):
    config=config if config is not None else PortalConfiguration.objects.filter(pk=1).first()
    return hashlib.sha256(json.dumps([bool(config and config.marketplaces is not None),selection(config)],sort_keys=True).encode()).hexdigest()

class MarketplaceForm(forms.Form):
    selection_token=forms.CharField(widget=forms.HiddenInput)
    marketplaces=forms.MultipleChoiceField(choices=CHOICES+[('manual','No online marketplace — manual orders / CSV only')],widget=forms.CheckboxSelectMultiple,label='Where do you receive orders?')
    def clean_marketplaces(self):
        values=self.cleaned_data['marketplaces']
        if 'manual' in values and len(values)>1:raise ValidationError('Choose manual-only, or select your online marketplaces. Manual orders and CSV remain available with every platform.')
        return sorted(values)

@transaction.atomic
def save_selection(post):
    config,_=PortalConfiguration.objects.get_or_create(pk=1)
    config=PortalConfiguration.objects.select_for_update().get(pk=config.pk)
    form=MarketplaceForm(post)
    if not form.is_valid():return form,False
    if form.cleaned_data['selection_token']!=selection_token(config):
        form.add_error(None,'Marketplace choices changed in another tab. Reload before saving.');return form,False
    chosen=form.cleaned_data['marketplaces']
    required=set(StoreConnection.objects.filter(active=True).exclude(platform='csv').values_list('platform',flat=True))
    if ShopifyConnection.objects.exists():required.add('shopify')
    missing=required-set(chosen)
    if missing:
        labels=dict(CHOICES)
        form.add_error(None,'Keep '+', '.join(labels[key] for key in sorted(missing))+' selected while connected. Pause its stores first; the existing Shopify connection must remain selected.');return form,False
    config.marketplaces=chosen;config.save(update_fields=['marketplaces'])
    return form,True
