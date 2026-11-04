"""Opt-in device pairing. Browser consent uses sessions/CSRF; API uses only bearer tokens.

No customer, payroll, stock, connection secrets or production-edit capability is exposed.
This is a first-party device protocol, not a general OAuth authorization server.
"""
import copy, functools, json, re, secrets
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse, HttpResponse, Http404
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac, constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .models import CompanionDevice, CompanionGrant, LoginAttemptWindow, PlannedBatch, RoastPlan, ArtisanProfileRevision, ArtisanPreparation
from . import artisan_profiles as profiles

def digest(value):return salted_hmac('crema-companion-v1',value,algorithm='sha256').hexdigest()
def reply(data,status=200):
    response=JsonResponse(data,status=status)
    response['Cache-Control']='private, no-store'
    return response
def error(message,status=400):return reply({'error':message},status)
def enabled():return getattr(settings,'COMPANION_ENABLED',False)
def limited(request,kind,limit):
    key=digest('limit:'+kind+':'+str(request.META.get('REMOTE_ADDR','unknown'))[:128])
    now=timezone.now()
    with transaction.atomic():
        item,_=LoginAttemptWindow.objects.get_or_create(key=key,defaults={'expires_at':now+timedelta(minutes=10)})
        item=LoginAttemptWindow.objects.select_for_update().get(pk=key)
        if item.expires_at<=now:item.attempts=0;item.expires_at=now+timedelta(minutes=10)
        if item.attempts>=limit:return True
        item.attempts+=1;item.save(update_fields=['attempts','expires_at'])
    return False
def body(request):
    if request.content_type!='application/json' or len(request.body)>4096:raise ValueError('Use a small JSON request.')
    value=json.loads(request.body)
    if not isinstance(value,dict):raise ValueError('Use a JSON object.')
    return value
def api(methods=('POST',),authenticated=False):
    def decorate(view):
        @csrf_exempt
        @functools.wraps(view)
        def wrapped(request,*args,**kwargs):
            if not enabled():return error('Companion connections are not enabled on this portal.',404)
            if request.method not in methods:return error('Method not allowed.',405)
            # Native HTTP only. Do not expose a cookie/CORS alternate path.
            if request.headers.get('Origin'):return error('Use the Companion application.',403)
            if not settings.LOCAL_DEVELOPMENT and not request.is_secure():return error('HTTPS is required.',400)
            try:
                if authenticated:
                    auth=request.headers.get('Authorization','')
                    if not re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}',auth):return error('Sign in to Companion again.',401)
                    device=CompanionDevice.objects.select_related('user').filter(access_hash=digest(auth[7:])).first()
                    now=timezone.now()
                    if not device or device.revoked_at or device.access_expires_at<=now or device.refresh_expires_at<=now or not device.user.is_active or not device.user.is_staff or not constant_time_compare(device.auth_fingerprint,digest(device.user.get_session_auth_hash())):return error('Sign in to Companion again.',401)
                    request.companion_device=device;request.user=device.user
                    CompanionDevice.objects.filter(pk=device.pk).update(last_seen_at=now)
                return view(request,*args,**kwargs)
            except (ValueError,TypeError,KeyError,json.JSONDecodeError):return error('Check the request and try again.')
            except ValidationError as exc:return error(' '.join(exc.messages),409)
            except Http404:return error('This roast is no longer available. Refresh the list.',404)
        return wrapped
    return decorate

@api()
def start(request):
    if limited(request,'start',12):return error('Too many connection attempts. Try again in ten minutes.',429)
    data=body(request);name=str(data.get('name','Roasting computer')).strip()
    if not name or len(name)>80 or not name.isprintable():raise ValueError()
    now=timezone.now();device=secrets.token_urlsafe(32)
    code=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
    CompanionGrant.objects.filter(expires_at__lt=now-timedelta(days=1)).delete()
    CompanionGrant.objects.create(device_hash=digest(device),code_hash=digest(code),name=name,expires_at=now+timedelta(minutes=10),next_poll_at=now+timedelta(seconds=5))
    return reply({'device_code':device,'user_code':code[:4]+'-'+code[4:],'verification_uri':settings.PORTAL_BASE_URL+reverse('companion_devices'),'expires_in':600,'interval':5})

def tokens(device):
    now=timezone.now();access=secrets.token_urlsafe(32);refresh=secrets.token_urlsafe(32)
    device.access_hash=digest(access);device.refresh_hash=digest(refresh)
    device.access_expires_at=now+timedelta(minutes=15)
    # Absolute device lifetime does not slide indefinitely on refresh.
    device.save()
    return reply({'access_token':access,'refresh_token':refresh,'token_type':'Bearer','expires_in':900})

@api()
def token(request):
    if limited(request,'token',600):return error('Try again later.',429)
    data=body(request);now=timezone.now()
    with transaction.atomic():
        if data.get('refresh_token'):
            secret=str(data['refresh_token'])
            if not re.fullmatch(r'[A-Za-z0-9_-]{43}',secret):raise ValueError()
            d=CompanionDevice.objects.select_for_update().select_related('user').filter(refresh_hash=digest(secret)).first()
            if not d or d.revoked_at or d.refresh_expires_at<=now or not d.user.is_active or not d.user.is_staff or not constant_time_compare(d.auth_fingerprint,digest(d.user.get_session_auth_hash())):return error('Sign in to Companion again.',401)
            return tokens(d)
        grant=CompanionGrant.objects.select_for_update().filter(device_hash=digest(str(data.get('device_code',''))[:200])).first()
        if not grant or grant.expires_at<=now or grant.state=='used':return error('expired_token',400)
        if grant.state=='denied':return error('access_denied',400)
        if now<grant.next_poll_at:
            grant.interval=min(60,grant.interval+5);grant.next_poll_at=now+timedelta(seconds=grant.interval);grant.save()
            return reply({'error':'slow_down','interval':grant.interval},400)
        grant.next_poll_at=now+timedelta(seconds=grant.interval);grant.save()
        if grant.state!='approved':return error('authorization_pending',400)
        user=grant.user
        if not user or not user.is_active or not user.is_staff:return error('access_denied',403)
        grant.state='used';grant.save(update_fields=['state'])
        device=CompanionDevice(user=user,name=grant.name,refresh_expires_at=now+timedelta(days=30),auth_fingerprint=digest(user.get_session_auth_hash()))
        return tokens(device)

@login_required
@require_http_methods(['GET','POST'])
def devices(request):
    if not enabled() or not request.user.is_staff:return HttpResponse('Companion access is unavailable.',status=403)
    note='';pending=None
    if request.method=='POST':
        if limited(request,'consent',30):return HttpResponse('Too many attempts. Try again in ten minutes.',status=429)
        if request.POST.get('revoke'):
            import uuid
            try:device_id=uuid.UUID(request.POST['revoke'])
            except ValueError:return HttpResponse('Choose a valid computer.',status=400)
            CompanionDevice.objects.filter(pk=device_id,user=request.user,revoked_at__isnull=True).update(revoked_at=timezone.now())
            return redirect('companion_devices')
        code=re.sub(r'[\s-]','',request.POST.get('code','').upper())
        with transaction.atomic():
            pending=CompanionGrant.objects.select_for_update().filter(code_hash=digest(code),state='pending',expires_at__gt=timezone.now()).first()
            if not pending:note='That code is unavailable or expired. Start a new connection in Companion.'
            elif request.POST.get('decision') in ['approve','deny']:
                pending.state='approved' if request.POST['decision']=='approve' else 'denied';pending.user=request.user;pending.save()
                note='Computer connected. Return to Companion.' if pending.state=='approved' else 'Connection declined.';pending=None
    return render(request,'portal/companion_devices.html',{'devices':CompanionDevice.objects.filter(user=request.user,revoked_at__isnull=True).order_by('-created_at'),'pending':pending,'code':request.POST.get('code',''),'note':note})

@api(('GET',),True)
def me(request):
    from .appearance import PALETTES,appearance_context
    from .instance import configuration
    palette=next(x for x in PALETTES if x['id']==appearance_context(request)['appearance_palette'])
    c=configuration()
    return reply({'username':request.user.username,'roastery':c.name if c else 'Crema','palette':palette,'device_name':request.companion_device.name,'scope':['roasts:read','preparations:create'],'api_version':1})

def options(row,mode,library):
    result=[]
    for entry,revision in library:
        if revision and profiles.eligible(entry,revision,row,mode):
            c=revision.configuration
            result.append({'id':revision.pk,'name':c['name'],'charge':str(c['charge']),'drop':str(row.group.target_finish_temp_f if row.group.target_finish_temp_f is not None else c['drop'])})
    return result

@api(('GET',),True)
def roasts(request):
    result=[]
    rows=PlannedBatch.objects.filter(group__plan__accepted_at__isnull=False,group__plan__closed_at__isnull=True,group__plan__removed_at__isnull=True).select_related('roaster','batch','group__coffee','group__plan').prefetch_related('group__orders').order_by('group__plan__date','group__plan_id','id')[:1000]
    revisions={}
    for revision in ArtisanProfileRevision.objects.all():revisions.setdefault(revision.profile_key,revision)
    library=[(entry,revisions.get(entry['key'])) for entry in profiles.library_entries()]
    levels=dict((name,i) for i,(name,_) in enumerate(profiles.ROAST_LEVELS))
    for row in rows:
        try:profiles.usable_row(row)
        except ValidationError:continue
        result.append({'id':row.pk,'plan':row.group.plan_id,'date':str(row.group.plan.date),'coffee':row.group.coffee.name,'roast':row.group.roast_level,'roaster':row.roaster.name,'green':str(row.batch.green_oz if row.batch_id else row.green_oz),'fingerprint':profiles.row_fingerprint(row),'profiles':{'first':options(row,'first',library),'second':options(row,'second',library)}})
    result.sort(key=lambda r:(r['date'],r['plan'],0 if r['roaster'].casefold()=='x-e' else 1,r['roaster'],levels.get(r['roast'],99),r['id']))
    return reply({'roasts':result})

@api(authenticated=True)
def prepare(request,pk):
    if limited(request,'prepare',120):return error('Too many preparation requests. Try again later.',429)
    data=body(request)
    if data.get('confirmed') is not True:raise ValidationError('Review the load before preparing it.')
    mode=data.get('mode');choice=data.get('profile')
    if mode not in ['first','second'] or not isinstance(choice,int) or isinstance(choice,bool):raise ValueError()
    with transaction.atomic():
        initial=profiles.preparation_row(pk)
        RoastPlan.all_objects.select_for_update().get(pk=initial.group.plan_id)
        row=profiles.preparation_row(pk,lock=True);profiles.usable_row(row)
        if data.get('fingerprint')!=profiles.row_fingerprint(row):raise ValidationError('This load changed. Refresh and review it again.')
        revision=ArtisanProfileRevision.objects.select_for_update().filter(pk=choice).first()
        if not revision:raise ValidationError('Choose a current approved profile.')
        entry=profiles.entry_for(revision.profile_key)
        if not entry or profiles.current(entry).pk!=revision.pk or not profiles.eligible(entry,revision,row,mode):raise ValidationError('Choose a current approved profile for this load and session.')
        c=copy.deepcopy(revision.configuration);requested=row.group.target_finish_temp_f
        if requested is not None:c['drop']=str(profiles.tenths(requested))
        snapshot={'profile_key':entry['key'],'original_name':entry['file'],'original_sha256':entry['sha256'],'revision':revision.revision,'name':c['name'],'mode':mode,'roaster':row.roaster.name,'coffee':row.group.coffee.name,'roast_level':row.group.roast_level,'green_oz':str(row.batch.green_oz if row.batch_id else row.green_oz),'requested_drop':str(requested) if requested is not None else None,'charge':c['charge'],'drop':c['drop'],'off':str(profiles.tenths(c['drop'])+Decimal('.1')),'plan_id':row.group.plan_id,'planned_batch_id':row.pk,'fingerprint':profiles.row_fingerprint(row),'configuration':c}
        snapshot['roast_title']=profiles.roast_title(snapshot)
        prepared=ArtisanPreparation.objects.create(revision=revision,planned_batch=row,snapshot=snapshot,created_by=request.user)
        payload=profiles.package_bytes(entry,c,snapshot,prepared)
    response=HttpResponse(payload,content_type='application/zip');response['Cache-Control']='private, no-store';return response

@api(('GET',),True)
def validate(request,preparation_id):
    prepared=ArtisanPreparation.objects.filter(pk=preparation_id,created_by=request.user).first()
    if not prepared or not profiles.preparation_current(prepared):return error('This preparation changed or is no longer available. Refresh the roast list.',409)
    return reply({'current':True,'fingerprint':prepared.snapshot['fingerprint']})

@api(authenticated=True)
def disconnect(request):
    CompanionDevice.objects.filter(pk=request.companion_device.pk).update(revoked_at=timezone.now())
    return reply({'disconnected':True})
