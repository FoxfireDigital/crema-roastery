"""Explainable management estimates, separate from stock, payroll and accounting."""
import csv
import hashlib
import io
import json
import re
import uuid
from decimal import Decimal, ROUND_HALF_UP
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import (Batch, Coffee, CostEstimate, CostEvent, CostProfile, GreenBatchUsage,
                     GreenBeanItem, GreenPurchase, GreenRecipe, LabelVariant, ROAST_LEVELS,
                     ShopifyCatalog, ShopifyConnection)

SALT = 'crema-costing-v1'
ZERO = Decimal('0')
HUNDRED = Decimal('100')
PARAMETERS = ['green_cost_per_lb', 'yield_pct', 'bag_cost', 'label_cost', 'flavor_cost',
              'labor_minutes', 'labor_rate', 'other_production_cost', 'retail_price',
              'wholesale_price', 'fee_pct', 'fixed_fee', 'other_selling_cost',
              'wholesale_fee_pct', 'wholesale_fixed_fee', 'wholesale_other_selling_cost']
COMPONENTS = [('bag_cost', 'Bag / packaging'), ('label_cost', 'Label'),
              ('flavor_cost', 'Flavoring'), ('other_production_cost', 'Other production')]


def number(value, *, maximum=Decimal('1000000000000'), positive=False):
    if value is None or value == '':
        return None
    try:
        if isinstance(value, bool):
            raise ValueError()
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result > maximum or positive and result <= 0:
            raise ValueError()
        return result
    except (ValueError, TypeError, ArithmeticError):
        raise ValidationError('Cost inputs must be finite, nonnegative numbers within the displayed limits.')


def decimal_text(value):
    if value is None:
        return None
    text = format(value, 'f') if isinstance(value, Decimal) else str(value)
    return text.rstrip('0').rstrip('.') if '.' in text else text


def money(value):
    return None if value is None else str(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


def calculate(inputs, size_oz, quantity=1):
    """Pure calculation. Keep precision until presentation; unknown never means zero."""
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 100000:
        raise ValidationError('Compare between 1 and 100,000 bags of this product.')
    size = number(size_oz, maximum=Decimal('100000'), positive=True)
    if size is None:
        raise ValidationError('Record a positive finished bag weight.')
    values = {name: number(inputs.get(name), maximum=HUNDRED if name == 'yield_pct' or name.endswith('fee_pct') else Decimal('1000000000000'), positive=name == 'yield_pct') for name in PARAMETERS}
    missing = []
    rate, yield_pct = values['green_cost_per_lb'], values['yield_pct']
    coffee_cost = rate * size / 16 / (yield_pct / 100) if rate is not None and yield_pct is not None else None
    if rate is None:
        missing.append('Green coffee cost')
    if yield_pct is None:
        missing.append('Roast yield')
    parts = [{'name': 'Yield-adjusted coffee', 'value': money(coffee_cost)}]
    total = coffee_cost
    for key, title in COMPONENTS:
        value = values[key]
        parts.append({'name': title, 'value': money(value)})
        if value is None:
            missing.append(title)
        total = total + value if total is not None and value is not None else None
    minutes, hourly = values['labor_minutes'], values['labor_rate']
    # Zero minutes is an explicit no-labor allocation, not an unknown rate.
    labor = ZERO if minutes == 0 else minutes * hourly / 60 if minutes is not None and hourly is not None else None
    if labor is None:
        missing.append('Production labor (minutes and hourly allocation rate)')
    parts.append({'name': 'Production labor', 'value': money(labor)})
    total = total + labor if total is not None and labor is not None else None
    missing_selling = []
    channels = []
    for key, title in [('retail_price', 'Retail'), ('wholesale_price', 'Wholesale')]:
        price = values[key]
        prefix = 'wholesale_' if key == 'wholesale_price' else ''
        channel_missing = [label for suffix, label in [('fee_pct', 'Merchant fee percentage'), ('fixed_fee', 'Fixed fee per order'), ('other_selling_cost', 'Other selling cost per bag')] if values[prefix + suffix] is None]
        missing_selling.extend(title + ': ' + label for label in channel_missing)
        profit = price - total if price is not None and total is not None else None
        fee_known = values[prefix + 'fee_pct'] is not None and values[prefix + 'fixed_fee'] is not None
        fee = price * values[prefix + 'fee_pct'] / 100 + values[prefix + 'fixed_fee'] / quantity if price is not None and fee_known else None
        contribution = profit - fee - values[prefix + 'other_selling_cost'] if profit is not None and fee is not None and values[prefix + 'other_selling_cost'] is not None else None
        channels.append({'name': title, 'price': money(price), 'production_profit': money(profit),
                         'production_margin': money(profit / price * 100) if profit is not None and price else None,
                         'selling_fees': money(fee), 'contribution_profit': money(contribution),
                         'contribution_margin': money(contribution / price * 100) if contribution is not None and price else None,
                         'order_contribution': money(contribution * quantity) if contribution is not None else None})
    return {'quantity': quantity, 'size_oz': decimal_text(size), 'components': parts,
            'yield_pct': decimal_text(yield_pct), 'green_oz_per_bag': decimal_text(size / (yield_pct / 100)) if yield_pct is not None else None,
            'production_cost': money(total), 'production_cost_unrounded': decimal_text(total),
            'order_production_cost': money(total * quantity) if total is not None else None,
            'missing_production': missing, 'missing_selling': missing_selling, 'channels': channels,
            'production_complete': not missing}


def current_catalog():
    connection = ShopifyConnection.objects.filter(pk=1).first()
    catalog = ShopifyCatalog.objects.filter(pk=1).first()
    if not connection or not catalog or not catalog.checked_at or not connection.access_token_cipher or catalog.shop_domain != connection.shop_domain:
        return None
    return catalog


def price_options(catalog):
    if not catalog or not isinstance(catalog.products, list):
        return {}
    result = {}
    for product in catalog.products:
        if not isinstance(product, dict) or product.get('status') not in ['ACTIVE', 'UNLISTED'] or not isinstance(product.get('variants'), list):
            continue
        for variant in product.get('variants', []):
            if not isinstance(variant, dict) or not isinstance(variant.get('id'), str) or not variant['id'].startswith('gid://shopify/ProductVariant/'):
                continue
            value = variant.get('price')
            currency = variant.get('currency', '')
            if value is None or not isinstance(currency, str) or not re.fullmatch(r'[A-Z]{3}', currency):
                continue
            try:
                number(value)
            except ValidationError:
                continue
            result[variant['id']] = {'price': value, 'currency': currency, 'taxes_included': variant.get('taxesIncluded'),
                                     'title': str(product.get('title') or 'Unnamed product') + ' — ' + str(variant.get('title') or 'Unnamed variant'), 'sku': variant.get('sku', ''),
                                     'checked_at': catalog.checked_at.isoformat(), 'shop_domain': catalog.shop_domain}
    return result


def physical_coffee(profile, batch=None):
    if batch:
        allowed = batch.coffee_id == profile.coffee_id
        if profile.coffee.kind == 'flavored':
            allowed = batch.coffee.flavor_base_eligible and batch.roast_level == 'Medium'
        if not allowed or batch.roast_level != profile.roast_level:
            raise ValidationError('Choose a batch with the correct physical coffee and roast for this cost profile.')
        if not batch.roasted_at or batch.roasted_oz is None or not batch.green_oz or not 0 < batch.roasted_oz <= batch.green_oz or batch.date > timezone.localdate():
            raise ValidationError('Use a completed roast with valid actual green and finished weights.')
        return batch.coffee
    return profile.coffee.roasting_coffee


def green_basis(profile, coffee, batch, as_of):
    manual = profile.parameters.get('green_cost_per_lb')
    if manual is not None and manual != '':
        return number(manual), [{'kind': 'manual', 'description': 'Reviewed green cost per pound; estimate, not inventory valuation'}], []
    warnings = []
    if batch:
        usage = GreenBatchUsage.objects.filter(batch=batch).first()
        if usage and usage.amounts:
            try:
                amounts = {str(int(k)): number(v, positive=True) for k, v in usage.amounts.items()}
                total = sum(amounts.values(), ZERO)
                assert total == batch.green_oz and len(amounts) <= 12
                percentages = {k: v / total * 100 for k, v in amounts.items()}
            except (ValueError, TypeError, ArithmeticError, AssertionError, ValidationError):
                return None, [], ['Saved measured ingredients cannot be costed reliably. Review the original usage.']
        elif batch.green_item_id:
            percentages = {str(batch.green_item_id): HUNDRED}
        else:
            return None, [], ['This roast has no saved green-origin usage. Enter a reviewed manual green cost; its old usage is not reconstructed.']
    else:
        recipe = GreenRecipe.objects.filter(coffee=coffee).first()
        try:
            percentages = {str(int(c['item'])): number(c['percent'], maximum=HUNDRED, positive=True) for c in recipe.components} if recipe else {}
            assert recipe and 1 <= len(percentages) <= 12 and len(percentages) == len(recipe.components) and sum(percentages.values(), ZERO) == 100
        except (KeyError, ValueError, TypeError, ArithmeticError, AssertionError, ValidationError):
            return None, [], ['Set a complete green recipe or enter a reviewed manual green cost.']
    sources = []
    total_rate = ZERO
    for pk, percent in sorted(percentages.items()):
        item = GreenBeanItem.objects.filter(pk=pk).first()
        receipt = GreenPurchase.objects.filter(item_id=pk, voided_at__isnull=True, received_on__lte=as_of).first()
        source = {'item_id': pk, 'item_name': item.name if item else 'Missing origin', 'percent': str(percent),
                  'purchase_id': receipt.pk if receipt else None, 'purchase_version': receipt.version if receipt else None,
                  'received_on': str(receipt.received_on) if receipt else None,
                  'quantity_oz': str(receipt.quantity_oz) if receipt else None,
                  'landed_cost': decimal_text(receipt.total_cost) if receipt else None,
                  'currency': receipt.currency if receipt else None}
        sources.append(source)
        if not item or not receipt or receipt.total_cost is None or receipt.quantity_oz <= 0 or receipt.currency != profile.currency:
            warnings.append('Missing same-currency landed receipt cost for ' + source['item_name'] + '. No older priced receipt is substituted.')
            continue
        rate = receipt.total_cost / receipt.quantity_oz * 16
        total_rate += rate * percent / 100
        source['cost_per_green_lb'] = str(rate)
        if 'estimated' in (item.name + ' ' + item.notes + ' ' + receipt.notes).casefold():
            source['quantity_estimated'] = True
    if any('cost_per_green_lb' not in source for source in sources):
        return None, sources, warnings
    if any(source.get('quantity_estimated') for source in sources):
        warnings.append('Some receipt weights are estimates. Confirm net weights before relying on the resulting costs.')
    return total_rate, sources, warnings


def estimate(profile, batch=None, quantity=1):
    coffee = physical_coffee(profile, batch)
    as_of = batch.date if batch else timezone.localdate()
    values = {name: profile.parameters.get(name) for name in PARAMETERS}
    rate, green_sources, warnings = green_basis(profile, coffee, batch, as_of)
    values['green_cost_per_lb'] = decimal_text(rate)
    if batch:
        values['yield_pct'] = str(batch.roasted_oz / batch.green_oz * 100)
    catalog = current_catalog()
    price_source = {'kind': 'manual', 'description': 'Entered selling prices; review taxes and discounts'}
    if profile.parameters.get('retail_from_shopify'):
        variant = price_options(catalog).get(profile.parameters.get('shopify_variant', ''))
        domain = profile.parameters.get('shopify_domain')
        if not variant or variant['shop_domain'] != domain or variant['currency'] != profile.currency or variant['taxes_included'] is not False:
            values['retail_price'] = None
            warnings.append('Linked Shopify price is unavailable, changed store/currency, or includes unverified tax. Refresh product checks or enter a net manual price.')
        else:
            values['retail_price'] = variant['price']
            price_source = {'kind': 'shopify_catalog', 'variant_id': profile.parameters['shopify_variant'], **variant}
            warnings.append('Shopify price is the checked catalog list price, not discounted order revenue or live settlement proceeds.')
    result = calculate(values, profile.size_oz, quantity)
    payload = {'schema': 'crema-cost-estimate-v1', 'name': profile.name, 'profile_id': profile.pk,
               'profile_version': profile.version, 'coffee': profile.coffee.name, 'physical_coffee': coffee.name,
               'label': profile.label_variant.name if profile.label_variant_id else 'Standard product label',
               'roast_level': profile.roast_level, 'currency': profile.currency, 'as_of': str(as_of),
               'review_note': profile.parameters.get('note', ''), 'inputs': values, 'green_sources': green_sources, 'price_source': price_source,
               'warnings': warnings, 'batch_id': batch.pk if batch else None,
               'batch_green_oz': decimal_text(batch.green_oz) if batch else None,
               'batch_finished_oz': decimal_text(batch.roasted_oz) if batch else None,
               'basis': 'Actual batch yield with reviewed/current cost assumptions' if batch else 'Planned yield and reviewed/current cost assumptions',
               'receipt_method': 'Latest nonvoided receipt for each ingredient on/before basis date; not FIFO or accounting inventory valuation',
               'result': result}
    payload['fingerprint'] = digest(payload)
    return payload


class CostProfileForm(forms.Form):
    name = forms.CharField(max_length=160, label='Cost profile name')
    coffee = forms.ModelChoiceField(queryset=Coffee.objects.none())
    label_variant = forms.ModelChoiceField(queryset=LabelVariant.objects.all(), required=False, label='Packaging label identity (optional)')
    roast_level = forms.ChoiceField(choices=ROAST_LEVELS)
    size_oz = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('.01'), max_value=100000, label='Finished ounces per bag')
    currency = forms.RegexField(r'^[A-Z]{3}$', max_length=3, initial='USD', label='Currency code')
    yield_pct = forms.DecimalField(max_digits=6, decimal_places=3, min_value=Decimal('.001'), max_value=100, required=False, label='Expected roast yield (%)')
    green_cost_per_lb = forms.DecimalField(max_digits=12, decimal_places=4, min_value=0, required=False, label='Manual green cost per lb (blank: use recipe receipts)')
    labor_minutes = forms.DecimalField(max_digits=9, decimal_places=3, min_value=0, required=False, label='Allocated production minutes per bag')
    labor_rate = forms.DecimalField(max_digits=12, decimal_places=4, min_value=0, required=False, label='Allocated labor cost per hour')
    fee_pct = forms.DecimalField(max_digits=6, decimal_places=3, min_value=0, max_value=100, required=False, label='Merchant selling fee (%)')
    wholesale_fee_pct = forms.DecimalField(max_digits=6, decimal_places=3, min_value=0, max_value=100, required=False, label='Wholesale merchant fee (%)')
    retail_from_shopify = forms.BooleanField(required=False, label='Use this explicitly matched Shopify catalog price for retail')
    shopify_variant = forms.ChoiceField(required=False, label='Shopify variant (review coffee, bag size and grind)')
    active = forms.BooleanField(required=False, initial=True)
    change_note = forms.CharField(max_length=300, label='Reason / cost assumption note')
    for key, label in [('bag_cost', 'Bag / packaging cost per bag'), ('label_cost', 'Label cost per bag'),
                       ('flavor_cost', 'Flavoring cost per bag'), ('other_production_cost', 'Other production cost per bag'),
                       ('retail_price', 'Manual retail price per bag, excluding tax'), ('wholesale_price', 'Wholesale price per bag, excluding tax'),
                       ('fixed_fee', 'Retail fixed merchant fee per order'), ('other_selling_cost', 'Retail other selling cost per bag (for example net shipping subsidy)'),
                       ('wholesale_fixed_fee', 'Wholesale fixed merchant fee per order'), ('wholesale_other_selling_cost', 'Wholesale other selling cost per bag')]:
        locals()[key] = forms.DecimalField(max_digits=12, decimal_places=4, min_value=0, required=False, label=label)

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['coffee'].queryset = Coffee.objects.filter(Q(active=True) | Q(pk=profile.coffee_id if profile else None))
        self.catalog = current_catalog()
        choices = price_options(self.catalog)
        self.fields['shopify_variant'].choices = [('', 'No Shopify price link')] + [(pk, row['title'] + ' · ' + row['currency'] + ' ' + str(row['price'])) for pk, row in choices.items()]
        old = (profile.parameters if profile else {}).get('shopify_variant')
        if old and old not in choices:
            self.fields['shopify_variant'].choices.append((old, 'Previously linked variant — refresh product checks'))
        self.fields['change_note'].widget = forms.Textarea(attrs={'rows': 2})
        self.fields['yield_pct'].help_text = 'Finished weight ÷ green input × 100. Use 85 for a 15% roast loss.'
        self.fields['labor_minutes'].help_text = 'Enter 0 only for an explicit no-labor allocation. Otherwise enter minutes and an hourly cost rate.'
        self.fields['fixed_fee'].help_text = 'Charged once across the comparison quantity, not once per bag.'

    def clean(self):
        data = super().clean()
        coffee, label = data.get('coffee'), data.get('label_variant')
        if label and coffee and label.coffee_id != coffee.pk:
            self.add_error('label_variant', 'Choose a label belonging to this coffee.')
        if coffee and coffee.roast_locked and data.get('roast_level') != coffee.standard_roast:
            self.add_error('roast_level', 'Use this blend or flavor’s standard roast.')
        if data.get('retail_from_shopify'):
            variant = price_options(self.catalog).get(data.get('shopify_variant'))
            if not variant or variant['currency'] != data.get('currency') or variant['taxes_included'] is not False:
                self.add_error('shopify_variant', 'Refresh product checks and choose a same-currency, tax-exclusive catalog price. Otherwise use a manual net price.')
        return data


def profile_state(profile):
    return {'name': profile.name, 'coffee_id': profile.coffee_id, 'label_variant_id': profile.label_variant_id,
            'roast_level': profile.roast_level, 'size_oz': str(profile.size_oz), 'currency': profile.currency,
            'parameters': profile.parameters, 'active': profile.active, 'version': profile.version}


def ticket(actor, profile=None, **extra):
    return signing.dumps({'actor': actor.pk, 'profile': profile.pk if profile else None,
                          'version': profile.version if profile else 0, 'nonce': str(uuid.uuid4()), **extra}, salt=SALT, compress=True)


def request_identity(post, actor, pk, action):
    if not actor.is_active or not actor.is_staff:
        raise PermissionDenied()
    try:
        packet = signing.loads(post.get('ticket', ''), salt=SALT, max_age=14400)
        assert packet['actor'] == actor.pk and packet['profile'] == pk and packet.get('action', 'profile') == action
        key = uuid.UUID(packet['nonce'])
    except (signing.BadSignature, ValueError, TypeError, KeyError, AssertionError):
        raise ValidationError('This cost form expired or belongs to another record. Reload before saving.')
    fingerprint = digest({k: post.getlist(k) for k in post if k not in ['ticket', 'csrfmiddlewaretoken']})
    prior = CostEvent.objects.filter(request_key=key).first()
    if prior and (prior.actor_id != actor.pk or prior.action != action or prior.request_hash != fingerprint):
        raise ValidationError('This request was already saved with different values. Reload before changing it.')
    return packet, key, fingerprint, prior


def save_profile(post, actor, pk=None):
    with transaction.atomic():
        packet, key, fingerprint, prior = request_identity(post, actor, pk, 'profile')
        if prior:
            return prior.profile
        obj = get_object_or_404(CostProfile.objects.select_for_update(), pk=pk) if pk else CostProfile(updated_by=actor)
        if packet['version'] != obj.version:
            raise ValidationError('These cost assumptions changed. Reload before saving.')
        form = CostProfileForm(post, profile=obj if pk else None)
        if not form.is_valid():
            raise ValidationError([str(e) for errors in form.errors.values() for e in errors])
        values = form.cleaned_data
        before = profile_state(obj) if pk else {}
        for name in ['name', 'coffee', 'label_variant', 'roast_level', 'size_oz', 'currency', 'active']:
            setattr(obj, name, values[name])
        obj.parameters = {name: decimal_text(values.get(name)) for name in PARAMETERS}
        obj.parameters.update(retail_from_shopify=values['retail_from_shopify'], shopify_variant=values['shopify_variant'],
                              shopify_domain=form.catalog.shop_domain if form.catalog and values['shopify_variant'] else '', note=values['change_note'])
        obj.version += 1
        obj.updated_by = actor
        obj.save()
        CostEvent.objects.create(profile=obj, actor=actor, action='profile', before=before, after=profile_state(obj), request_key=key, request_hash=fingerprint)
        return obj


def save_estimate(post, actor, pk):
    with transaction.atomic():
        packet, key, fingerprint, prior = request_identity(post, actor, pk, 'estimate')
        if prior:
            return prior.estimate
        profile = get_object_or_404(CostProfile.objects.select_for_update(of=('self',)).select_related('coffee', 'label_variant'), pk=pk)
        if packet['version'] != profile.version:
            raise ValidationError('This cost profile changed. Review a fresh estimate before saving.')
        batch = get_object_or_404(Batch.objects.select_for_update(of=('self',)).select_related('coffee'), pk=packet['batch']) if packet.get('batch') else None
        coffee = physical_coffee(profile, batch)
        Coffee.objects.select_for_update().get(pk=coffee.pk)
        recipe = GreenRecipe.objects.select_for_update().filter(coffee=coffee).first()
        usage = GreenBatchUsage.objects.select_for_update().filter(batch=batch).first() if batch else None
        # The inventory parent locks prevent a new receipt racing the saved basis;
        # receipt and catalog locks also serialize invoice and price corrections.
        item_ids = list(usage.amounts) if usage else [str(batch.green_item_id)] if batch and batch.green_item_id else [str(c.get('item')) for c in recipe.components] if recipe else []
        item_ids = [int(pk) for pk in item_ids if str(pk).isdigit()]
        list(GreenBeanItem.objects.select_for_update().filter(pk__in=item_ids).order_by('pk'))
        list(GreenPurchase.objects.select_for_update().filter(item_id__in=item_ids).order_by('pk'))
        list(ShopifyCatalog.objects.select_for_update().filter(pk=1))
        payload = estimate(profile, batch, packet.get('quantity', 1))
        if payload['fingerprint'] != packet.get('preview'):
            raise ValidationError('Prices, receipts or production changed after this preview. Reload and review before saving.')
        saved = CostEstimate.objects.create(profile=profile, batch=batch, created_by=actor, payload=payload)
        CostEvent.objects.create(profile=profile, actor=actor, action='estimate', before={}, after={'estimate': saved.pk, 'fingerprint': payload['fingerprint']}, request_key=key, request_hash=fingerprint, estimate=saved)
        return saved


def initial_values(profile):
    if not profile:
        return {'currency': 'USD', 'active': True}
    return {**profile_state(profile), 'coffee': profile.coffee_id, 'label_variant': profile.label_variant_id,
            **profile.parameters, 'change_note': profile.parameters.get('note', '')}


@staff_member_required
@require_http_methods(['GET'])
def dashboard(request):
    rows = []
    for profile in CostProfile.objects.select_related('coffee', 'label_variant')[:300]:
        try:
            payload = estimate(profile)
            rows.append({'profile': profile, 'payload': payload, 'result': payload['result']})
        except ValidationError as exc:
            rows.append({'profile': profile, 'error': '; '.join(exc.messages)})
    return render(request, 'portal/costing.html', {'rows': rows, 'recent': CostEstimate.objects.select_related('profile', 'created_by')[:20]})


@staff_member_required
@require_http_methods(['GET', 'POST'])
def profile_page(request, pk=None):
    profile = get_object_or_404(CostProfile.objects.select_related('coffee', 'label_variant'), pk=pk) if pk else None
    error, status = '', 200
    if request.method == 'POST':
        try:
            if request.POST.get('action') == 'estimate' and pk:
                saved = save_estimate(request.POST, request.user, pk)
                return redirect('/costing/estimates/' + str(saved.pk) + '/')
            if request.POST.get('action') != 'profile':
                raise ValidationError('Choose Save cost profile or Save reviewed estimate.')
            saved = save_profile(request.POST, request.user, pk)
            messages.success(request, 'Cost assumptions saved. Stock, payroll and marketplace prices are unchanged.')
            return redirect('/costing/' + str(saved.pk) + '/')
        except (ValidationError, IntegrityError) as exc:
            error = '; '.join(exc.messages) if isinstance(exc, ValidationError) else 'That profile name or saved request already exists. Reload to review.'
            status = 400
    form = CostProfileForm(request.POST if request.method == 'POST' and request.POST.get('action') == 'profile' else None, profile=profile, initial=initial_values(profile))
    sections = [('Product', ['name', 'coffee', 'label_variant', 'roast_level', 'size_oz', 'currency', 'active']),
                ('Coffee and production', ['yield_pct', 'green_cost_per_lb', 'bag_cost', 'label_cost', 'flavor_cost', 'labor_minutes', 'labor_rate', 'other_production_cost']),
                ('Retail price and fees', ['retail_price', 'shopify_variant', 'retail_from_shopify', 'fee_pct', 'fixed_fee', 'other_selling_cost']),
                ('Wholesale price and fees', ['wholesale_price', 'wholesale_fee_pct', 'wholesale_fixed_fee', 'wholesale_other_selling_cost']),
                ('Review note', ['change_note'])]
    payload, preview_ticket = None, ''
    quantity, batch = 1, None
    if profile:
        try:
            quantity = int(request.GET.get('quantity', '1'))
            if not 1 <= quantity <= 100000:
                raise ValueError()
            if request.GET.get('batch'):
                batch = get_object_or_404(Batch.objects.select_related('coffee'), pk=request.GET['batch'])
            payload = estimate(profile, batch, quantity)
            preview_ticket = ticket(request.user, profile, action='estimate', preview=payload['fingerprint'], batch=batch.pk if batch else None, quantity=quantity)
        except (ValueError, TypeError, ValidationError) as exc:
            error = '; '.join(exc.messages) if isinstance(exc, ValidationError) else 'Use a valid batch and between 1 and 100,000 bags.'
            status = 400
    batches = []
    if profile:
        matching = Q(coffee=profile.coffee)
        if profile.coffee.kind == 'flavored':
            matching = Q(coffee__flavor_base_allowed=True, coffee__active=True, coffee__experimental=False) & ~Q(coffee__kind='flavored')
        batches = Batch.objects.filter(matching, roast_level=profile.roast_level, roasted_at__isnull=False, roasted_oz__gt=0, green_oz__gt=0, merged_into__isnull=True).select_related('coffee', 'roaster').order_by('-date', '-pk')[:100]
    return render(request, 'portal/cost_profile.html', {'profile': profile, 'form': form, 'sections': [(title, [form[name] for name in names]) for title, names in sections],
                  'ticket': request.POST.get('ticket', '') if request.method == 'POST' and request.POST.get('action') == 'profile' else ticket(request.user, profile), 'payload': payload, 'result': payload['result'] if payload else None,
                  'preview_ticket': preview_ticket, 'error': error, 'quantity': quantity, 'batch': batch, 'batches': batches,
                  'events': profile.events.select_related('actor')[:20] if profile else []}, status=status)


@staff_member_required
@require_http_methods(['GET'])
def estimate_page(request, pk):
    saved = get_object_or_404(CostEstimate.objects.select_related('profile', 'created_by'), pk=pk)
    return render(request, 'portal/cost_estimate.html', {'saved': saved, 'payload': saved.payload, 'result': saved.payload.get('result', {})})


@staff_member_required
@require_http_methods(['GET'])
def export_estimate(request, pk):
    from .recovery import csv_cell
    saved = get_object_or_404(CostEstimate, pk=pk)
    payload = saved.payload
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    def row(*values):writer.writerow([csv_cell(v) for v in values])
    row('Crema management cost estimate', saved.pk, 'Saved at', saved.created_at.isoformat())
    row('Profile', payload['name'], 'Currency', payload['currency'], 'Basis', payload['basis'])
    row('Coffee', payload['coffee'], 'Roast', payload['roast_level'], 'Bag oz', payload['result']['size_oz'])
    row('Component', 'Cost per bag (blank means unknown)')
    for part in payload['result']['components']:
        row(part['name'], part['value'])
    row('Total production cost', payload['result']['production_cost'])
    row('Channel', 'Selling price', 'Production profit', 'Production margin %', 'Selling fees per bag', 'Contribution profit', 'Contribution margin %')
    for channel in payload['result']['channels']:
        row(*(channel.get(key) for key in ['name', 'price', 'production_profit', 'production_margin', 'selling_fees', 'contribution_profit', 'contribution_margin']))
    row('Order comparison quantity', payload['result']['quantity'])
    row('Missing production inputs', '; '.join(payload['result']['missing_production']))
    row('Missing selling inputs', '; '.join(payload['result']['missing_selling']))
    row('Receipt basis', payload['receipt_method'])
    row('Warnings', '; '.join(payload['warnings']))
    row('Frozen inputs and provenance', json.dumps(payload, sort_keys=True))
    response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="crema-cost-estimate-' + str(saved.pk) + '.csv"'
    return response
