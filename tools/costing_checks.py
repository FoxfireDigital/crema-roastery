"""Independent arithmetic, provenance and authorization checks; synthetic rollback only."""
def run_costing_checks(root, client, user):
    import copy
    import csv
    import io
    import json
    from datetime import timedelta
    from decimal import Decimal
    from unittest.mock import patch
    from django.contrib.auth import get_user_model
    from django.core.exceptions import ValidationError
    from django.db import transaction
    from django.http import QueryDict
    from django.test import Client, override_settings
    from django.utils import timezone
    from portal import costing, product_checks
    from portal.models import (Batch, Coffee, CostEstimate, CostEvent, CostProfile, GreenBatchUsage,
                               GreenBeanItem, GreenMovement, GreenPurchase, GreenRecipe, ImportOrder,
                               LabelVariant, Roaster, Shift, ShopifyCatalog, ShopifyConnection)
    from portal.shopify_client import encrypt

    def post(**values):
        data = QueryDict('', mutable=True)
        data.update({k: str(v) for k, v in values.items()})
        return data

    def reject(call):
        try:
            call()
        except ValidationError:
            return
        raise AssertionError('Invalid or stale cost operation accepted')

    inputs = {'green_cost_per_lb': '4', 'yield_pct': '80', 'bag_cost': '.4', 'label_cost': '.1',
              'flavor_cost': '0', 'labor_minutes': '2', 'labor_rate': '15', 'other_production_cost': '0',
              'retail_price': '10', 'wholesale_price': '7', 'fee_pct': '3', 'fixed_fee': '.3', 'other_selling_cost': '0',
              'wholesale_fee_pct': '3', 'wholesale_fixed_fee': '.3', 'wholesale_other_selling_cost': '0'}
    result = costing.calculate(inputs, '16')
    assert result['production_cost'] == '6.00' and Decimal(result['green_oz_per_bag']) == 20
    retail, wholesale = result['channels']
    assert (retail['production_profit'], retail['production_margin'], retail['contribution_profit'], retail['contribution_margin']) == ('4.00', '40.00', '3.40', '34.00')
    assert wholesale['contribution_profit'] == '.49' or wholesale['contribution_profit'] == '0.49'
    invoice = costing.calculate({**inputs, 'wholesale_fee_pct': '0', 'wholesale_fixed_fee': '0'}, 16)
    assert invoice['channels'][1]['contribution_profit'] == '1.00' and invoice['channels'][0]['contribution_profit'] == '3.40'
    bulk = costing.calculate(inputs, 16, 3)
    assert bulk['order_production_cost'] == '18.00' and bulk['channels'][0]['contribution_profit'] == '3.60' and bulk['channels'][0]['order_contribution'] == '10.80'
    fractional = costing.calculate({**inputs, 'fixed_fee': '.25'}, 16, 3)
    assert fractional['channels'][0]['contribution_profit'] == '3.62' and fractional['channels'][0]['order_contribution'] == '10.85'
    missing = costing.calculate({**inputs, 'bag_cost': None}, 16)
    assert not missing['production_complete'] and missing['production_cost'] is None and missing['channels'][0]['production_profit'] is None
    fees_unknown = costing.calculate({**inputs, 'fee_pct': None}, 16)
    assert fees_unknown['channels'][0]['production_profit'] == '4.00' and fees_unknown['channels'][0]['contribution_profit'] is None
    unknown_shipping = costing.calculate({**inputs, 'other_selling_cost': None}, 16)
    assert unknown_shipping['channels'][0]['selling_fees'] == '0.60' and unknown_shipping['channels'][0]['contribution_profit'] is None
    no_labor = costing.calculate({**inputs, 'labor_minutes': '0', 'labor_rate': None}, 16)
    assert no_labor['production_cost'] == '5.50'
    free = costing.calculate({**inputs, 'retail_price': '0'}, 16)
    assert free['channels'][0]['production_profit'] == '-6.00' and free['channels'][0]['production_margin'] is None
    for key, value in [('yield_pct', '0'), ('yield_pct', '101'), ('fee_pct', '101'), ('wholesale_fee_pct', '101'), ('green_cost_per_lb', 'NaN'), ('retail_price', 'Infinity'), ('bag_cost', '-.01'), ('label_cost', True)]:
        reject(lambda key=key, value=value: costing.calculate({**inputs, key: value}, 16))
    for quantity in [0, -1, 100001, True, 1.5]:
        reject(lambda quantity=quantity: costing.calculate(inputs, 16, quantity))

    with transaction.atomic():
        unchanged = {model.__name__: list(model.objects.order_by('pk').values()) for model in [Batch, ImportOrder, Shift, GreenMovement]}
        coffee = Coffee.objects.get(name='Demo Hearth')
        data = post(ticket=costing.ticket(user), action='profile', name='=Fictional cost profile', coffee=coffee.pk,
                    roast_level='Medium', size_oz=16, currency='USD', active='on', change_note='Synthetic reviewed assumptions', **inputs)
        profile = costing.save_profile(data, user)
        assert costing.save_profile(data, user).pk == profile.pk and CostProfile.objects.filter(pk=profile.pk).count() == 1
        altered = data.copy(); altered['retail_price'] = '99'
        reject(lambda: costing.save_profile(altered, user))
        invalid = data.copy(); invalid['ticket'] = costing.ticket(user); invalid['name'] = 'Invalid cost'; invalid['yield_pct'] = 'NaN'
        reject(lambda: costing.save_profile(invalid, user))
        response = client.get('/costing/' + str(profile.pk) + '/')
        assert response.status_code == 200 and b'6.00' in response.content and b'3.40' in response.content, (response.status_code, response.context and response.context.get('error'), costing.estimate(profile))
        payload = costing.estimate(profile, quantity=3)
        stamp = costing.ticket(user, profile, action='estimate', preview=payload['fingerprint'], batch=None, quantity=3)
        saved_post = post(action='estimate', ticket=stamp)
        saved = costing.save_estimate(saved_post, user, profile.pk)
        assert costing.save_estimate(saved_post, user, profile.pk).pk == saved.pk
        frozen = copy.deepcopy(saved.payload)
        assert client.get('/costing/estimates/' + str(saved.pk) + '/').status_code == 200
        response = client.get('/costing/estimates/' + str(saved.pk) + '/export/')
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        assert rows[1][1].startswith("'=Fictional") and 'no-store' in response['Cache-Control']
        reject(lambda: saved.save())
        stale = post(ticket=costing.ticket(user, profile), action='profile', name=profile.name, coffee=coffee.pk,
                     roast_level='Medium', size_oz=16, currency='USD', active='on', change_note='Corrected assumptions', **{**inputs, 'retail_price': '11'})
        profile = costing.save_profile(stale, user, profile.pk)
        saved.refresh_from_db(); assert saved.payload == frozen
        new_request = post(action='estimate', ticket=costing.ticket(user, CostProfile(pk=profile.pk, version=profile.version-1), action='estimate', preview=payload['fingerprint'], quantity=3))
        reject(lambda: costing.save_estimate(new_request, user, profile.pk))
        stale_form = stale.copy(); stale_form['ticket'] = costing.ticket(user, CostProfile(pk=profile.pk, version=0))
        reject(lambda: costing.save_profile(stale_form, user, profile.pk))

        # Receipt basis uses the latest eligible receipt, preserving missing cost/currency.
        item = GreenBeanItem.objects.create(name='Fictional cost origin', remaining_oz=0, recorded_by=user)
        movement = GreenMovement.objects.create(item=item, actor=user, action='receipt', delta_oz=160, before_oz=0, after_oz=160)
        receipt = GreenPurchase.objects.create(item=item, bean_name=item.name, quantity_oz=160, total_cost=40, currency='USD', received_on=timezone.localdate(), receipt=movement, created_by=user)
        older_movement = GreenMovement.objects.create(item=item, actor=user, action='receipt', delta_oz=160, before_oz=0, after_oz=160)
        GreenPurchase.objects.create(item=item, bean_name=item.name, quantity_oz=160, total_cost=20, currency='USD', received_on=timezone.localdate()-timedelta(days=1), receipt=older_movement, created_by=user)
        recipe = GreenRecipe.objects.create(coffee=coffee, components=[{'item': item.pk, 'percent': '100'}], updated_by=user)
        profile.parameters = {**profile.parameters, 'green_cost_per_lb': None}; profile.save()
        by_receipt = costing.estimate(profile)
        assert by_receipt['result']['production_cost'] == '6.00' and by_receipt['green_sources'][0]['purchase_id'] == receipt.pk
        stamp = costing.ticket(user, profile, action='estimate', preview=by_receipt['fingerprint'], quantity=1)
        receipt.total_cost = 50; receipt.version += 1; receipt.save()
        reject(lambda: costing.save_estimate(post(action='estimate', ticket=stamp), user, profile.pk))
        receipt.total_cost = None; receipt.save()
        assert costing.estimate(profile)['result']['production_cost'] is None
        receipt.total_cost = 40; receipt.currency = 'EUR'; receipt.save()
        assert costing.estimate(profile)['result']['production_cost'] is None
        receipt.currency = 'USD'; receipt.save()
        # Blend pricing weights the green ingredients, without consuming them.
        other = GreenBeanItem.objects.create(name='Fictional second cost origin', remaining_oz=0, recorded_by=user)
        other_movement = GreenMovement.objects.create(item=other, actor=user, action='receipt', delta_oz=160, before_oz=0, after_oz=160)
        GreenPurchase.objects.create(item=other, bean_name=other.name, quantity_oz=160, total_cost=80, currency='USD', received_on=timezone.localdate(), receipt=other_movement, created_by=user)
        recipe.components = [{'item': item.pk, 'percent': '25'}, {'item': other.pk, 'percent': '75'}]; recipe.save()
        assert costing.estimate(profile)['inputs']['green_cost_per_lb'] == '7'
        recipe.components = [{'item': item.pk, 'percent': '100'}]; recipe.save()
        # Actual yield and saved measured ingredients are used; missing history is not invented.
        roaster = Roaster.objects.get(name='Demo Small')
        batch = Batch.objects.create(date=timezone.localdate(), operator=user, coffee=coffee, roaster=roaster, roast_level='Medium', green_oz=20, roasted_oz=16, roasted_at=timezone.now())
        item.refresh_from_db(); stock_after_physical_roast = item.remaining_oz
        assert costing.estimate(profile, batch)['result']['yield_pct'] == '80'
        assert costing.estimate(profile, batch)['green_sources']
        GreenBatchUsage.objects.filter(batch=batch).delete()
        assert costing.estimate(profile, batch)['result']['production_cost'] is None
        GreenBatchUsage.objects.create(batch=batch, percentages={str(item.pk): '100'}, amounts={str(item.pk): '20'})
        assert costing.estimate(profile, batch)['result']['production_cost'] == '6.00'

        # Price imports are read-only and retain exact variant/currency/tax provenance.
        connection, _ = ShopifyConnection.objects.get_or_create(pk=1, defaults={'updated_by': user, 'shop_domain': 'fictional-costs.myshopify.com', 'client_id': 'synthetic-client'})
        connection.shop_domain = 'fictional-costs.myshopify.com'; connection.access_token_cipher = encrypt('synthetic-only'); connection.save()
        catalog, _ = ShopifyCatalog.objects.get_or_create(pk=1)
        product = {'id': 'gid://shopify/Product/901', 'title': 'Demo Hearth', 'status': 'ACTIVE', 'productType': 'Coffee', 'description': '', 'onlineStoreUrl': None,
                   'variants': {'nodes': [{'id': 'gid://shopify/ProductVariant/902', 'title': 'Whole bean / 16 oz', 'sku': 'fictional-16', 'price': '12.00', 'selectedOptions': []}], 'pageInfo': {'hasNextPage': False, 'endCursor': None}}}
        response = {'shop': {'currencyCode': 'USD', 'taxesIncluded': False}, 'products': {'nodes': [product], 'pageInfo': {'hasNextPage': False, 'endCursor': None}}}
        with patch.object(product_checks.api, 'graphql', return_value=response) as api:
            assert product_checks.refresh_catalog(user) == 1
            assert 'price' in api.call_args.args[1] and 'taxesIncluded' in api.call_args.args[1] and api.call_args.args[1].startswith('query ')
        catalog.refresh_from_db(); before_products = copy.deepcopy(catalog.products)
        bad_response = copy.deepcopy(response); bad_response['products']['nodes'][0]['variants']['nodes'][0]['price'] = 'NaN'
        with patch.object(product_checks.api, 'graphql', return_value=bad_response):
            reject(lambda: product_checks.refresh_catalog(user))
        catalog.refresh_from_db(); assert catalog.products == before_products
        profile.parameters.update(retail_from_shopify=True, shopify_variant='gid://shopify/ProductVariant/902', shopify_domain=connection.shop_domain); profile.save()
        linked = costing.estimate(profile)
        assert linked['result']['channels'][0]['price'] == '12.00' and linked['price_source']['kind'] == 'shopify_catalog'
        frozen_link = costing.save_estimate(post(action='estimate', ticket=costing.ticket(user, profile, action='estimate', preview=linked['fingerprint'], quantity=1)), user, profile.pk)
        catalog.products[0]['variants'][0]['price'] = '20.00'; catalog.save()
        frozen_link.refresh_from_db(); assert frozen_link.payload['result']['channels'][0]['price'] == '12.00'
        catalog.products[0]['variants'][0]['taxesIncluded'] = True; catalog.save()
        assert costing.estimate(profile)['result']['channels'][0]['price'] is None
        catalog.products[0]['variants'][0]['taxesIncluded'] = False; catalog.products[0]['variants'][0]['currency'] = 'EUR'; catalog.save()
        assert costing.estimate(profile)['result']['channels'][0]['price'] is None
        profile.parameters['retail_from_shopify'] = False; profile.save()

        outsider = get_user_model().objects.create_user('costing-nonstaff', password='Synthetic-costing-test-password', is_staff=False)
        limited = Client(HTTP_HOST='localhost'); limited.force_login(outsider)
        paths = ['/costing/', '/costing/new/', '/costing/' + str(profile.pk) + '/', '/costing/estimates/' + str(saved.pk) + '/', '/costing/estimates/' + str(saved.pk) + '/export/']
        for path in paths:
            assert limited.get(path).status_code == 302 and Client(HTTP_HOST='localhost').get(path).status_code == 302
            assert client.get(path).status_code == 200
        csrf = Client(HTTP_HOST='localhost', enforce_csrf_checks=True); csrf.force_login(user)
        assert csrf.post('/costing/' + str(profile.pk) + '/', {'action': 'estimate', 'ticket': 'bad'}).status_code == 403
        with override_settings(PORTAL_DEMO_MODE=True):
            assert client.get('/costing/').status_code == 200 and limited.get('/costing/').status_code == 302
        fixtures = root/'costing-fixtures'; fixtures.mkdir(exist_ok=True)
        for name, path in [('dashboard', '/costing/'), ('profile', '/costing/' + str(profile.pk) + '/'), ('snapshot', '/costing/estimates/' + str(saved.pk) + '/')]:
            (fixtures/(name + '.html')).write_bytes(client.get(path).content)
        # Remove only these synthetic physical fixtures before checking preserved originals.
        GreenBatchUsage.objects.filter(batch=batch).delete()
        GreenMovement.objects.filter(batch=batch).delete()
        batch.delete()
        for model in [ImportOrder, Shift]:
            assert list(model.objects.order_by('pk').values()) == unchanged[model.__name__]
        item.refresh_from_db(); other.refresh_from_db()
        assert item.remaining_oz == stock_after_physical_roast and other.remaining_oz == 0
        assert saved.payload == frozen
        from django.core.management import call_command
        from django.core.management.base import CommandError
        try:
            call_command('portal_demo_costs', owner=user.username, stdout=io.StringIO())
        except CommandError:
            pass
        else:
            raise AssertionError('Fictional costs seeded outside confined demo mode')
        with override_settings(PORTAL_DEMO_MODE=True):
            call_command('portal_demo_costs', owner=user.username, stdout=io.StringIO())
            count = CostProfile.objects.count()
            call_command('portal_demo_costs', owner=user.username, stdout=io.StringIO())
            assert CostProfile.objects.count() == count
        transaction.set_rollback(True)
    print('PASS: independent costing arithmetic, unknowns, source/currency/tax and stale-review guards, immutable estimates, CSV, staff/CSRF and no inventory/payroll writes.')
