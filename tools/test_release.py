"""Synthetic fresh-install regression. Optional TEST_DB_HOST exercises PostgreSQL."""
from pathlib import Path
import os,sys,tempfile,io,runpy,json,subprocess,shutil
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];APP=Path(os.environ.get('PORTAL_APP_ROOT',str(ROOT/'app')));sys.path.insert(0,str(APP))
if os.environ.get('DB_HOST') and os.environ.get('PORTAL_RELEASE_QA_DISPOSABLE')!='1':raise SystemExit('Refusing an external database. Use an isolated disposable QA stack, or unset DB_HOST for in-memory tests.')
temp=tempfile.TemporaryDirectory(prefix='roastery-release-test-')
from registry_identity_checks import run_registry_identity_checks
run_registry_identity_checks(Path(temp.name))
os.environ.update(DJANGO_SETTINGS_MODULE='project_settings',DJANGO_SECRET_KEY='synthetic-release-test-key-only-not-for-deployment',PORTAL_LOCAL_DEVELOPMENT='1',PORTAL_BASE_URL='http://localhost',PORTAL_SQLITE_PATH=':memory:')
if os.environ.get('TEST_DB_HOST'):os.environ['DB_HOST']=os.environ['TEST_DB_HOST']
import django;django.setup()
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.test.utils import setup_test_environment
from portal.models import *
call_command('migrate',interactive=False,stdout=io.StringIO());call_command('check');call_command('makemigrations','--check','--dry-run',stdout=io.StringIO())
runpy.run_path(str(APP/'bootstrap.py'))
assert not Coffee.objects.exists() and not Roaster.objects.exists() and not get_user_model().objects.exists()
owner=get_user_model().objects.create_superuser('test-owner','', 'Only-synthetic-test-password-192!')
setup_test_environment();client=Client(HTTP_HOST='localhost');client.force_login(owner)
for path in ['/setup/','/','/planning/','/plans/','/packing/','/imports/','/stock/','/green-beans/','/suppliers/','/purchases/','/cupping/','/artisan/','/products/','/subscriptions/','/wholesale/','/information/','/help/','/payroll/','/recovery/','/labels/artwork/']:
    response=client.get(path);assert response.status_code==200,(path,response.status_code)
assert not Coffee.objects.exists() and not Batch.objects.exists()
try:Roaster.objects.create(name='Unsafe missing limit')
except ValidationError:pass
else:raise AssertionError('Unconfigured active machine accepted')
call_command('portal_demo',owner=owner.username,stdout=io.StringIO())
assert Coffee.objects.count()==7 and Roaster.objects.count()==2 and not Batch.objects.exists() and not ImportOrder.objects.exists() and not Shift.objects.exists()
try:call_command('portal_demo',owner=owner.username,stdout=io.StringIO())
except Exception as exc:assert 'empty catalog' in str(exc)
else:raise AssertionError('Demo overwrote real catalog')
base=Coffee.objects.get(name='Demo Hearth');base.flavor_base_allowed=False;base.save()
assert not base.flavor_base_eligible;base.flavor_base_allowed=True;base.save()
from portal.wholesale import ItemForm
form=ItemForm({'size':'frac_pack','count':'2','grind':'whole'});assert form.is_valid(),form.errors
assert sum(x['extra_oz'] for x in form.cleaned_data['expanded'])==Decimal(20)
from portal.artisan_profiles import ProfileForm
assert set(dict(ProfileForm().fields['machines'].choices))=={'Demo Small','Demo Large'}
from sourcing_checks import run_sourcing_cupping_checks
run_sourcing_cupping_checks(Path(temp.name),client,owner)
from costing_checks import run_costing_checks
run_costing_checks(Path(temp.name),client,owner)
from onboarding_checks import run_onboarding_checks
run_onboarding_checks(client,owner)
from store_checks import run_store_checks
run_store_checks(Path(temp.name),client,owner)
from production_checks import run_production_checks, run_standard_label_checks
run_production_checks(Path(temp.name),client,owner)
run_standard_label_checks(client,owner)
from roast_pooling_checks import run_order_roast_edit_checks, run_roast_pooling_checks
run_roast_pooling_checks(client,owner)
run_order_roast_edit_checks(client,owner)
from batch_combine_checks import run_batch_combine_checks
run_batch_combine_checks(client,owner)
from minimum_load_checks import run_minimum_load_checks
run_minimum_load_checks(client,owner)
from today_packing_checks import run_today_packing_checks
run_today_packing_checks(client,owner)
from evidence_actions_checks import run_evidence_actions_checks
run_evidence_actions_checks(client,owner)
from artisan_checks import run_artisan_checks
run_artisan_checks(client,owner)
from green_checks import run_green_checks
run_green_checks(client,owner)
from roast_day_checks import run_roast_day_checks
run_roast_day_checks(client,owner)
from production_order_checks import run_production_order_checks
run_production_order_checks(client,owner)
from review_checks import run_review_checks
run_review_checks(client,owner)
for path in ['/setup/','/','/planning/','/packing/','/stock/','/green-beans/','/wholesale/','/products/','/information/','/help/','/artisan/']:
    response=client.get(path);assert response.status_code==200,(path,response.status_code)
assert not Batch.objects.exists() and not ImportOrder.objects.exists() and not Shift.objects.exists()
if os.name=='posix':
    subprocess.run([sys.executable,str(Path(__file__).parent/'test_initializer.py')],check=True)
for overrides in [{'DJANGO_SECRET_KEY':'short'},{'PORTAL_BASE_URL':'http://coffee.example.org'},{'DB_HOST':''}]:
    env={**os.environ,'PORTAL_LOCAL_DEVELOPMENT':'0','DJANGO_SECRET_KEY':'synthetic-production-settings-test-key-only','PORTAL_BASE_URL':'https://coffee.example.org','DB_HOST':'not-contacted',**overrides}
    env.pop('DJANGO_SECRET_KEY_FILE',None)
    result=subprocess.run([sys.executable,str(APP/'manage.py'),'check'],env=env,capture_output=True,text=True)
    assert result.returncode!=0,'Unsafe production configuration accepted'
print('PASS: empty install, generic catalog, configurable machines/assortment, optional demo, sourcing/tastings, private boundaries and no fabricated production.')
temp.cleanup()
