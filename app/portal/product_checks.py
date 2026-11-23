"""Read-only catalog snapshots and review flags; never rewrites coffees or orders."""
from collections import Counter
from datetime import timedelta
from decimal import Decimal
import re
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render,redirect
from django.utils import timezone
from . import shopify_client as api
from .models import ShopifyCatalog,ShopifyConnection,Coffee,LabelVariant

VARIANT_FIELDS='id title sku price selectedOptions { name value }'
PRODUCT_FIELDS='id title status productType description onlineStoreUrl variants(first:20) { nodes { '+VARIANT_FIELDS+' } pageInfo { hasNextPage endCursor } }'
OFFERED={'ACTIVE','UNLISTED'}


def catalog_nodes(value):
    try:return api.connection_nodes(value)
    except ValidationError:raise ValidationError('Shopify returned an incomplete catalog page. The previous product check was preserved.')


def fetch_catalog(connection):
    products=[];cursor=None;seen=set();cursors=set();variant_ids=set();currency=None;taxes=None
    for _ in range(100):
        data=api.graphql(connection,'query CoffeeCatalog($after:String) { shop { currencyCode taxesIncluded } products(first:25,after:$after,sortKey:ID) { nodes { '+PRODUCT_FIELDS+' } pageInfo { hasNextPage endCursor } } }',{'after':cursor})
        shop=data.get('shop') or {}
        if shop:
            if not isinstance(shop.get('currencyCode'),str) or not re.fullmatch(r'[A-Z]{3}',shop['currencyCode']) or not isinstance(shop.get('taxesIncluded'),bool):raise ValidationError('Shopify returned an invalid price currency or tax setting. The previous product check was preserved.')
            if currency is not None and (currency!=shop['currencyCode'] or taxes!=shop['taxesIncluded']):raise ValidationError('Shopify currency or tax settings changed during the check. Refresh again.')
            currency=shop['currencyCode'];taxes=shop['taxesIncluded']
        nodes,info=catalog_nodes(data.get('products'))
        for node in nodes:
            if not isinstance(node.get('id'),str) or not node['id'].startswith('gid://shopify/Product/') or node['id'] in seen or not isinstance(node.get('title'),str) or not node['title'].strip() or node.get('status') not in OFFERED|{'DRAFT','ARCHIVED'} or 'onlineStoreUrl' not in node:
                raise ValidationError('Shopify returned invalid or duplicate products. The previous product check was preserved.')
            seen.add(node['id']);variants,vinfo=catalog_nodes(node.get('variants'));variants=list(variants);vcursors=set()
            for _ in range(25):
                if not vinfo['hasNextPage']:break
                after=vinfo.get('endCursor')
                if after in vcursors:raise ValidationError('Shopify variant pagination stalled. The previous product check was preserved.')
                vcursors.add(after)
                extra=api.graphql(connection,'query CoffeeCatalogVariants($id:ID!,$after:String!) { product(id:$id) { variants(first:100,after:$after) { nodes { '+VARIANT_FIELDS+' } pageInfo { hasNextPage endCursor } } } }',{'id':node['id'],'after':after})
                more,vinfo=catalog_nodes((extra.get('product') or {}).get('variants'));variants.extend(more)
            else:raise ValidationError('This product has too many variant pages to check safely.')
            if not variants:raise ValidationError('A product has no readable variants. The previous product check was preserved.')
            for variant in variants:
                if not isinstance(variant.get('id'),str) or not variant['id'].startswith('gid://shopify/ProductVariant/') or variant['id'] in variant_ids or not isinstance(variant.get('title'),str) or not isinstance(variant.get('selectedOptions'),list) or any(not isinstance(opt,dict) or not isinstance(opt.get('name'),str) or not isinstance(opt.get('value'),str) for opt in variant['selectedOptions']):
                    raise ValidationError('Shopify returned invalid or repeated variants. The previous product check was preserved.')
                variant_ids.add(variant['id'])
                if variant.get('price') is not None:
                    price=variant['price']
                    if not isinstance(price,str) or not re.fullmatch(r'\d{1,12}(?:\.\d{1,4})?',price) or currency is None:raise ValidationError('Shopify returned an invalid variant price. The previous product check was preserved.')
                    variant['currency']=currency;variant['taxesIncluded']=taxes
            products.append({key:node.get(key) for key in ['id','title','status','productType','description','onlineStoreUrl']}|{'variants':variants})
        if not info['hasNextPage']:return products
        cursor=info['endCursor']
        if cursor in cursors:raise ValidationError('Shopify product pagination stalled. The previous product check was preserved.')
        cursors.add(cursor)
    raise ValidationError('The catalog is too large for one check. The previous product check was preserved.')


def refresh_catalog(user):
    with transaction.atomic():
        connection=ShopifyConnection.objects.get(pk=1)
        if not connection.access_token_cipher:raise ValidationError('Connect Shopify before checking products.')
        saved=ShopifyCatalog.objects.select_for_update().get(pk=1)
        if saved.checking_started_at and saved.checking_started_at>timezone.now()-timedelta(minutes=10):raise ValidationError('A product check is already running. Wait before refreshing again.')
        saved.checking_started_at=timezone.now();lease=saved.checking_started_at;version=connection.version
        saved.save(update_fields=['checking_started_at'])
    try:
        products=fetch_catalog(connection)
        with transaction.atomic():
            current=ShopifyConnection.objects.select_for_update().get(pk=1)
            saved=ShopifyCatalog.objects.select_for_update().get(pk=1)
            if current.version!=version or saved.checking_started_at!=lease:raise ValidationError('The Shopify connection changed during the product check. Refresh again.')
            saved.products=products;saved.shop_domain=connection.shop_domain;saved.checked_at=timezone.now();saved.checked_by=user
            saved.checking_started_at=None;saved.last_error='';saved.save()
        return len(products)
    except Exception as error:
        message='; '.join(error.messages) if isinstance(error,ValidationError) else 'Product check stopped. The previous successful check was preserved. Try again.'
        ShopifyCatalog.objects.filter(pk=1,checking_started_at=lease).update(checking_started_at=None,last_error=message[:300])
        if not isinstance(error,ValidationError):raise ValidationError(message) from error
        raise


def declared_roast(text):
    text=re.sub(r'[^a-z0-9]+',' ',text.casefold()).strip()
    for pattern,roast in [(r'\bfrench\b','French'),(r'\bvienna\b','Dark'),(r'\bmedium dark\b','Medium/Dark'),(r'\blight (?:to )?medium\b','Light/Medium'),(r'\bfull city\b','Medium'),(r'\bcity\b','Light'),(r'\bdark(?: roast)?\b','Dark'),(r'\bmedium(?: roast)?\b','Medium'),(r'\blight(?: roast)?\b','Light')]:
        if re.search(pattern,text):return roast
    return ''


def product_report(products):
    from .order_import import infer_item,infer_grind,expand_frac_line
    from .label_sheets import find_art
    coffees={c.pk:c for c in Coffee.objects.all()};labels={l.pk:l for l in LabelVariant.objects.all()}
    by_name={c.name.casefold():c for c in coffees.values()};matched={};rows=[]
    skus=Counter(str(v.get('sku') or '').strip().casefold() for p in products if p['status'] in OFFERED for v in p['variants'] if str(v.get('sku') or '').strip())
    for product in products:
        issues=[];variants=[];names=set();offered=product['status'] in OFFERED
        title=product['title'].replace('–','-').replace('—','-')
        for variant in product['variants']:
            text=title+(' - '+variant['title'] if variant['title']!='Default Title' else '')
            item=infer_item(text,1,variant.get('sku') or '',use_saved=True)
            coffee=coffees.get(item['coffee'])
            if not coffee:
                coffee=by_name.get(title.casefold())
                if not coffee and title.casefold()=='colombian':coffee=by_name.get('colombian santa maria')
                if coffee:item.update(coffee=coffee.pk,roast_level=coffee.standard_roast)
            vissues=[];size=Decimal(item['size_oz']) if item.get('size_oz') else None
            sku=str(variant.get('sku') or '').strip()
            if sku and offered and skus[sku.casefold()]>1:vissues.append('SKU is shared by multiple offered variants: '+sku)
            if not sku:vissues.append('SKU missing — matching currently depends on names/options.')
            from .product_bundles import expand_bundle_line
            item['source_line']='1'
            box_parts=expand_bundle_line(item)
            if item['skip']:kind='Excluded non-roasting product'
            elif item['cycle_choice']:kind='Subscription assortment — choose coffees for each paid delivery'
            elif box_parts is not None:
                kind='Coffee box — '+box_parts[0]['bundle_name']
                size=sum(Decimal(part['size_oz'])*part['quantity'] for part in box_parts)
                for part in box_parts:
                    c=coffees[part['coffee']];label=labels.get(part['label_variant'])
                    names.add(c.name);matched.setdefault(c.pk,set()).add(product['status'])
                    art,issue=find_art(c.name,label.name if label else '',Decimal(part['size_oz']),part['roast_level'])
                    if issue:vissues.append(c.name+' '+part['size_oz']+' oz label: '+issue)
            elif re.search(r'\b(?:frac|fraq)\s*(?:packs?|pacs?)\b',title,re.I):
                kind='Four-coffee frac pack';item['source_line']='1'
                for part in expand_frac_line(item):
                    c=coffees.get(part['coffee'])
                    if not c:vissues.append('Frac coffee missing from the active catalog.');continue
                    names.add(c.name);matched.setdefault(c.pk,set()).add(product['status'])
                    art,issue=find_art(c.name,'',Decimal('2.5'),c.standard_roast)
                    if issue:vissues.append(c.name+' 2.5 oz label: '+issue)
                    elif art.get('per_sheet')!=8:vissues.append(c.name+': confirm eight-per-sheet horizontal artwork.')
            elif not coffee:
                kind='Unmapped product';vissues.append('Confirm its local coffee mapping, or exclude it as a non-roasting product when reviewing an order.')
            else:
                kind=coffee.name;names.add(coffee.name);matched.setdefault(coffee.pk,set()).add(product['status'])
                if not coffee.active:vissues.append('Matching coffee is inactive locally.')
                if not size:vissues.append('Confirm bag weight — no unambiguous weight was found.')
                roast_text=' '.join(opt['value'] for opt in variant['selectedOptions'] if 'roast' in opt['name'].casefold())
                # French press is a coarse grind, not a French roast request.
                requested=declared_roast(roast_text)
                if not roast_text and re.search(r'\broast\b',variant['title'],re.I):
                    requested=declared_roast(re.sub(r'\bfrench[ -]*press\b','',variant['title'],flags=re.I))
                custom=coffee.kind=='single_origin' and size and size>=80
                roast=requested if custom and requested else coffee.standard_roast
                if requested and requested!=coffee.standard_roast and not custom:vissues.append('Shopify says '+requested+'; local standard stays '+coffee.standard_roast+'.')
                # Owner-confirmed corrections are flagged even when present only
                # in the storefront description. They never overwrite defaults.
                if coffee.name in ('a decaf coffee','Costa Rica'):
                    described=declared_roast(product.get('description') or '')
                    if described and described!=coffee.standard_roast:vissues.append('Storefront description says '+described+'; confirmed local standard is '+coffee.standard_roast+'.')
                if size:
                    label=labels.get(item.get('label_variant'));art,issue=find_art(coffee.name,label.name if label else '',size,roast)
                    if issue:vissues.append(f'{size:.1f} oz label: '+issue)
                if infer_grind(text)=='unknown':vissues.append('Grind not specified in the product/variant name — confirm on the order.')
            for issue in vissues:
                if issue not in issues:issues.append(issue)
            variants.append({'title':variant['title'],'sku':sku,'size':size,'mapping':kind,'issues':vissues,'price':variant.get('price'),'currency':variant.get('currency'),'taxes_included':variant.get('taxesIncluded')})
        rows.append({'title':product['title'],'status':product['status'],'offered':offered,'published':bool(product.get('onlineStoreUrl')),'names':sorted(names),'variants':variants,'issues':issues,'issue_count':len(issues),'search':' '.join([product['title'],*names,*[v['sku'] for v in variants]]).casefold()})
    gaps=[]
    for coffee in coffees.values():
        if coffee.active and not coffee.experimental and not matched.get(coffee.pk,set())&OFFERED:
            statuses=sorted(matched.get(coffee.pk,set()))
            gaps.append({'coffee':coffee,'status':', '.join(statuses) if statuses else 'No matching Shopify product found'})
    counts=Counter(p['status'] for p in products)
    return {'rows':sorted(rows,key=lambda r:(not r['offered'],not bool(r['issues']),r['title'].casefold())),'gaps':gaps,'active_count':counts['ACTIVE'],'unlisted_count':counts['UNLISTED'],'draft_count':counts['DRAFT'],'archived_count':counts['ARCHIVED'],'issue_count':sum(bool(r['issues']) for r in rows if r['offered']),'product_count':len(products)}


@staff_member_required
def product_checks(request):
    if request.method=='POST':
        try:
            if request.POST.get('action')!='refresh':raise ValidationError('Choose Refresh product checks.')
            count=refresh_catalog(request.user);messages.success(request,f'Checked {count} Shopify products. Review differences below.')
        except (ValidationError,ShopifyConnection.DoesNotExist) as error:messages.error(request,'; '.join(error.messages) if isinstance(error,ValidationError) else 'Connect Shopify before checking products.')
        return redirect('/products/')
    connection=ShopifyConnection.objects.filter(pk=1).first();saved=ShopifyCatalog.objects.filter(pk=1).first()
    current=bool(saved and saved.checked_at and connection and saved.shop_domain==connection.shop_domain)
    report=product_report(saved.products) if current else None
    busy=bool(saved and saved.checking_started_at and saved.checking_started_at>timezone.now()-timedelta(minutes=10))
    return render(request,'portal/product_checks.html',{'catalog':saved,'report':report,'connection':connection,'busy':busy,'current':current})
