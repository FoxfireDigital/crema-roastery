"""Normalize source facts; never interpret a shipment weight as a coffee bag."""
import base64,hashlib,json
from datetime import timezone as dt_timezone
from decimal import Decimal
from urllib.parse import urlencode,urlsplit
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .store_http import request_json
from .order_import import infer_item,expand_frac_line,source_signature
from .shopify_client import normalize_order,connection_nodes,order_fields,LINE_FIELDS,order_window_filter

def text(value,limit=500):
    if not isinstance(value,(str,int)) or isinstance(value,bool):raise ValidationError('The store returned an invalid text field.')
    result=str(value)
    if len(result)>limit:raise ValidationError('A store field exceeds the supported length. Review it at the source.')
    return result

def stamp(value):
    result=parse_datetime(value) if isinstance(value,str) else None
    if not result or timezone.is_naive(result):raise ValidationError('The store returned an invalid timestamp; a timezone is required.')
    return result

def count(value):
    if isinstance(value,bool):raise ValidationError('A store item quantity is invalid.')
    try:
        result=int(value)
        if str(result)!=str(value) or not 1<=result<=100000:raise ValueError()
        return result
    except (ValueError,TypeError):raise ValidationError('A store item quantity is invalid.')

def make_line(identity,title,quantity,sku='',subscription='',variant=''):
    identity=text(identity,250)
    if not identity:raise ValidationError('A store line has no stable identity.')
    item=infer_item(text(title),count(quantity),text(sku or '',150),text(subscription or '',250),use_saved=False)
    key=hashlib.sha256(identity.encode()).hexdigest()[:24]
    item.update(line_key=key,source_line=key,api_line_id=identity,source_total=str(Decimal(item['size_oz'])*item['quantity']) if item['size_oz'] else None,fulfilled=False,
                store_product_key=hashlib.sha256(json.dumps([text(variant or '',250),item['sku'],item['title']],ensure_ascii=True).encode()).hexdigest())
    return item

def finish(identity,reference,created,updated,lines,payment,fulfillment,cancelled=False,notes='',customer='',flags=None):
    identity=text(identity,250)
    if not identity or not lines or len(lines)>1000 or len({l['api_line_id'] for l in lines})!=len(lines):raise ValidationError('An order has missing or repeated line identities.')
    raw=hashlib.sha256(json.dumps({'lines':lines,'instructions':notes},sort_keys=True,default=str,allow_nan=False).encode()).hexdigest()
    expanded=[]
    for line in lines:expanded.extend(expand_frac_line(line))
    prepaid='prepaid' in (' '.join(l.get('selling_plan','') for l in lines)+' '+notes).casefold()
    return {'external_id':identity,'reference':text(reference,100),'received_at':stamp(created),'source_updated_at':stamp(updated or created),'financial_status':payment,
            'fulfillment_status':fulfillment,'cancelled':bool(cancelled),'subscription':'prepaid' if prepaid else 'recurring' if any(l.get('selling_plan') for l in lines) else 'unknown',
            'instructions':text(notes,2000),'customer':text(customer,120),'lines':expanded,'source_signature':source_signature(expanded,notes),'api_signature':raw,'source_flags':flags or []}

def woo(node,names=False):
    lines=[];notes=[node.get('customer_note') or '']
    for line in node['line_items']:
        options=[str(m.get('display_value') or m.get('value') or '') for m in line.get('meta_data',[]) if isinstance(m,dict) and not str(m.get('key','')).startswith('_') and isinstance(m.get('display_value',m.get('value')),(str,int))]
        title=text(line['name'])+(' - '+' / '.join(options) if options else '')
        renewal=any(m.get('key') in ['_subscription_renewal','_subscription_renewal_order'] and m.get('value') for m in node.get('meta_data',[]))
        lines.append(make_line(line['id'],title,line['quantity'],line.get('sku',''),'Subscription renewal' if renewal else '',str(line.get('variation_id') or line.get('product_id') or '')))
    state=node.get('status');paid=bool(node.get('date_paid_gmt')) and state in ['processing','completed']
    payment='refunded' if node.get('refunds') or state=='refunded' else 'paid' if paid else 'unknown'
    created=text(node['date_created_gmt'],50);updated=text(node.get('date_modified_gmt') or node['date_created_gmt'],50)
    address=node.get('billing') or {};customer=' '.join(str(address.get(k) or '') for k in ['first_name','last_name']).strip() if names else ''
    return finish(node['id'],str(node.get('number') or node['id']),created+'Z' if not created.endswith('Z') else created,updated+'Z' if not updated.endswith('Z') else updated,
                  lines,payment,'fulfilled' if state=='completed' else 'unfulfilled' if state=='processing' else 'unknown',state in ['cancelled','trash','failed'],'\n'.join(notes),customer,
                  [] if state in ['processing','completed','cancelled','trash','failed','refunded','pending','on-hold'] else ['Unknown WooCommerce order status — review before production'])

def wix(node,names=False):
    lines=[]
    for line in node['lineItems']:
        options=[]
        for d in line.get('descriptionLines') or []:
            value=d.get('plainText') or {};value=value.get('original') or value.get('translated') or ''
            if value:options.append(text(value,150))
        title=(line.get('productName') or {}).get('original')
        if options:title+=' - '+' / '.join(options)
        sub=line.get('subscriptionInfo') or {};catalog=line.get('catalogReference') or {}
        item=make_line(line.get('id') or line.get('_id'),title,line['quantity'],(line.get('physicalProperties') or {}).get('sku',''),sub.get('subscriptionOptionTitle') or ('Subscription renewal' if sub.get('cycleNumber') else ''),catalog.get('catalogItemId',''))
        lines.append(item)
    address=(node.get('billingInfo') or {}).get('contactDetails') or {};customer=' '.join(str(address.get(k) or '') for k in ['firstName','lastName']).strip() if names else ''
    flags=[]
    if node.get('status')!='APPROVED':flags.append('Order is not approved for production')
    fulfillment={'NOT_FULFILLED':'unfulfilled','FULFILLED':'fulfilled','PARTIALLY_FULFILLED':'partial'}.get(node.get('fulfillmentStatus'),'unknown')
    return finish(node.get('id') or node.get('_id'),node['number'],node.get('createdDate') or node.get('_createdDate'),node.get('updatedDate') or node.get('_updatedDate'),lines,
                  'paid' if node.get('paymentStatus') in ['PAID','FULLY_PAID'] else str(node.get('paymentStatus') or 'unknown').lower(),fulfillment,node.get('status') in ['CANCELED','CANCELLED'],str(node.get('buyerNote') or ''),customer,flags)

def squarespace(node,names=False):
    lines=[];notes=[str(n.get('content') or '') for n in node.get('internalNotes',[])]
    for line in node['lineItems']:
        options=[text(o.get('value') or '',150) for o in line.get('variantOptions') or []]
        title=text(line['productName'])+(' - '+' / '.join(options) if options else '')
        lines.append(make_line(line['id'],title,line['quantity'],line.get('sku',''),str(line.get('subscriptionId') or ''),line.get('variantId') or line.get('productId') or ''))
        notes.extend(text(x.get('label') or '',100)+': '+text(x.get('value') or '',300) for x in line.get('customizations') or [])
    flags=[]
    if node.get('testmode'):flags.append('Test order — excluded from production')
    if node.get('channel')=='pos':flags.append('POS sale — confirm stock handling rather than creating another roast')
    fulfillment={'PENDING':'unfulfilled','FULFILLED':'fulfilled','CANCELED':'unknown'}.get(node.get('fulfillmentStatus'),'unknown')
    if node.get('fulfillments') and fulfillment=='unfulfilled':fulfillment='partial'
    address=node.get('billingAddress') or {};customer=' '.join(str(address.get(k) or '') for k in ['firstName','lastName']).strip() if names else ''
    payment=str(node.get('paymentState') or 'unknown').lower()
    if Decimal(str((node.get('refundedTotal') or {}).get('value','0')))>0:payment='refunded'
    return finish(node['id'],node['orderNumber'],node['createdOn'],node.get('modifiedOn'),lines,payment,fulfillment,node.get('fulfillmentStatus')=='CANCELED','\n'.join(notes),customer,flags)

def iso(value):return value.astimezone(dt_timezone.utc).isoformat().replace('+00:00','Z')

def fetch_page(store,credentials,since,until,cursor):
    """One bounded page; caller commits cursor only with its normalized orders."""
    platform=store.platform
    if platform=='woocommerce':
        page=int(cursor.get('page',1));url=urlsplit(store.origin)
        params={'per_page':50,'page':page,'orderby':'modified','order':'asc','modified_after':iso(since),'modified_before':iso(until),'dates_are_gmt':'true','status':'any'}
        auth=base64.b64encode((credentials['key']+':'+credentials['secret']).encode()).decode()
        raw,headers=request_json(store.origin,url.path.rstrip('/')+'/wp-json/wc/v3/orders?'+urlencode(params),{'Authorization':'Basic '+auth})
        pages=int(headers['x-wp-totalpages']);total=int(headers['x-wp-total'])
        if not isinstance(raw,list) or pages<0 or pages>10000 or total<0 or len(raw)>50 or (page<pages and len(raw)!=50):raise ValidationError('WooCommerce pagination is incomplete. Retry the refresh.')
        return [woo(n,store.include_customer_names) for n in raw],{'page':page+1} if page<pages else {}
    if platform=='wix':
        search={'filter':{'updatedDate':{'$gte':iso(since),'$lte':iso(until)},'status':{'$in':['APPROVED','CANCELED','PENDING','REJECTED']}},'sort':[{'fieldName':'updatedDate','order':'ASC'}],'cursorPaging':{'limit':50}}
        if cursor.get('cursor'):search['cursorPaging']['cursor']=cursor['cursor']
        raw,_=request_json('https://www.wixapis.com','/ecom/v1/orders/search',{'Authorization':credentials['token'],'wix-site-id':store.site_id},{'search':search})
        nodes=raw['orders'];next_cursor=(raw.get('metadata',{}).get('cursors') or {}).get('next')
        if not isinstance(nodes,list) or len(nodes)>50:raise ValidationError('Wix returned an invalid order page.')
        return [wix(n,store.include_customer_names) for n in nodes],{'cursor':text(next_cursor,2000)} if next_cursor else {}
    if platform=='squarespace':
        params={'cursor':cursor['cursor']} if cursor.get('cursor') else {'modifiedAfter':iso(since),'modifiedBefore':iso(until),'paymentStates':'NOT_CHARGED,AUTHORIZED,PAID,PARTIALLY_PAID,PENDING,FAILED,REFUND_PENDING,REFUNDED,REFUND_FAILED'}
        raw,_=request_json('https://api.squarespace.com','/1.0/commerce/orders?'+urlencode(params),{'Authorization':'Bearer '+credentials['token']})
        nodes=raw['result'];info=raw['pagination']
        if not isinstance(nodes,list) or len(nodes)>50 or not isinstance(info.get('hasNextPage'),bool):raise ValidationError('Squarespace returned incomplete pagination.')
        nxt=text(info.get('nextPageCursor') or '',2000)
        if info['hasNextPage'] and not nxt:raise ValidationError('Squarespace pagination stalled.')
        return [squarespace(n,store.include_customer_names) for n in nodes],{'cursor':nxt} if info['hasNextPage'] else {}
    if platform=='shopify':
        headers={'X-Shopify-Access-Token':credentials['token']}
        query='query CremaOrders($after:String,$filter:String!) { orders(first:20,after:$after,sortKey:UPDATED_AT,query:$filter) { nodes { '+order_fields(store.include_customer_names)+' } pageInfo { hasNextPage endCursor } } }'
        def graphql(query,variables):
            raw,_=request_json(store.origin,'/admin/api/2026-10/graphql.json',headers,{'query':query,'variables':variables})
            if raw.get('errors') or not isinstance(raw.get('data'),dict):raise ValidationError('Shopify denied or could not complete the read query. Check read_orders and customer-data permissions.')
            return raw['data']
        data=graphql(query,{'after':cursor.get('cursor'),'filter':order_window_filter(since,until)});nodes,info=connection_nodes(data.get('orders'));result=[]
        for node in nodes:
            line_nodes,li=connection_nodes(node.get('lineItems'));line_nodes=list(line_nodes);seen=set()
            while li['hasNextPage']:
                key=li.get('endCursor')
                if key in seen or len(seen)>=20:raise ValidationError('Shopify line pagination stalled or exceeded its safe limit.')
                seen.add(key);extra=graphql('query CremaLines($id:ID!,$after:String!) { order(id:$id) { lineItems(first:100,after:$after) { nodes { '+LINE_FIELDS+' } pageInfo { hasNextPage endCursor } } } }',{'id':node['id'],'after':key})
                more,li=connection_nodes((extra.get('order') or {}).get('lineItems'));line_nodes.extend(more)
            node['all_lines']=line_nodes
            if not str(node.get('legacyResourceId','')).isdigit() or len({l.get('id') for l in line_nodes})!=len(line_nodes) or any(not isinstance(l.get('id'),str) or not l['id'].startswith('gid://shopify/LineItem/') for l in line_nodes):raise ValidationError('Shopify returned missing or repeated source identities.')
            data=normalize_order(node);data['source_updated_at']=stamp(node['updatedAt']);data['source_flags']=[]
            # Legacy inference can consult global mappings. Connected stores use
            # only their own mappings; reconstruct each original item first.
            clean=[]
            for i,line in enumerate(line_nodes,1):
                quantity=line['currentQuantity'];unfulfilled=line['unfulfilledQuantity']
                if not isinstance(quantity,int) or isinstance(quantity,bool) or not isinstance(unfulfilled,int) or isinstance(unfulfilled,bool) or not 0<=unfulfilled<=quantity<=100000:raise ValidationError('Shopify returned invalid remaining quantities.')
                if quantity==0:continue
                item=make_line(line['id'],line['name'],quantity,line.get('sku',''),(line.get('sellingPlan') or {}).get('name',''))
                item['fulfilled']=unfulfilled==0;clean.extend(expand_frac_line(item))
            data['lines']=clean;data['source_signature']=source_signature(clean,data['instructions']);result.append(data)
        return result,{'cursor':info['endCursor']} if info['hasNextPage'] else {}
    raise ValidationError('This store uses CSV uploads rather than an API refresh.')
