"""Exact-number diagnosis and explicit, repeat-safe Shopify recovery."""
import re
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render,redirect
from django.views.decorators.http import require_http_methods
from .models import ImportOrder,ShopifyConnection,OrderLookupEvent
from . import shopify_client as api
from .order_import import readiness

SALT='coffee-order-lookup'


class LookupForm(forms.Form):
    number=forms.CharField(max_length=13,label='Shopify order number',widget=forms.TextInput(attrs={'placeholder':'For example, #2055','inputmode':'numeric','autocomplete':'off'}))
    def clean_number(self):
        value=self.cleaned_data['number'].strip()
        if not re.fullmatch(r'#?[0-9]{1,12}',value):raise ValidationError('Enter the order number, such as 2055 or #2055.')
        return value.lstrip('#')


def fetch_order(connection,number):
    query='query CoffeeExactOrder($filter:String!) { orders(first:10,query:$filter) { nodes { '+api.order_fields(connection.include_customer_names).replace('lineItems(first:20)','lineItems(first:100)')+' } pageInfo { hasNextPage endCursor } } }'
    data=api.graphql(connection,query,{'filter':'status:any name:"'+number+'"'})
    page=data.get('orders') or {};nodes,info=api.connection_nodes(page)
    matches=[n for n in nodes if n.get('name','').lstrip('#')==number]
    if len(matches)>1 or (not matches and page.get('pageInfo',{}).get('hasNextPage')):raise ValidationError('The order search is ambiguous. Review the order number in Shopify.')
    if not matches:return None
    node=matches[0];lines,info=api.connection_nodes(node.get('lineItems'));lines=list(lines);cursors=set()
    for _ in range(100):
        if not info['hasNextPage']:break
        cursor=info['endCursor']
        if cursor in cursors:raise ValidationError('Shopify line pagination stopped. No order was recovered.')
        cursors.add(cursor)
        extra=api.graphql(connection,'query CoffeeExactOrderLines($id:ID!,$after:String!) { order(id:$id) { lineItems(first:100,after:$after) { nodes { '+api.LINE_FIELDS+' } pageInfo { hasNextPage endCursor } } } }',{'id':node['id'],'after':cursor})
        more,info=api.connection_nodes((extra.get('order') or {}).get('lineItems'));lines.extend(more)
    else:raise ValidationError('This order has too many line-item pages to recover safely.')
    identities=[line.get('id') for line in lines]
    if any(not isinstance(i,str) or not i.startswith('gid://shopify/LineItem/') for i in identities) or len(set(identities))!=len(identities):raise ValidationError('Shopify returned invalid line items. No order was recovered.')
    node['all_lines']=lines
    try:normalized=api.normalize_order(node)
    except (KeyError,TypeError,ValueError,ArithmeticError):raise ValidationError('Shopify returned incomplete order details. No order was recovered.')
    if not normalized['external_id'].isdigit():raise ValidationError('Shopify did not return a valid order identity.')
    return normalized


def local_status(order):
    ready,reason=readiness(order);plan=order.imported_plan
    url='/imports/'+str(order.pk)+'/review/';button='Review items'
    if plan and order.imported_at:
        if plan.closed_at:reason=f'In closed plan #{plan.pk}';url=f'/plans/{plan.pk}/completed/';button='View completed plan'
        elif plan.historical:url=f'/plans/{plan.pk}/history/';button='View past plan'
        elif plan.removed_at:url=f'/plans/{plan.pk}/restore/';button='Review deleted plan'
        else:url='/planning/?plan='+str(plan.pk);button='Open roast plan'
    elif order.dismissed_at:url='/imports/?dismissed=1';button='Open dismissed orders'
    return {'order':order,'ready':ready,'reason':reason,'url':url,'button':button}


@staff_member_required
@require_http_methods(['GET','POST'])
def lookup_order(request):
    form=LookupForm(request.POST if request.method=='POST' else request.GET or None)
    remote=None;local=[];token='';notice='';error='';status=200
    if form.is_bound and form.is_valid():
        number=form.cleaned_data['number']
        local=list(ImportOrder.objects.filter(reference__in=[number,'#'+number]).select_related('imported_plan'))
        try:
            connection=ShopifyConnection.objects.get(pk=1)
            if not connection.connected_at:raise ValidationError('Connect Shopify before searching live orders. Stored records are shown below.')
            version=connection.version;domain=connection.shop_domain
            remote=fetch_order(connection,number)
            connection.refresh_from_db()
            if connection.version!=version or connection.shop_domain!=domain:raise ValidationError('The Shopify connection changed. Search again before recovering an order.')
            if remote:
                exact=ImportOrder.objects.filter(external_id=remote['external_id']).select_related('imported_plan').first()
                if exact:local=[exact]
                elif local:notice='A stored order shares this number but has a different Shopify identity. Review the records before recovering anything.'
                else:token=signing.dumps({'user':request.user.pk,'number':number,'version':version,'shop':domain,'id':remote['external_id'],'signature':remote['api_signature']},salt=SALT)
            else:notice='Shopify did not return this order. Check its number and store; this connection normally reads the recent 60-day window. Older stored or CSV records may still appear below.'
            if request.method=='POST':
                if request.POST.get('action')!='recover':raise ValidationError('Choose Recover to import list.')
                try:packet=signing.loads(request.POST.get('recovery_token',''),salt=SALT,max_age=20*60)
                except signing.BadSignature:raise ValidationError('This recovery preview expired. Search for the order again.')
                if not remote or any(packet.get(k)!=v for k,v in {'user':request.user.pk,'number':number,'version':version,'shop':domain,'id':remote['external_id'],'signature':remote['api_signature']}.items()):
                    raise ValidationError('The order or connection changed. Review a fresh search before recovering it.')
                with transaction.atomic():
                    current=ShopifyConnection.objects.select_for_update().get(pk=1)
                    if current.version!=version or current.shop_domain!=domain:raise ValidationError('Shopify connection changed. Search again.')
                    existing=ImportOrder.objects.filter(external_id=remote['external_id']).first()
                    if not existing:
                        if ImportOrder.objects.filter(reference__in=[number,'#'+number]).exists():raise ValidationError('Another stored order uses this number. Review it before recovering anything.')
                        from .shopify import stage_orders
                        stage_orders([remote]);existing=ImportOrder.objects.get(external_id=remote['external_id'])
                        OrderLookupEvent.objects.create(order=existing,actor=request.user)
                        messages.success(request,'Order recovered to the import list. Review its status and select it before adding it to a plan.')
                    else:messages.info(request,'This order is already stored. No duplicate or plan change was made.')
                return redirect('/imports/find/?number='+number)
        except ShopifyConnection.DoesNotExist:error='Set up the Shopify connection before searching live orders.'
        except ValidationError as exc:error='; '.join(exc.messages);status=400 if request.method=='POST' else 200
    elif request.method=='POST':status=400
    return render(request,'portal/order_lookup.html',{'form':form,'remote':remote,'local_rows':[local_status(o) for o in local],'recovery_token':token,'notice':notice,'error':error},status=status)
