"""Browser boundaries and database-backed sign-in limits for all app workers."""
import math,secrets,unicodedata
from datetime import timedelta
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.cache import patch_cache_control
from django.utils.crypto import salted_hmac
from django.utils.deprecation import MiddlewareMixin

MAX_REQUEST_BYTES=12*1024*1024
LOGIN_WINDOW=timedelta(minutes=10)


def wants_json(request):return 'application/json' in request.headers.get('Accept','')


def problem(request,status,title,message,**context):
    if wants_json(request):return JsonResponse({'error':message},status=status)
    if not hasattr(request,'user'):
        from django.contrib.auth.models import AnonymousUser
        request.user=AnonymousUser()
    return render(request,'portal/request_problem.html',{'problem_title':title,'problem_message':message,**context},status=status)


def csrf_failure(request,reason=''):
    return problem(request,403,'Your changes were not saved','The security check expired. Keep a note of unsaved entries. Sign in in another tab if needed, then reload before trying again.')


class PortalSecurityMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        request.get_host()  # Validate even HTTPS requests before rendering a page.
        request.csp_nonce=secrets.token_urlsafe(24)
        try:too_large=int(request.META.get('CONTENT_LENGTH') or 0)>MAX_REQUEST_BYTES
        except (TypeError,ValueError):too_large=True
        if too_large:
            response=problem(request,413,'This upload is too large','Use an image up to 10 MB, an Artisan file up to 2 MB, or an export up to 5 MB.')
        else:response=self.get_response(request)
        response['Permissions-Policy']='camera=(self), microphone=(), geolocation=(), payment=(), usb=()'
        # Nonces are attached to trusted template script tags, never added by
        # rewriting rendered HTML, which could bless untrusted injected markup.
        if response.get('Content-Type','').split(';')[0]=='text/html':
            response['Content-Security-Policy']=("default-src 'self'; script-src 'self' 'nonce-"+request.csp_nonce+"'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
        if getattr(getattr(request,'user',None),'is_authenticated',False) or request.path in ['/login/','/admin/login/'] or response.status_code>=400:
            patch_cache_control(response,private=True,no_store=True,no_cache=True,max_age=0,must_revalidate=True)
        return response


def login_limits(request):
    # Forwarded client-IP headers are deliberately not trusted. The peer limit
    # is generous because a reverse proxy may represent several real people.
    peer=str(request.META.get('REMOTE_ADDR','unknown'))[:128]
    name=unicodedata.normalize('NFKC',str(request.POST.get('username',''))[:256]).casefold()
    return [(salted_hmac('coffee-login-v1',value,algorithm='sha256').hexdigest(),limit) for value,limit in [('peer:'+peer,100),('identity:'+peer+'|'+name,10)]]


class LoginThrottleMiddleware(MiddlewareMixin):
    def process_view(self,request,view_func,view_args,view_kwargs):
        if request.method!='POST' or request.path not in ['/login/','/admin/login/']:return None
        from .models import LoginAttemptWindow
        now=timezone.now();limits=login_limits(request);blocked_until=None
        with transaction.atomic():
            # Old counters contain no audit history and need no indefinite retention.
            LoginAttemptWindow.objects.filter(expires_at__lt=now-timedelta(days=1)).delete()
            windows=[]
            for key,limit in limits:
                item,_=LoginAttemptWindow.objects.get_or_create(key=key,defaults={'expires_at':now+LOGIN_WINDOW})
                item=LoginAttemptWindow.objects.select_for_update().get(pk=key)
                if item.expires_at<=now:item.attempts=0;item.expires_at=now+LOGIN_WINDOW
                if item.attempts>=limit:
                    blocked_until=item.expires_at
                    # Check the shared peer window first: a blocked connection
                    # cannot fill the table with new, random username buckets.
                    break
                windows.append(item)
            if not blocked_until:
                for item in windows:item.attempts+=1;item.save(update_fields=['attempts','expires_at'])
        if blocked_until:
            seconds=max(1,math.ceil((blocked_until-now).total_seconds()))
            response=problem(request,429,'Please wait before signing in again','Too many sign-in attempts. Wait up to 10 minutes, then try again. Existing signed-in sessions still work.',retry_minutes=math.ceil(seconds/60))
            response['Retry-After']=str(seconds);return response
        return None
