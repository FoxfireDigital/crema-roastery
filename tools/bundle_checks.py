"""Coffee boxes preserve sold quantities and individual production/label needs."""
import copy,json
from decimal import Decimal
from django.core.exceptions import ValidationError
from portal.models import Coffee,LabelVariant,ProductBundle,ProductBundleItem,ImportOrder
from portal.order_import import infer_item,expand_frac_line,source_signature,readiness
from portal.product_bundles import bundle_source_grind


def run_bundle_checks(client,owner):
    coffees=[Coffee.objects.create(name='Box sample '+str(i),standard_roast=roast) for i,roast in enumerate(['Light/Medium','Medium','Dark','French'])]
    bundle=ProductBundle.objects.create(name='Seasonal sample box',source_title='Seasonal Coffee Box',active=True,updated_by=owner)
    parts=[]
    for coffee in coffees:
        label=LabelVariant.objects.create(name='Box art '+coffee.name,coffee=coffee)
        parts.append(ProductBundleItem.objects.create(bundle=bundle,coffee=coffee,label_variant=label,size_oz=12))
    def line(title='Seasonal Coffee Box',quantity=2):
        value=infer_item(title,quantity)
        value.update(source_line='1',line_key='1',source_total=None,fulfilled=False)
        return value
    original=line();expanded=expand_frac_line(original)
    assert len(expanded)==4 and {x['quantity'] for x in expanded}=={2}
    assert {x['size_oz'] for x in expanded}=={'12.00'}
    assert sum(Decimal(x['size_oz'])*x['quantity'] for x in expanded)==96
    assert {x['source_total'] for x in expanded}=={'96.00'} and {x['grind'] for x in expanded}=={'whole'}
    assert len({x['line_key'] for x in expanded})==4 and len({x['label_variant'] for x in expanded})==4
    assert source_signature(expanded,'')==source_signature([original],'')
    from django.utils import timezone
    from portal.shopify_client import normalize_order
    from portal.shopify import stage_orders
    from portal.allocations import source_groups,save_allocations,review_token
    from portal.models import OrderReviewEvent
    node={'legacyResourceId':'880011','name':'BOX-TEST','createdAt':timezone.now().isoformat(),
          'displayFinancialStatus':'PAID','displayFulfillmentStatus':'UNFULFILLED',
          'all_lines':[{'id':'gid://shopify/LineItem/880011','name':'Seasonal Coffee Box','currentQuantity':2,'unfulfilledQuantity':2,'customAttributes':[]}]}
    normalized=normalize_order(node);stage_orders([normalized])
    order=ImportOrder.objects.get(external_id='880011')
    groups=source_groups(order);assert len(groups)==4 and {g['expected_oz'] for g in groups}=={'24.00'}
    payload=[{**g['allocations'][0],'grind':'regular','remember':True} for g in groups]
    save_allocations(order,payload,review_token(order),owner)
    saved=copy.deepcopy(order.lines)
    assert len(saved)==4 and {x['grind'] for x in saved}=={'regular'} and len({x['line_key'] for x in saved})==4
    stage_orders([normalize_order(node)]);order.refresh_from_db()
    assert order.lines==saved and not order.source_changed and readiness(order)[0]
    wrong=copy.deepcopy(payload);wrong[0]['bag_size_oz']='8'
    try:save_allocations(order,wrong,review_token(order),owner)
    except ValidationError:pass
    else:raise AssertionError('Box composition altered in allocation review')
    node['all_lines'][0].update(currentQuantity=3,unfulfilledQuantity=3)
    stage_orders([normalize_order(node)]);order.refresh_from_db()
    assert order.source_changed and order.lines==saved and sum(x['quantity'] for x in order.latest_lines)==12
    OrderReviewEvent.objects.filter(order=order).delete();order.delete()
    assert expand_frac_line(line('Seasonal Coffee Box - Regular'))[0]['grind']=='regular'
    value=line();bundle_source_grind(value,[{'key':'Grind','value':'Ground'}])
    assert {x['grind'] for x in expand_frac_line(value)}=={'ground'}
    value=line('Seasonal Coffee Box - Whole bean');bundle_source_grind(value,[{'key':'Grind','value':'Ground'}])
    assert {x['grind'] for x in expand_frac_line(value)}=={'unknown'} and value['bundle_grind_explicit']
    assert len(expand_frac_line(line('Other Coffee Box')))==1
    bundle.sku='ONLY-THIS';bundle.save()
    assert len(expand_frac_line(line()))==1
    value=line();value['sku']='ONLY-THIS';assert len(expand_frac_line(value))==4
    bundle.sku='';bundle.save()
    parts[0].bags=2;parts[0].save()
    more=expand_frac_line(line())
    assert [x['quantity'] for x in more]==[4,2,2,2] and {x['source_total'] for x in more}=={'120.00'}
    assert source_signature(more,'')==source_signature([line()],'')
    from portal.stores import mapped_lines
    # Normal single-product remember mappings must not collapse a box's rows.
    from portal.models import StoreConnection,StoreProductMapping
    import uuid
    store=StoreConnection.objects.create(name='Box mapping check',platform='csv',updated_by=owner)
    StoreProductMapping.objects.create(store=store,product_key='same',title='Seasonal Coffee Box',coffee=coffees[0],size_oz=16,updated_by=owner)
    for item in more:item['store_product_key']='same'
    assert [x['coffee'] for x in mapped_lines(store,more)]==[x['coffee'] for x in more]
    from django.test import override_settings
    with override_settings(STORAGES={'default':{'BACKEND':'django.core.files.storage.InMemoryStorage'},'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}}):
        assert client.get('/admin/portal/productbundle/').status_code==200
    # A temporarily unusable component must stop refresh, never drop a coffee.
    coffees[0].active=False;coffees[0].save()
    try:expand_frac_line(line())
    except ValidationError:pass
    else:raise AssertionError('Inactive box coffee silently accepted')
    bundle.delete();StoreProductMapping.objects.filter(store=store).delete();store.delete()
    LabelVariant.objects.filter(name__startswith='Box art ').delete()
    Coffee.objects.filter(pk__in=[c.pk for c in coffees]).delete()
    print('PASS: configured boxes, exact bag/weight multiplication, separate labels/roasts, source quantity identity, grind choices/conflicts, SKU boundaries and inactive-component holds.')
