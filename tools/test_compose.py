"""Disposable Linux Compose installation and backup/restore QA; fictional data only."""
import argparse,os,json,secrets,tempfile,subprocess,time,shutil,urllib.parse,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--image',required=True,help='Already built generic image; never a customer image')
parser.add_argument('--revision',required=True)
parser.add_argument('--output',required=True,type=Path)
args=parser.parse_args()
if os.name!='posix' or not Path('/tmp').is_dir():parser.error('This QA tool currently supports Linux Docker hosts only.')
if not re.fullmatch(r'[a-f0-9]{40}(?:-dirty)?',args.revision):parser.error('Use an explicit source commit identity.')
if not args.image or args.image.startswith('-'):parser.error('Use an explicit built image name.')
args.output=args.output.resolve()
SOURCE_COMMIT=args.revision
token=secrets.token_hex(6);project='crematrial_'+token;image='local/crema-yaml-trial:'+token
root=Path(tempfile.mkdtemp(prefix='crema-yaml-trial-',dir='/tmp')).resolve()
assert root.parent==Path('/tmp') and root.name.startswith('crema-yaml-trial-')
started=False;cleanup_ok=False
def run(args,*,input=None,timeout=180):
    value=subprocess.run(args,cwd=root,input=input,capture_output=True,text=True,timeout=timeout)
    if value.returncode:raise RuntimeError('Trial command failed: '+' '.join(args[:2])+'\n'+value.stderr[-1800:])
    return value.stdout.strip()
def wait_health(service):
    for _ in range(45):
        cid=run(cp+['ps','-q',service])
        if cid:
            info=json.loads(run(['docker','inspect',cid]))[0]
            if info['State'].get('Health',{}).get('Status')=='healthy':return cid
        time.sleep(2)
    raise RuntimeError('Trial service did not become healthy: '+service)
def web_python(code):return run(cp+['exec','-T','web','python','-'],input=code)
try:
    shutil.copytree(ROOT,root,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','__pycache__','*.pyc','image-review','deployment-review'))
    cp=['docker','compose','-p',project,'-f',str(root/'compose.yaml')]
    engine=run(['docker','compose','version','--short'])
    run(cp+['config','--quiet'])
    # Keep the supplied YAML immutable; render a local-only variant for this host.
    config=json.loads(run(cp+['config','--format','json']))
    for service in ['initialize','web','worker']:config['services'][service]['image']=image
    for service,limit in [('initialize','256m'),('postgres','512m'),('web','768m'),('worker','256m'),('proxy','256m')]:
        config['services'][service].update(mem_limit=limit,cpus=1)
    for service in ['web','worker']:
        config['services'][service]['environment']['PORTAL_BASE_URL']='https://crema-qa.localhost'
        config['services'][service]['environment']['PORTAL_TIME_ZONE']='America/New_York'
    config['services']['proxy']['environment']['PORTAL_DOMAIN']='crema-qa.localhost'
    config['services']['proxy']['ports']=[{'target':443,'published':'0','host_ip':'127.0.0.1','protocol':'tcp'}]
    config['configs']['caddyfile']['content']='{\n admin off\n auto_https disable_redirects\n}\nhttps://crema-qa.localhost {\n tls internal\n reverse_proxy web:8000\n}\n'
    config.setdefault('networks',{}).setdefault('default',{})['internal']=True
    # Only the proxy gets a routable bridge for loopback publishing. Backend stays isolated.
    config['networks']['front']={'internal':False}
    config['services']['proxy']['networks']={'default':{},'front':{}}
    # Canonical project labels would otherwise use the source YAML's project name.
    config['name']=project
    for key in ['volumes','networks']:
        for name,definition in config[key].items():definition['name']=project+'_'+name
    for definition in config.get('configs',{}).values():definition.pop('name',None)
    local=root/'compose.local.yaml';local.write_text(json.dumps(config))
    cp=['docker','compose','-p',project,'-f',str(local)]
    rendered=json.loads(run(cp+['config','--format','json']))
    assert all(p['host_ip']=='127.0.0.1' for service in rendered['services'].values() for p in service.get('ports',[]))
    version=re.search(r'x-portal-image: &portal-image crema:([a-z0-9.-]+)',(root/'compose.yaml').read_text()).group(1)
    run(['docker','tag',args.image,image])
    image_review={};components=None
    if (root/'tools/verify_image.py').exists():
        output=root/'image-review'
        check=run(['python3',str(root/'tools/verify_image.py'),'--image',image,'--version',version,'--revision',SOURCE_COMMIT,'--output',str(output)],timeout=300)
        image_review=json.loads((output/'image-verification.json').read_text())
        components=json.loads((output/'components.json').read_text())
        print('PASS: offline generic image inspection.',flush=True)
    started=True;run(cp+['up','-d'],timeout=180)
    web=wait_health('web');db=wait_health('postgres')
    proxy=run(cp+['ps','-q','proxy'])
    inspector=json.loads(run(['docker','inspect',web]))[0]
    assert inspector['Config']['User']=='10001:10001'
    assert not inspector['HostConfig']['PortBindings']
    for svc in ['web','worker','postgres','initialize']:
        cid=run(cp+['ps','-aq',svc]);info=json.loads(run(['docker','inspect',cid]))[0]
        assert all(m.get('Name','').startswith(project+'_') for m in info['Mounts'] if m['Type']=='volume')
    fresh=web_python("import os,json;os.environ.setdefault('DJANGO_SETTINGS_MODULE','project_settings');import django;django.setup();from portal.models import Coffee,Batch,ImportOrder;from django.contrib.auth import get_user_model;print(json.dumps({'coffees':Coffee.objects.count(),'batches':Batch.all_objects.count(),'orders':ImportOrder.objects.count(),'users':get_user_model().objects.count()}))")
    assert all(v==0 for v in json.loads(fresh).values())
    keycode="from pathlib import Path;import hashlib;print(hashlib.sha256(b''.join((Path('/run/roastery-secrets')/n).read_bytes() for n in ['django','postgres'])).hexdigest())"
    keys=web_python(keycode)
    rerun=run(cp+['run','--rm','-T','--no-deps','initialize'])
    assert 'Existing instance keys retained' in rerun and web_python(keycode)==keys
    # Run the full suite in a separate database so the primary trial stays empty.
    run(cp+['exec','-T','postgres','createdb','-U','coffee','coffee_regression'])
    code="import os,sys;sys.path.insert(0,'/release/tools');os.environ.update(PORTAL_LOCAL_DEVELOPMENT='1',PORTAL_BASE_URL='http://localhost');import project_settings,runpy;project_settings.DATABASES['default']['NAME']='coffee_regression';runpy.run_path('/release/tools/test_release.py',run_name='__main__')"
    regress=run(cp+['run','--rm','-T','-e','PORTAL_RELEASE_QA_DISPOSABLE=1','-e','PORTAL_APP_ROOT=/srv','-v',str(root/'tools')+':/release/tools:ro','web','python','-c',code],timeout=240)
    assert 'PASS: empty install' in regress
    print('PASS: fresh empty install, generated keys retained, full PostgreSQL regression suite.',flush=True)
    for _ in range(15):
        proxy_info=json.loads(run(['docker','inspect',proxy]))[0]
        ports=proxy_info['NetworkSettings'].get('Ports',{}).get('443/tcp')
        if proxy_info['State']['Status']=='running' and ports:break
        time.sleep(1)
    else:raise RuntimeError('Local proxy did not publish HTTPS: '+json.dumps({'state':proxy_info['State']['Status'],'bindings':proxy_info['HostConfig'].get('PortBindings'),'ports':proxy_info['NetworkSettings'].get('Ports')})+' '+run(cp+['logs','--tail','15','proxy'])[-1800:])
    port=ports[0]
    assert port['HostIp']=='127.0.0.1'
    ca=root/'trial-ca.crt'
    for _ in range(20):
        certificate=subprocess.run(['docker','exec',proxy,'cat','/data/caddy/pki/authorities/local/root.crt'],capture_output=True,text=True)
        if certificate.returncode==0:ca.write_text(certificate.stdout);break
        time.sleep(1)
    else:raise RuntimeError('Trial TLS authority did not initialize.')
    origin='https://crema-qa.localhost'
    curl=['curl','--noproxy','*','--silent','--show-error','--max-time','20','--cacert',str(ca),'--connect-to','crema-qa.localhost:443:127.0.0.1:'+port['HostPort']]
    assert run(curl+['-o','/dev/null','-w','%{http_code}',origin+'/healthz/'])=='200'
    password=secrets.token_urlsafe(32)
    web_python("import os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','project_settings');import django;django.setup();from django.contrib.auth import get_user_model;get_user_model().objects.create_superuser('trial-owner','',"+repr(password)+")")
    jar=root/'trial-cookies';headers=root/'headers'
    page=run(curl+['-c',str(jar),'-D',str(headers),origin+'/login/'])
    csrf=re.search('name="csrfmiddlewaretoken" value="([^"]+)"',page).group(1)
    assert 'secure' in headers.read_text().lower() and 'content-security-policy:' in headers.read_text().lower()
    body=urllib.parse.urlencode({'username':'trial-owner','password':password,'csrfmiddlewaretoken':csrf})
    status=run(curl+['-b',str(jar),'-c',str(jar),'-H','Origin: '+origin,'-H','Referer: '+origin+'/login/','-H','Content-Type: application/x-www-form-urlencoded','--data-binary','@-','-o','/dev/null','-w','%{http_code}',origin+'/login/'],input=body)
    assert status=='302','Trial login did not complete.'
    page=run(curl+['-b',str(jar),origin+'/stores/'])
    assert 'Your marketplaces' in page and 'trial-owner' in page
    csrf=re.search('name="csrfmiddlewaretoken" value="([^"]+)"',page).group(1)
    stamp=re.search('name="selection_token" value="([^"]+)"',page).group(1)
    data=urllib.parse.urlencode({'action':'marketplaces','csrfmiddlewaretoken':csrf,'selection_token':stamp,'marketplaces':'manual'})
    status=run(curl+['-b',str(jar),'-c',str(jar),'-H','Origin: '+origin,'-H','Referer: '+origin+'/stores/','-H','Content-Type: application/x-www-form-urlencoded','--data-binary','@-','-o','/dev/null','-w','%{http_code}',origin+'/stores/'],input=data)
    assert status=='302'
    assert 'Manual orders / CSV only' in run(curl+['-b',str(jar),origin+'/stores/'])
    denied=run(curl+['-b',str(jar),'-H','Content-Type: application/x-www-form-urlencoded','--data','action=marketplaces','-o','/dev/null','-w','%{http_code}',origin+'/stores/'])
    assert denied=='403'
    run(cp+['exec','-T','web','python','manage.py','portal_demo','--owner','trial-owner'])
    countcode="import os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','project_settings');import django;django.setup();from portal.models import Coffee;print(Coffee.objects.count())"
    assert web_python(countcode)=='7'
    run(cp+['restart','postgres','web','worker'],timeout=120);wait_health('postgres');wait_health('web')
    assert web_python(keycode)==keys and web_python(countcode)=='7'
    assert run(curl+['-b',str(jar),'-o','/dev/null','-w','%{http_code}',origin+'/stores/'])=='200'
    from backup_rehearsal import rehearse
    recovery=rehearse(cp,root,config,password)
    report={'result':'passed','sourceCommit':SOURCE_COMMIT,'composeVersion':engine,'executionHost':'Linux Docker engine','primaryYAMLValidated':True,'localVariantChanges':['unique project/image/volume names','loopback-only dynamic HTTPS port','local TLS authority explicitly trusted by test client','internal network and resource limits','trial origin/timezone'],'emptyInstall':json.loads(fresh),'nonRootApp':True,'postgresRegression':True,'proxyTLSVerified':True,'loginAndCSRFSave':True,'invalidCSRFRejected':True,'marketplaceChoiceSaved':True,'restartRetainsKeysAndData':True,'productionProjectChanged':False,'yaml':local.read_text(),'loopbackPort':port['HostPort']}
    report['backupRestore']=recovery
    if image_review:report['imageReview']=image_review
    print('PASS: local HTTPS proxy, real login, CSRF-protected marketplace save, restart persistence.',flush=True)
finally:
    if started:
        assert project.startswith('crematrial_') and len(token)==12
        removed=subprocess.run(cp+['down','--volumes','--remove-orphans'],cwd=root,capture_output=True,text=True,timeout=120)
        cleanup_ok=removed.returncode==0
        print('Trial-only containers and volumes removed: '+str(cleanup_ok),flush=True)
    assert root.parent==Path('/tmp') and root.name.startswith('crema-yaml-trial-')
    shutil.rmtree(root)
    subprocess.run(['docker','image','rm',image],capture_output=True,text=True,timeout=60)
if 'report' in locals():
    report['trialContainersAndVolumesRemoved']=cleanup_ok
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'deployment-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    if components:(args.output/'components.json').write_text(json.dumps(components,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key!='yaml'}),flush=True)
