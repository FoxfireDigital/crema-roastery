from pathlib import Path
import os
BASE_DIR=Path(__file__).resolve().parent

def secret(name, default=''):
    path=os.environ.get(name+'_FILE')
    return Path(path).read_text().strip() if path else os.environ.get(name,default)
SECRET_KEY=secret('DJANGO_SECRET_KEY')
DEBUG=False
from urllib.parse import urlsplit
PORTAL_BASE_URL=os.environ.get('PORTAL_BASE_URL','https://localhost').rstrip('/')
_url=urlsplit(PORTAL_BASE_URL)
if _url.scheme not in ['https','http'] or not _url.hostname or _url.path or _url.query or _url.fragment or _url.username or _url.password:raise ValueError('PORTAL_BASE_URL must be an origin URL.')
LOCAL_DEVELOPMENT=os.environ.get('PORTAL_LOCAL_DEVELOPMENT')=='1'
PORTAL_DEMO_MODE=os.environ.get('PORTAL_DEMO_MODE')=='1'
if _url.scheme!='https' and not LOCAL_DEVELOPMENT:raise ValueError('Production requires HTTPS.')
ALLOWED_HOSTS=[_url.hostname,'localhost','127.0.0.1',*filter(None,os.environ.get('PORTAL_LAN_HOSTS','').split(','))]
CSRF_TRUSTED_ORIGINS=[PORTAL_BASE_URL]
COFFEE_BACKUP_ROOT='/var/lib/coffee-backups'
if len(SECRET_KEY)<32:raise ValueError('Provide a unique DJANGO_SECRET_KEY of at least 32 characters.')
INSTALLED_APPS=['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','portal']
MIDDLEWARE=['django.middleware.security.SecurityMiddleware','portal.security.PortalSecurityMiddleware','whitenoise.middleware.WhiteNoiseMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','portal.security.DemoBoundaryMiddleware','portal.security.LoginThrottleMiddleware','portal.inventory_actor.InventoryActorMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF='project_urls'
TEMPLATES=[{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'portal'/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.debug','django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages','portal.appearance.appearance_context','portal.green_stock.inventory_context','portal.shopfloor.tools_context','portal.payroll.payroll_context','portal.instance.instance_context']}}]
WSGI_APPLICATION='project_wsgi.application'
if not os.environ.get('DB_HOST') and not LOCAL_DEVELOPMENT and os.environ.get('PORTAL_BUILD')!='1':raise ValueError('Production requires PostgreSQL.')
if os.environ.get('DB_HOST'):
    DATABASES={'default':{'ENGINE':'django.db.backends.postgresql','NAME':'coffee','USER':'coffee','PASSWORD':secret('DB_PASSWORD'),'HOST':os.environ['DB_HOST'],'PORT':'5432','CONN_MAX_AGE':60}}
else:
    DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':os.environ.get('PORTAL_SQLITE_PATH',str(BASE_DIR/'development.sqlite3'))}}
AUTH_PASSWORD_VALIDATORS=[{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator','OPTIONS':{'min_length':12}},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE='en-us'
TIME_ZONE=os.environ.get('PORTAL_TIME_ZONE','UTC')
USE_I18N=True
USE_TZ=True
STATIC_URL='/static/'
STATIC_ROOT=BASE_DIR/'staticfiles'
STORAGES={'staticfiles':{'BACKEND':'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
# The import table can submit 1,000 order checkboxes plus CSRF/action/plan fields.
DATA_UPLOAD_MAX_NUMBER_FIELDS=1100
LOGIN_URL='/login/'
LOGIN_REDIRECT_URL='/'
LOGOUT_REDIRECT_URL='/login/'
SESSION_COOKIE_SECURE=not LOCAL_DEVELOPMENT
CSRF_COOKIE_SECURE=not LOCAL_DEVELOPMENT
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE='Lax'
SECURE_CONTENT_TYPE_NOSNIFF=True
SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')
SECURE_REFERRER_POLICY='same-origin'
X_FRAME_OPTIONS='DENY'
SECURE_SSL_REDIRECT=not LOCAL_DEVELOPMENT
SECURE_SSL_HOST=_url.netloc
# The NAS health check is read-only and deliberately remains available locally.
SECURE_REDIRECT_EXEMPT=[r'^healthz/$']
SECURE_HSTS_SECONDS=3600
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_HSTS_PRELOAD=False
DATA_UPLOAD_MAX_NUMBER_FILES=4
FILE_UPLOAD_MAX_MEMORY_SIZE=1024*1024
CSRF_FAILURE_VIEW='portal.security.csrf_failure'
