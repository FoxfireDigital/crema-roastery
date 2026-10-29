"""Signed notifications trigger read-only staging, with polling reconciliation."""
from datetime import timedelta
import base64,hashlib,hmac,uuid
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import ShopifyConnection,ShopifyAutoState,ShopifyWebhookEvent
from . import shopify_client as api

from django.conf import settings
URI=settings.PORTAL_BASE_URL+'/shopify/events/'
TOPICS={'orders/create':'ORDERS_CREATE','orders/updated':'ORDERS_UPDATED','orders/cancelled':'ORDERS_CANCELLED'}
CREATE='mutation CoffeeWebhookCreate($topic:WebhookSubscriptionTopic!,$input:WebhookSubscriptionInput!) { webhookSubscriptionCreate(topic:$topic,webhookSubscription:$input) { webhookSubscription { id topic uri } userErrors { field message } } }'


@csrf_exempt
@require_POST
def receive_event(request):
    connection=ShopifyConnection.objects.filter(pk=1,connected_at__isnull=False).first()
    if not connection or not connection.client_secret_cipher:return HttpResponse(status=503)
    if request.headers.get('X-Shopify-Shop-Domain')!=connection.shop_domain:return HttpResponse(status=403)
    topic=request.headers.get('X-Shopify-Topic','')
    if topic not in TOPICS:return HttpResponse(status=400)
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0)>2*1024*1024:return HttpResponse(status=413)
        body=request.body
        if len(body)>2*1024*1024:return HttpResponse(status=413)
        identity=str(uuid.UUID(request.headers.get('X-Shopify-Webhook-Id','')))
        supplied=request.headers.get('X-Shopify-Hmac-Sha256','')
        expected=base64.b64encode(hmac.new(api.decrypt(connection.client_secret_cipher).encode(),body,hashlib.sha256).digest()).decode()
        if not hmac.compare_digest(supplied,expected):return HttpResponse(status=401)
    except (ValueError,TypeError,ValidationError):return HttpResponse(status=400)
    key=hashlib.sha256((connection.shop_domain+':'+identity).encode()).hexdigest()
    ShopifyWebhookEvent.objects.get_or_create(delivery_key=key,defaults={'shop_domain':connection.shop_domain,'topic':topic,'connection_version':connection.version})
    return HttpResponse(status=200)


def register_notifications(connection):
    identity=(connection.shop_domain,connection.client_id,connection.version)
    data=api.graphql(connection,'query CoffeeWebhookSubscriptions { webhookSubscriptions(first:100) { nodes { id topic uri } pageInfo { hasNextPage } } }')
    page=data.get('webhookSubscriptions') or {}
    if not isinstance(page.get('nodes'),list) or page.get('pageInfo',{}).get('hasNextPage') is not False:raise ValidationError('Notification registration needs review. Five-minute checks remain available.')
    present={row['topic'] for row in page['nodes'] if row.get('uri')==URI}
    connection.refresh_from_db()
    if identity!=(connection.shop_domain,connection.client_id,connection.version):raise ValidationError('Shopify connection changed. Notifications will be checked again.')
    for topic in TOPICS.values():
        if topic in present:continue
        result=api.request_json(connection.shop_domain,'/admin/api/'+api.API_VERSION+'/graphql.json',{'query':CREATE,'variables':{'topic':topic,'input':{'uri':URI,'includeFields':['id']}}},api.decrypt(connection.access_token_cipher))
        payload=(result.get('data') or {}).get('webhookSubscriptionCreate') or {}
        saved=payload.get('webhookSubscription') or {}
        if result.get('errors') or payload.get('userErrors') or saved.get('topic')!=topic or saved.get('uri')!=URI:
            raise ValidationError('Shopify notifications could not be registered. Five-minute checks remain active; review app permissions.')
        present.add(topic)
    return sorted(present & set(TOPICS.values()))


def automatic_status():
    state=ShopifyAutoState.objects.filter(pk=1).first()
    if not state:return {'enabled':False,'healthy':False}
    connection_version=ShopifyConnection.objects.filter(pk=1).values_list('version',flat=True).first()
    return {'enabled':state.enabled,'healthy':bool(state.heartbeat_at and state.heartbeat_at>timezone.now()-timedelta(minutes=4)),
            'last_success_at':state.last_success_at,'last_error':state.last_error,'registration_error':state.registration_error,
            'registered':len(state.registered_topics)==3 and state.registered_version==connection_version,'heartbeat_at':state.heartbeat_at}


def tick():
    now=timezone.now();key=uuid.uuid4()
    with transaction.atomic():
        state,_=ShopifyAutoState.objects.select_for_update().get_or_create(pk=1)
        state.heartbeat_at=now
        if not state.enabled or state.lease_at and state.lease_at>now-timedelta(minutes=10):state.save(update_fields=['heartbeat_at']);return 'paused or busy'
        connection=ShopifyConnection.objects.filter(pk=1,connected_at__isnull=False).first()
        if not connection:state.last_error='Connect Shopify to enable automatic checks.';state.save(update_fields=['heartbeat_at','last_error']);return 'not connected'
        pending=ShopifyWebhookEvent.objects.filter(shop_domain=connection.shop_domain,connection_version=connection.version,processed_at__isnull=True).exists()
        due=pending or bool(connection.sync_cursor) or not state.last_success_at or state.last_success_at<=now-timedelta(minutes=5)
        registration=state.registered_version!=connection.version or not state.registered_at or state.registered_at<=now-timedelta(days=1)
        if not due and not registration:state.save(update_fields=['heartbeat_at']);return 'current'
        state.lease_key=key;state.lease_at=now;state.last_attempt_at=now;state.save()
    try:
        if registration:
            try:
                topics=register_notifications(connection)
                ShopifyAutoState.objects.filter(pk=1,lease_key=key).update(registered_topics=topics,registered_at=now,registered_version=connection.version,registration_error='')
            except ValidationError as error:
                ShopifyAutoState.objects.filter(pk=1,lease_key=key).update(registration_error='; '.join(error.messages)[:300],registered_at=now,registered_version=connection.version,registered_topics=[])
        if due:
            from .shopify import sync_orders
            count,more=sync_orders(connection.updated_by)
            if not more:
                ShopifyWebhookEvent.objects.filter(shop_domain=connection.shop_domain,connection_version=connection.version,received_at__lte=now,processed_at__isnull=True).update(processed_at=timezone.now())
                ShopifyAutoState.objects.filter(pk=1,lease_key=key).update(last_success_at=timezone.now())
            ShopifyAutoState.objects.filter(pk=1,lease_key=key).update(last_error='')
            return f'checked {count} orders'+(' (continuing)' if more else '')
        return 'notifications checked'
    except Exception:
        ShopifyAutoState.objects.filter(pk=1,lease_key=key).update(last_error='Automatic refresh stopped. Reviewed orders and production were preserved; the next check will retry.')
        return 'refresh needs attention'
    finally:ShopifyAutoState.objects.filter(pk=1,lease_key=key).update(lease_key=None,lease_at=None)


@staff_member_required
@require_POST
def set_automatic(request):
    if request.POST.get('enabled') not in ('yes','no'):return HttpResponse(status=400)
    with transaction.atomic():
        state,_=ShopifyAutoState.objects.select_for_update().get_or_create(pk=1)
        state.enabled=request.POST['enabled']=='yes'
        if state.enabled:state.registered_at=None
        state.save(update_fields=['enabled','registered_at'])
    messages.success(request,'Automatic order checks '+('enabled.' if state.enabled else 'paused.'))
    return redirect('/shopify/')
