"""Synthetic full restore into separate volumes, only for our disposable QA stack."""
from pathlib import Path
import copy
import hashlib
import json
import re
import subprocess
import time

SEED = r'''
import os,base64,hashlib,json
from datetime import timedelta
from decimal import Decimal
os.environ.setdefault('DJANGO_SETTINGS_MODULE','project_settings')
import django;django.setup()
from django.contrib.auth import get_user_model
from portal.models import StoreConnection,ArtisanProfileSource,Batch,BatchArtisanLog,Coffee,Roaster,Shift,GreenBeanItem
from django.utils import timezone
from portal.shopify_client import encrypt
assert not StoreConnection.objects.exists(),'QA backup seed requires an empty connection table'
owner=get_user_model().objects.get(username='trial-owner')
StoreConnection.objects.create(name='Fictional restore fixture',platform='csv',active=False,automatic=False,updated_by=owner,credentials_cipher=encrypt(json.dumps({'token':'synthetic-recovery-only'})))
raw=b'FICTIONAL_RETAINED_ORIGINAL\x00\xff\n'
source=ArtisanProfileSource.objects.create(sha256=hashlib.sha256(raw).hexdigest(),filename='fictional-original.alog',original_b64=base64.b64encode(raw).decode(),inspection={'fixture':True},created_by=owner)
item=GreenBeanItem.objects.create(name='Fictional recovery stock',remaining_oz=Decimal('100.0'),recorded_by=owner)
batch=Batch.objects.create(operator=owner,coffee=Coffee.objects.get(name='Demo Hearth'),roaster=Roaster.objects.get(name='Demo Small'),green_item=item,green_oz=Decimal('20.0'),roasted_oz=Decimal('17.1'),roast_level='Medium',measured_at=timezone.now(),roasted_at=timezone.now(),note='Fictional recovery fixture only')
BatchArtisanLog.objects.create(batch=batch,source=source,created_by=owner)
item.refresh_from_db();assert item.remaining_oz==Decimal('80.0')
Shift.objects.create(user=owner,started_at=timezone.now()-timedelta(hours=2),ended_at=timezone.now())
print('Synthetic inactive credential and original-file fixtures created')
'''

SNAPSHOT = r'''
import os,json,hashlib
os.environ.setdefault('DJANGO_SETTINGS_MODULE','project_settings')
import django;django.setup()
from django.apps import apps
from django.core import serializers
parts=[];counts={}
for model in sorted(apps.get_models(),key=lambda m:m._meta.label):
    rows=model._base_manager.order_by(model._meta.pk.name)
    counts[model._meta.label]=rows.count()
    parts.append(serializers.serialize('json',rows))
print(json.dumps({'sha256':hashlib.sha256('\n'.join(parts).encode()).hexdigest(),'counts':counts}))
'''

RESTORE_KEYS = '''
import io,os,sys,tarfile
from pathlib import Path
root=Path('/var/lib/roastery-secrets')
assert not any(root.iterdir()),'Restore key volume must be empty'
data=sys.stdin.buffer.read(16385)
assert len(data)<=16384,'Unexpected key archive size'
with tarfile.open(fileobj=io.BytesIO(data),mode='r:') as archive:
    members=archive.getmembers()
    assert sorted(m.name for m in members)==['django','postgres']
    assert all(m.isfile() and 64<=m.size<=128 for m in members)
    for member in members:
        fd=os.open(root/member.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
        with os.fdopen(fd,'wb') as target:target.write(archive.extractfile(member).read())
print('Matching keys restored into separate QA volume')
'''


def rehearse(compose, root, configuration, password):
    project=configuration['name']
    assert re.fullmatch(r'crematrial_[0-9a-f]{12}',project),'Only the disposable QA project is accepted'
    assert Path(root).parent==Path('/tmp') and Path(root).name.startswith('crema-yaml-trial-')

    def command(args, data=None, timeout=120, ok=True):
        value=subprocess.run(compose+args,input=data,capture_output=True,timeout=timeout)
        if ok and value.returncode:raise RuntimeError('QA restore command failed: '+value.stderr.decode(errors='replace')[-1200:])
        return value

    def python(service, code):
        return command(['exec','-T',service,'python','-'],code.encode()).stdout.decode().strip()

    # Confirm that no bind-mounted installation keys or database slipped in.
    db=command(['ps','-q','postgres']).stdout.decode().strip()
    info=json.loads(subprocess.check_output(['docker','inspect',db]))[0]
    assert info['Config']['Labels']['com.docker.compose.project']==project
    assert all(m['Type']=='volume' and m['Name'].startswith(project+'_') for m in info['Mounts'])
    command(['stop','worker'])  # Quiesce only the fictional source before comparison.
    python('web',SEED)
    before=json.loads(python('web',SNAPSHOT))
    dump=command(['exec','-T','postgres','pg_dump','-U','coffee','-d','coffee','-Fc']).stdout
    assert dump.startswith(b'PGDMP') and len(dump)>1000
    assert command(['exec','-T','postgres','pg_restore','--list'],dump).stdout
    corrupt=command(['exec','-T','postgres','pg_restore','--list'],b'FICTIONAL_CORRUPT_DUMP',ok=False)
    assert corrupt.returncode!=0,'Corrupt dump was accepted'
    keys=command(['exec','-T','web','tar','-C','/run/roastery-secrets','-cf','-','django','postgres']).stdout
    assert 0<len(keys)<=16384
    folder=Path(root)/'restore-material';folder.mkdir(mode=0o700)
    for name,data in [('database.dump',dump),('instance-keys.tar',keys)]:
        path=folder/name;path.write_bytes(data);path.chmod(0o600)

    config=copy.deepcopy(configuration)
    for name in ['restore_database','restore_keys']:
        config['volumes'][name]={'name':project+'_'+name}
    initialize=copy.deepcopy(config['services']['initialize'])
    initialize.pop('depends_on',None)
    initialize['volumes']=[{'type':'volume','source':'restore_keys','target':'/var/lib/roastery-secrets'}]
    initialize['command']=['python','-c',RESTORE_KEYS]
    config['services']['restore_keys']=initialize
    postgres=copy.deepcopy(config['services']['postgres'])
    postgres['volumes']=[{'type':'volume','source':'restore_database','target':'/var/lib/postgresql/data'},{'type':'volume','source':'restore_keys','target':'/run/roastery-secrets','read_only':True}]
    postgres['depends_on']={'restore_keys':{'condition':'service_completed_successfully'}}
    config['services']['restore_postgres']=postgres
    postgres.update(mem_limit='256m',cpus=0.5)
    web=copy.deepcopy(config['services']['web'])
    web['environment']={**web['environment'],'DB_HOST':'restore_postgres'}
    web['volumes']=[{'type':'volume','source':'restore_keys','target':'/run/roastery-secrets','read_only':True}]
    web['depends_on']={'restore_postgres':{'condition':'service_healthy'}}
    config['services']['restore_web']=web
    web.update(mem_limit='384m',cpus=0.5)
    # The caller owns this generated QA file; service names and project stay fixed.
    Path(compose[-1]).write_text(json.dumps(config))
    command(['run','--rm','-T','--no-deps','restore_keys'],keys)
    # Subsequent up can use a no-op rather than trying to replace existing keys.
    config['services']['restore_keys']['command']=['python','-c','from pathlib import Path;assert all((Path("/var/lib/roastery-secrets")/name).is_file() for name in ["django","postgres"])']
    Path(compose[-1]).write_text(json.dumps(config))
    command(['up','-d','restore_postgres'])
    for _ in range(45):
        if command(['exec','-T','restore_postgres','pg_isready','-h','127.0.0.1','-U','coffee','-d','coffee'],ok=False).returncode==0:break
        time.sleep(1)
    else:raise RuntimeError('Disposable restore database did not become ready')
    command(['exec','-T','restore_postgres','pg_restore','-U','coffee','-d','coffee','--exit-on-error','--no-owner'],dump)
    # Later writes to the original must not appear in the restored database.
    python('web',"import os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','project_settings');import django;django.setup();from portal.models import Coffee;Coffee.objects.create(name='Fictional after-backup write',kind='single_origin',standard_roast='Medium')")
    command(['up','-d','restore_web'])
    for _ in range(45):
        health=command(['exec','-T','restore_web','python','-c',"import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz/',timeout=2)"],ok=False)
        if health.returncode==0:break
        time.sleep(1)
    else:raise RuntimeError('Disposable restored application did not become ready')
    after=json.loads(python('restore_web',SNAPSHOT))
    assert before==after,'Restored records differ from the consistent backup snapshot'
    check='''
import os,json,base64,hashlib
os.environ.setdefault('DJANGO_SETTINGS_MODULE','project_settings')
import django;django.setup()
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import Client
from portal.models import StoreConnection,ArtisanProfileSource,Coffee
from portal.stores import credentials
store=StoreConnection.objects.get(name='Fictional restore fixture')
assert credentials(store)=={'token':'synthetic-recovery-only'}
original=settings.SECRET_KEY;settings.SECRET_KEY='synthetic-wrong-instance-key'
try:
    credentials(store)
except ValidationError:pass
else:raise AssertionError('Wrong instance key was accepted')
finally:settings.SECRET_KEY=original
source=ArtisanProfileSource.objects.get(filename='fictional-original.alog')
raw=base64.b64decode(source.original_b64)
assert raw==b'FICTIONAL_RETAINED_ORIGINAL\\x00\\xff\\n' and hashlib.sha256(raw).hexdigest()==source.sha256
assert not Coffee.objects.filter(name='Fictional after-backup write').exists()
client=Client(HTTP_HOST='crema-qa.localhost')
assert client.login(username='trial-owner',password=PASSWORD)
assert client.get('/stores/',secure=True).status_code==200
Coffee.objects.create(name='Fictional restored-only write',kind='single_origin',standard_roast='Medium')
print('Accounts, matching-key credentials and original bytes verified; wrong key rejected')
'''.replace('PASSWORD',repr(password))
    python('restore_web',check)
    python('web',"import os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','project_settings');import django;django.setup();from portal.models import Coffee;assert not Coffee.objects.filter(name='Fictional restored-only write').exists()")
    restored_keys=command(['exec','-T','restore_web','tar','-C','/run/roastery-secrets','-cf','-','django','postgres']).stdout
    # Compare file contents rather than tar headers/owner metadata.
    import io,tarfile
    def contents(data):
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:return {m.name:archive.extractfile(m).read() for m in archive.getmembers()}
    assert contents(keys)==contents(restored_keys)
    return {'consistentDump':True,'separateDatabaseAndKeyVolumes':True,'sameRecords':True,'models':len(before['counts']),'modelRows':sum(before['counts'].values()),'snapshotSHA256':before['sha256'],'dumpSHA256':hashlib.sha256(dump).hexdigest(),'matchingKeys':True,'credentialsReadable':True,'originalBytesRetained':True,'accountLogin':True,'wrongKeyRejected':True,'corruptDumpRejected':True,'laterSourceWritesExcluded':True,'restoredWritesIndependent':True,'restoredSequenceUsable':True,'offsiteDownloadOrEncryptionTested':False}
