"""Read-only Shopify GraphQL client. Never sends a store-data mutation."""
from datetime import datetime,timedelta,timezone as datetime_timezone
from decimal import Decimal
import base64,hashlib,json,re,time,math
from urllib import request,error,parse
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.db import transaction
from cryptography.fernet import Fernet,InvalidToken

API_VERSION='2026-10'
SHOP_RE=re.compile(r'[a-z0-9][a-z0-9-]*\.myshopify\.com\Z')

def shop_domain(value):
    value=value.strip().lower()
    if value.startswith('https://'):
        try:
            parts=parse.urlsplit(value)
            invalid=parts.path not in ('','/') or parts.query or parts.fragment or parts.username or parts.port
        except ValueError:raise ValidationError('Use the store’s myshopify.com address only.')
        if invalid:raise ValidationError('Use the store’s myshopify.com address only.')
        value=parts.hostname or ''
    if re.fullmatch(r'[a-z0-9][a-z0-9-]*',value):value+='.myshopify.com'
    if not SHOP_RE.fullmatch(value) or len(value)>100:raise ValidationError('Enter the store’s original name.myshopify.com address.')
    return value

def cipher():return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('coffee-shopify-v1:'+settings.SECRET_KEY).encode()).digest()))
def encrypt(value):return cipher().encrypt(value.encode()).decode() if value else ''
def decrypt(value):
    try:return cipher().decrypt(value.encode()).decode() if value else ''
    except (InvalidToken,ValueError):raise ValidationError('The saved Shopify key cannot be read. Re-enter it on the connection page.')

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def retry_delay(result):
    """Wait for Shopify's reported query budget rather than guessing one second."""
    try:
        cost=result['extensions']['cost'];status=cost['throttleStatus']
        requested=float(cost['requestedQueryCost']);available=float(status['currentlyAvailable']);rate=float(status['restoreRate'])
        if not all(math.isfinite(v) for v in [requested,available,rate]) or requested<0 or available<0 or rate<=0:return 1
        seconds=max(1,math.ceil(max(0,requested-available)/rate)+1)
        if seconds>15:raise ValidationError('Shopify needs more time before another refresh. Wait a little, then refresh again; the saved position is retained.')
        return seconds
    except (KeyError,TypeError,ValueError,OverflowError):return 1


def request_json(domain,path,payload,token=None):
    domain=shop_domain(domain)
    if path not in ['/admin/oauth/access_token','/admin/api/'+API_VERSION+'/graphql.json']:raise ValidationError('Unsupported Shopify request.')
    headers={'Content-Type':'application/json','Accept':'application/json','User-Agent':'Crema/1.0'}
    if token:headers['X-Shopify-Access-Token']=token
    body=json.dumps(payload).encode();opener=request.build_opener(NoRedirect())
    for attempt in range(3):
        try:
            with opener.open(request.Request('https://'+domain+path,data=body,headers=headers,method='POST'),timeout=10) as response:
                raw=response.read(8*1024*1024+1)
                if len(raw)>8*1024*1024:raise ValidationError('Shopify returned too much data. Retry a smaller refresh.')
                result=json.loads(raw)
                if not isinstance(result,dict):raise ValidationError('Shopify returned an incomplete response. No reviewed orders were changed.')
                return result
        except error.HTTPError as exc:
            if exc.code in [429,502,503,504] and attempt<2:
                try:delay=float(exc.headers.get('Retry-After') or 1)
                except (TypeError,ValueError):delay=1
                if not math.isfinite(delay) or delay<0:delay=1
                if delay>15:raise ValidationError('Shopify asked for a longer pause. Wait before refreshing again; the saved position is retained.')
                time.sleep(max(1,delay));continue
            if exc.code in [401,403]:raise ValidationError('Shopify access was declined or expired. Reconnect and check the app’s approved permissions.')
            raise ValidationError('Shopify did not accept the request. Check the store address, app setup and approved permissions.')
        except (error.URLError,TimeoutError,OSError,json.JSONDecodeError):
            raise ValidationError('Shopify could not be reached. Existing orders are unchanged; try refreshing again.')
    raise ValidationError('Shopify is busy. Try again shortly.')

def graphql(connection,query,variables=None,token=None):
    if not query.lstrip().startswith('query '):raise ValidationError('Only read-only Shopify queries are permitted.')
    token=token or decrypt(connection.access_token_cipher)
    if not token:raise ValidationError('Connect Shopify before refreshing orders.')
    if connection.auth_mode=='client_credentials' and connection.token_expires_at and connection.token_expires_at<=timezone.now()+timedelta(minutes=5):
        grant=request_json(connection.shop_domain,'/admin/oauth/access_token',{'grant_type':'client_credentials','client_id':connection.client_id,'client_secret':decrypt(connection.client_secret_cipher)})
        save_grant(connection,grant,'client_credentials');token=decrypt(connection.access_token_cipher)
    elif connection.token_expires_at and connection.token_expires_at<=timezone.now()+timedelta(minutes=5):
        if not connection.refresh_token_cipher or connection.refresh_token_expires_at and connection.refresh_token_expires_at<=timezone.now():raise ValidationError('Shopify authorization expired. Reconnect from the connection page.')
        grant=request_json(connection.shop_domain,'/admin/oauth/access_token',{'grant_type':'refresh_token','client_id':connection.client_id,'client_secret':decrypt(connection.client_secret_cipher),'refresh_token':decrypt(connection.refresh_token_cipher)})
        save_grant(connection,grant,'oauth');token=decrypt(connection.access_token_cipher)
    for attempt in range(3):
        result=request_json(connection.shop_domain,'/admin/api/'+API_VERSION+'/graphql.json',{'query':query,'variables':variables or {}},token)
        errors=result.get('errors') or []
        if errors:
            if all(e.get('extensions',{}).get('code')=='THROTTLED' for e in errors) and attempt<2:time.sleep(retry_delay(result));continue
            if 'CoffeeCatalog' in query:raise ValidationError('Shopify could not provide product data. Approve read_products for the installed app and reconnect on the Shopify connection page. The previous product check was preserved.')
            raise ValidationError('Shopify could not provide the requested order data. Check read_orders and customer-name access; no orders were changed.')
        if not isinstance(result.get('data'),dict):raise ValidationError('Shopify returned an incomplete response. No orders were changed.')
        return result['data']

@transaction.atomic
def save_grant(connection,grant,mode):
    current=type(connection).objects.select_for_update().get(pk=connection.pk)
    if current.version!=connection.version:raise ValidationError('App details changed while connecting. Start again from the connection page.')
    if not isinstance(grant.get('access_token'),str) or not grant['access_token']:raise ValidationError('Shopify did not return an access token.')
    scopes=[s.strip() for s in str(grant.get('scope','')).split(',') if s.strip()]
    if not {'read_orders','write_orders'}&set(scopes):raise ValidationError('The app needs read_orders permission before it can connect.')
    try:expiry=int(grant['expires_in']) if grant.get('expires_in') else None
    except (ValueError,TypeError):raise ValidationError('Shopify returned an invalid token expiry.')
    if expiry is not None and not 0<expiry<=31536000:raise ValidationError('Shopify returned an invalid token expiry.')
    if mode=='client_credentials' and not expiry:raise ValidationError('Shopify did not return an expiry for the app token.')
    connection.access_token_cipher=encrypt(grant['access_token']);connection.granted_scopes=scopes;connection.auth_mode=mode
    connection.token_expires_at=timezone.now()+timedelta(seconds=expiry) if expiry else None
    if grant.get('refresh_token'):
        try:refresh_expiry=int(grant['refresh_token_expires_in'])
        except (KeyError,ValueError,TypeError):raise ValidationError('Shopify returned an invalid refresh-token expiry.')
        if not 0<refresh_expiry<=366*86400:raise ValidationError('Shopify returned an invalid refresh-token expiry.')
        connection.refresh_token_cipher=encrypt(grant['refresh_token']);connection.refresh_token_expires_at=timezone.now()+timedelta(seconds=refresh_expiry)
    elif mode=='oauth' and expiry:raise ValidationError('Shopify returned an expiring token without a refresh token. Reconnect the app.')
    else:connection.refresh_token_cipher='';connection.refresh_token_expires_at=None
    connection.connected_at=connection.connected_at or timezone.now();connection.last_error=''
    connection.save(update_fields=['access_token_cipher','refresh_token_cipher','refresh_token_expires_at','granted_scopes','auth_mode','token_expires_at','connected_at','last_error'])

LINE_FIELDS='id name sku quantity currentQuantity unfulfilledQuantity sellingPlan { name } customAttributes { key value }'
def order_fields(names=False):
    return 'id legacyResourceId name createdAt updatedAt cancelledAt displayFinancialStatus displayFulfillmentStatus note customAttributes { key value } tags '+('customer { displayName } ' if names else '')+'lineItems(first:20) { nodes { '+LINE_FIELDS+' } pageInfo { hasNextPage endCursor } }'

def connection_nodes(value):
    if not isinstance(value,dict) or not isinstance(value.get('nodes'),list) or not isinstance(value.get('pageInfo'),dict):raise ValidationError('Shopify returned incomplete order or line-item pages. Retry the refresh; reviewed items were preserved.')
    info=value['pageInfo']
    if not isinstance(info.get('hasNextPage'),bool) or any(not isinstance(node,dict) for node in value['nodes']):raise ValidationError('Shopify returned an incomplete page. Retry the refresh.')
    if info['hasNextPage'] and (not value['nodes'] or not isinstance(info.get('endCursor'),str) or not info['endCursor']):raise ValidationError('Shopify pagination did not advance. Retry the refresh.')
    return value['nodes'],info


def order_window_filter(since,until):
    if not isinstance(since,datetime) or not isinstance(until,datetime) or timezone.is_naive(since) or timezone.is_naive(until) or since>until:
        raise ValidationError('Choose a valid, timezone-aware Shopify refresh window.')
    lower=since.astimezone(datetime_timezone.utc).isoformat().replace('+00:00','Z')
    upper=until.astimezone(datetime_timezone.utc).isoformat().replace('+00:00','Z')
    # Shopify requires quoted date strings. Unquoted ISO times can be parsed as
    # separate search terms and silently return orders outside the window.
    return 'status:any updated_at:>="'+lower+'" updated_at:<="'+upper+'"'


def fetch_batch(connection,since,until,cursor=''):
    query='query CoffeeOrders($after:String,$filter:String!) { orders(first:20,after:$after,sortKey:UPDATED_AT,query:$filter) { nodes { '+order_fields(connection.include_customer_names)+' } pageInfo { hasNextPage endCursor } } }'
    search=order_window_filter(since,until)
    orders=[];more=False;seen=set()
    for page in range(5):
        data=graphql(connection,query,{'after':cursor or None,'filter':search});batch=data.get('orders')
        nodes,batch_info=connection_nodes(batch)
        for order in nodes:
            identity=str(order.get('legacyResourceId') or '')
            if not identity.isdigit() or identity in seen:raise ValidationError('Shopify returned a duplicate or invalid order identity; refresh again.')
            if 'updatedAt' in order:
                stamp=parse_datetime(order['updatedAt']) if isinstance(order['updatedAt'],str) else None
                # Shopify's displayed timestamps can omit fractional seconds.
                if not stamp or timezone.is_naive(stamp) or stamp<since-timedelta(seconds=1) or stamp>until+timedelta(seconds=1):
                    raise ValidationError('Shopify returned orders outside the requested date window. The refresh position was preserved; review the date filter before retrying.')
            seen.add(identity)
            lines=order.get('lineItems');first_nodes,_=connection_nodes(lines);line_nodes=list(first_nodes)
            cursors=set()
            for _ in range(100):
                info=lines.get('pageInfo') or {}
                if not info.get('hasNextPage'):break
                line_cursor=info.get('endCursor')
                if not line_cursor or line_cursor in cursors:raise ValidationError('Shopify line pagination stalled; no orders were changed.')
                cursors.add(line_cursor)
                extra=graphql(connection,'query CoffeeOrderLines($id:ID!,$after:String!) { order(id:$id) { lineItems(first:100,after:$after) { nodes { '+LINE_FIELDS+' } pageInfo { hasNextPage endCursor } } } }',{'id':order['id'],'after':line_cursor})
                lines=(extra.get('order') or {}).get('lineItems');more_nodes,_=connection_nodes(lines);line_nodes.extend(more_nodes)
            else:raise ValidationError('This order has too many line items to refresh safely.')
            if any(not isinstance(l.get('id'),str) or not l['id'].startswith('gid://shopify/LineItem/') for l in line_nodes) or len({l['id'] for l in line_nodes})!=len(line_nodes):raise ValidationError('Shopify returned invalid or repeated line items; no orders were changed.')
            order['all_lines']=line_nodes;orders.append(order)
        info=batch_info;more=info['hasNextPage']
        if not more:cursor='';break
        new_cursor=info.get('endCursor')
        if not new_cursor or new_cursor==cursor:raise ValidationError('Shopify pagination stalled; no orders were changed.')
        cursor=new_cursor
    return orders,cursor,more

def normalize_order(node):
    from .order_import import infer_item,source_signature,expand_frac_line
    external=str(node['legacyResourceId']);received=parse_datetime(node['createdAt'])
    if not received:raise ValidationError('A Shopify order is missing its creation date.')
    lines=[];notes=[node.get('note') or ''];recurring=False
    for attr in node.get('customAttributes') or []:
        if attr.get('value'):notes.append(str(attr.get('key',''))+': '+str(attr['value']))
    for index,line in enumerate(node['all_lines'],1):
        quantity=int(line['currentQuantity'])
        if quantity<=0:continue
        selling=(line.get('sellingPlan') or {}).get('name') or '';recurring=recurring or bool(selling)
        item=infer_item(line['name'],quantity,line.get('sku') or '',selling,use_saved=True)
        item.update(line_key=str(index),source_line=str(index),source_total=str(Decimal(item['size_oz'])*quantity) if item['size_oz'] else None,
                    fulfilled=int(line['unfulfilledQuantity'])==0,api_line_id=line['id'])
        from .product_bundles import bundle_source_grind
        bundle_source_grind(item,line.get('customAttributes'))
        lines.extend(expand_frac_line(item))
        for attr in line.get('customAttributes') or []:
            if attr.get('value'):notes.append(line['name']+' — '+str(attr.get('key',''))+': '+str(attr['value']))
    instructions='\n'.join(n.strip() for n in notes if n.strip())[:2000]
    prepaid='prepaid' in (' '.join(str(t) for t in node.get('tags',[]))+' '+' '.join(l.get('selling_plan','') for l in lines)).lower()
    raw_source=hashlib.sha256(json.dumps({'items':[{k:l.get(k) for k in ['api_line_id','title','sku','quantity','selling_plan','bundle_key']} for l in lines],'instructions':instructions},sort_keys=True).encode()).hexdigest()
    return {'external_id':external,'reference':node['name'],'customer':(node.get('customer') or {}).get('displayName','')[:120],
      'received_at':received,'financial_status':str(node.get('displayFinancialStatus') or '').lower(),
      'fulfillment_status':{'PARTIALLY_FULFILLED':'partial'}.get(node.get('displayFulfillmentStatus'),str(node.get('displayFulfillmentStatus') or '').lower()),
      'cancelled':bool(node.get('cancelledAt')),'subscription':'prepaid' if prepaid else 'recurring' if recurring else 'unknown',
      'lines':lines,'instructions':instructions,'source_signature':source_signature(lines,instructions),'api_signature':raw_source}
