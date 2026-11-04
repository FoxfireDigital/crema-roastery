"""First-party device protocol regression; fictional in-memory database only."""
import os,sys,io,json,base64,hashlib,zipfile
import tempfile
from unittest.mock import patch
from pathlib import Path
from datetime import timedelta
ROOT=Path(__file__).resolve().parents[1]
if os.environ.get('DB_HOST'):raise SystemExit('Unset DB_HOST: Companion checks only use an in-memory database.')
os.environ.update(DJANGO_SETTINGS_MODULE='project_settings',DJANGO_SECRET_KEY='fictional-device-protocol-test-only-0123456789',PORTAL_LOCAL_DEVELOPMENT='1',PORTAL_BASE_URL='http://localhost',PORTAL_SQLITE_PATH=':memory:',PORTAL_COMPANION_ENABLED='1')
sys.path.insert(0,os.environ.get('PORTAL_APP_ROOT',str(ROOT/'app')))
import django;django.setup()
from django.core.management import call_command
from django.test import Client,override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from portal.models import *
from portal.companion import digest
call_command('migrate',stdout=io.StringIO());call_command('makemigrations','--check','--dry-run',stdout=io.StringIO())
checks=[]
def check(name,value):
    assert value,name
    checks.append(name)
api=Client(HTTP_HOST='localhost');browser=Client(HTTP_HOST='localhost');owner=get_user_model().objects.create_user('fictional-operator',password='synthetic-device-password-19',is_staff=True)
other=get_user_model().objects.create_user('other-operator',password='synthetic-other-password-19',is_staff=True)
def post(path,data,**kw):return api.post('/api/companion/v1/'+path,json.dumps(data),content_type='application/json',**kw)
def get(path,token):return api.get('/api/companion/v1/'+path,HTTP_AUTHORIZATION='Bearer '+token)
with override_settings(COMPANION_ENABLED=False):check('disabled-endpoint-404',post('start/',{}).status_code==404)
check('no-cookie-auth',api.get('/api/companion/v1/me/').status_code==401)
browser.force_login(owner);check('session-does-not-authenticate-api',browser.get('/api/companion/v1/me/').status_code==401)
check('origin-header-refused',post('start/',{},HTTP_ORIGIN='https://evil.example').status_code==403)
check('get-cannot-start',api.get('/api/companion/v1/start/').status_code==405)
check('invalid-json',api.post('/api/companion/v1/start/','[1]',content_type='application/json').status_code==400)
with override_settings(LOCAL_DEVELOPMENT=False):check('https-required',post('start/',{}).status_code==400)
started=post('start/',{'name':'Fictional roasting PC'}).json();code=started['user_code'];device_code=started['device_code']
grant=CompanionGrant.objects.get(device_hash=digest(device_code))
check('no-plain-device-secret',device_code!=grant.device_hash and code.replace('-','')!=grant.code_hash)
check('polling-slow-down',post('token/',{'device_code':device_code}).json()['error']=='slow_down')
CompanionGrant.objects.update(next_poll_at=timezone.now()-timedelta(seconds=1))
check('pending-cannot-get-token',post('token/',{'device_code':device_code}).json()['error']=='authorization_pending')
csrf=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');csrf.force_login(owner)
check('browser-consent-csrf',csrf.post('/companion/',{'code':code,'decision':'approve'}).status_code==403)
check('get-does-not-approve',browser.get('/companion/',{'code':code,'decision':'approve'}).status_code==200 and CompanionGrant.objects.get(pk=grant.pk).state=='pending')
check('consent-review',b'Fictional roasting PC' in browser.post('/companion/',{'code':code}).content)
browser.post('/companion/',{'code':code,'decision':'approve'})
CompanionGrant.objects.update(next_poll_at=timezone.now()-timedelta(seconds=1))
pair=post('token/',{'device_code':device_code}).json();access=pair['access_token'];refresh=pair['refresh_token'];device=CompanionDevice.objects.get(user=owner)
check('one-time-device-code',post('token/',{'device_code':device_code}).json()['error']=='expired_token')
check('hashed-tokens',device.access_hash!=access and device.refresh_hash!=refresh)
UserAppearance.objects.create(user=owner,palette='gold')
me=get('me/',access);check('account-theme-and-scopes',me.status_code==200 and me.json()['palette']['id']=='gold' and me.json()['scope']==['roasts:read','preparations:create'])
check('no-store',me['Cache-Control'].find('no-store')>=0)
check('no-general-session',api.get('/stock/',HTTP_AUTHORIZATION='Bearer '+access).status_code==302)
coffee=Coffee.objects.create(name='Fictional Hearth',kind='blend',standard_roast='Medium')
machine=Roaster.objects.create(name='X-e',max_green_oz=140,min_green_oz=41)
plan=RoastPlan.objects.create(created_by=owner,accepted_at=timezone.now())
group=RoastGroup.objects.create(plan=plan,key='fictional',coffee=coffee,roast_level='Medium')
IncomingOrderLine.objects.create(group=group,finished_oz=48,reference='Fictional order')
row=PlannedBatch.objects.create(group=group,roaster=machine,green_oz=60)
original={'mode':'F','timex':[0,60,120,180],'temp1':[340,350,370,390],'temp2':[320,330,360,400],'extratimex':[],'extratemp1':[],'extratemp2':[],'extraname1':[],'extraname2':[],'specialevents':[],'specialeventstype':[],'specialeventsvalue':[],'specialeventsStrings':[],'flavors':[5.0]*10,'timeindex':[0,1,2,0,0,0,3,0],'title':'Fictional reference'}
raw=repr(original).encode();sha=hashlib.sha256(raw).hexdigest();source=ArtisanProfileSource.objects.create(sha256=sha,filename='Fictional.alog',original_b64=base64.b64encode(raw).decode(),inspection={'file':'Fictional.alog','sha256':sha},created_by=owner)
c={'charge':'320.0','drop':'400.0','name':'Fictional First Full City','state':'active','machines':['X-e'],'coffee_id':coffee.pk,'roast_level':'Medium','mode':'first','note':''}
revision=ArtisanProfileRevision.objects.create(profile_key='fictional-connected-profile',revision=1,configuration=c,source=source,created_by=owner)
listed=get('roasts/',access).json()['roasts'];check('accepted-loads-profile-filter',len(listed)==1 and len(listed[0]['profiles']['first'])==1 and not listed[0]['profiles']['second'])
request={'profile':revision.pk,'mode':'first','fingerprint':listed[0]['fingerprint'],'confirmed':True}
check('confirmation-required',post(f'roasts/{row.pk}/prepare/',{**request,'confirmed':False},HTTP_AUTHORIZATION='Bearer '+access).status_code==409)
check('stale-fingerprint-rejected',post(f'roasts/{row.pk}/prepare/',{**request,'fingerprint':'old'},HTTP_AUTHORIZATION='Bearer '+access).status_code==409)
check('wrong-session-rejected',post(f'roasts/{row.pk}/prepare/',{**request,'mode':'second'},HTTP_AUTHORIZATION='Bearer '+access).status_code==409)
prepared=post(f'roasts/{row.pk}/prepare/',request,HTTP_AUTHORIZATION='Bearer '+access)
check('fresh-audited-package',prepared.status_code==200 and ArtisanPreparation.objects.count()==1)
with zipfile.ZipFile(io.BytesIO(prepared.content)) as archive:
    manifest=json.loads(archive.read('manifest.json'));pid=manifest['preparation_id'];check('real-package-checksums',all(hashlib.sha256(archive.read(name)).hexdigest()==sha for name,sha in manifest['files'].items()))
    if len(sys.argv)>1:Path(sys.argv[1]).write_bytes(prepared.content)
check('preparation-current',get(f'preparations/{pid}/validate/',access).status_code==200)
plan.version+=1;plan.save(update_fields=['version'])
check('edit-invalidates-preparation',get(f'preparations/{pid}/validate/',access).status_code==409)
plan.removed_at=timezone.now();plan.save(update_fields=['removed_at'])
check('removed-plan-not-listed',get('roasts/',access).json()['roasts']==[])
check('removed-plan-cannot-prepare',post(f'roasts/{row.pk}/prepare/',request,HTTP_AUTHORIZATION='Bearer '+access).status_code in [404,409])
check('no-production-side-effects',not Batch.objects.exists() and not Shift.objects.exists() and not GreenMovement.objects.exists() and not RoastedStockAllocation.objects.exists() and not PackingProgress.objects.exists())
rotated=post('token/',{'refresh_token':refresh}).json();newaccess=rotated['access_token'];newrefresh=rotated['refresh_token']
check('refresh-rotation',post('token/',{'refresh_token':refresh}).status_code==401 and get('me/',access).status_code==401 and get('me/',newaccess).status_code==200)
device.refresh_from_db();intruder=Client(HTTP_HOST='localhost');intruder.force_login(other);intruder.post('/companion/',{'revoke':str(device.pk)});device.refresh_from_db()
check('revocation-account-owned',device.revoked_at is None)
owner.set_password('changed-synthetic-password-192');owner.save()
check('password-change-revokes',get('me/',newaccess).status_code==401 and post('token/',{'refresh_token':newrefresh}).status_code==401)
browser.force_login(owner);browser.post('/companion/',{'revoke':str(device.pk)});device.refresh_from_db();check('browser-revoke',device.revoked_at is not None)
check('invalid-revoke-safe',browser.post('/companion/',{'revoke':'not-a-uuid'}).status_code==400)
denied=post('start/',{'name':'Declined fictional PC'}).json();browser.post('/companion/',{'code':denied['user_code'],'decision':'deny'})
check('denied-device-cannot-connect',post('token/',{'device_code':denied['device_code']}).json()['error']=='access_denied')
expired=post('start/',{}).json();CompanionGrant.objects.filter(device_hash=digest(expired['device_code'])).update(expires_at=timezone.now()-timedelta(seconds=1))
check('expired-device-cannot-connect',post('token/',{'device_code':expired['device_code']}).json()['error']=='expired_token')
ordinary=get_user_model().objects.create_user('ordinary',password='synthetic-normal-password-199')
ordinary_browser=Client(HTTP_HOST='localhost');ordinary_browser.force_login(ordinary)
check('nonstaff-cannot-approve',ordinary_browser.post('/companion/',{'code':code,'decision':'approve'}).status_code==403)
with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'PORTAL_COMPANION_DOWNLOAD_ROOT':directory}):
    root=Path(directory);data=b'Fictional download fixture only; not an executable.'
    names={'installer':'CremaCompanion-Setup-fictional.exe','portable':'CremaCompanion-Pilot-fictional.zip'}
    release={'format':'crema-companion-release-v1','version':'0.2.0-preview.2','signed':False,'artifacts':{}}
    for kind,name in names.items():
        (root/name).write_bytes(data)
        release['artifacts'][kind]={'filename':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    def publish(): (root/'release.json').write_text(json.dumps(release),encoding='utf-8')
    publish()
    check('download-login-required',api.get('/companion/download/installer/').status_code==302)
    check('download-nonstaff-denied',ordinary_browser.get('/companion/install/').status_code==403 and ordinary_browser.get('/companion/download/installer/').status_code==403)
    page=browser.get('/companion/install/')
    check('install-page-version-origin-and-links',page.status_code==200 and b'0.2.0-preview.2' in page.content and b'http://localhost' in page.content and b'/companion/download/installer/' in page.content)
    for kind in names:
        response=browser.get('/companion/download/'+kind+'/')
        check('verified-'+kind+'-attachment',response.status_code==200 and b''.join(response.streaming_content)==data and 'attachment;' in response['Content-Disposition'] and 'no-store' in response['Cache-Control'] and response['X-Checksum-SHA256']==hashlib.sha256(data).hexdigest())
        response.close()
    check('download-post-refused',browser.post('/companion/download/installer/').status_code==405)
    check('download-unknown-kind-refused',browser.get('/companion/download/not-a-package/').status_code==404)
    with override_settings(COMPANION_ENABLED=False):check('download-feature-off-denied',browser.get('/companion/install/').status_code==403 and browser.get('/companion/download/installer/').status_code==403)
    (root/names['installer']).write_bytes(b'X'*len(data))
    check('download-corruption-blocked',browser.get('/companion/download/installer/').status_code==404)
    (root/names['installer']).write_bytes(data)
    release['artifacts']['installer']['filename']='../outside.exe';publish()
    check('download-path-escape-blocked',browser.get('/companion/download/installer/').status_code==404)
    release['artifacts']['installer']['filename']=names['installer'];publish()
    (root/'release.json').write_text('[]',encoding='utf-8')
    check('download-invalid-manifest-safe',browser.get('/companion/install/').status_code==200 and browser.get('/companion/download/installer/').status_code==404)
    (root/'release.json').write_bytes(b'X'*8193)
    check('download-oversized-manifest-safe',browser.get('/companion/download/installer/').status_code==404)
    publish()
    if os.name=='posix':
        target=root/names['installer'];target.unlink();target.symlink_to(root/names['portable'])
        check('download-symlink-blocked',browser.get('/companion/download/installer/').status_code==404)
LoginAttemptWindow.objects.all().delete()
for _ in range(12):assert post('start/',{}).status_code==200
check('start-rate-limited',post('start/',{}).status_code==429)
print(json.dumps({'result':'passed','count':len(checks),'checks':checks,'data':'fictional in-memory only'},indent=2))
