"""Native-format interoperability checks using fictional curves only."""
def run_artisan_checks(client,user):
    import ast,base64,hashlib,json,io,zipfile
    from django.core.exceptions import ValidationError
    from portal.artisan_profiles import derived,package_bytes,roast_title,ROAST_CODES
    from portal.artisan_files import decode_document
    original={'mode':'F','timex':[0,60,120,180],'temp1':[340,350,370,390],'temp2':[320,330,360,400],'extratemp1':[],'extratemp2':[],'timeindex':[0,1,2,0,0,0,3,0],
              'title':'Fictional native reference','flag':True,'optional':None,'disabled':False,'metadata':('reference',None)}
    raw=repr(original).encode();entry={'original_b64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest(),'file':'Fictional reference.alog'}
    config={'charge':'320.0','drop':'400.0'}
    profile,alarm=derived(entry,config)
    # This is the actual file grammar accepted by Artisan 3.1's reader.
    loaded=ast.literal_eval(profile.decode('utf-8'));alarms=ast.literal_eval(alarm.decode('utf-8'))
    for key,value in original.items():assert loaded[key]==value,(key,'source data changed')
    assert loaded['alarmtemperature']==[320.0,400.0,400.1] and alarms['alarmactions']==[16,13,15]
    assert loaded['alarmguard']==[-1,0,1] and decode_document(profile)==loaded
    try:ast.literal_eval(json.dumps(original))
    except (ValueError,SyntaxError):pass
    else:raise AssertionError('Regression fixture must reproduce the old JSON/native incompatibility')
    description={'coffee':'Demo Hearth','green_oz':'40','roast_level':'Medium','roaster':'Custom Drum 7','mode':'first','charge':'320.0','drop':'400.0','off':'400.1'}
    assert roast_title(description)=='Demo Hearth 40.0oz 1 FC'
    for level,code in ROAST_CODES.items():
        assert roast_title({**description,'roast_level':level,'mode':'second','green_oz':'39.85'})==f'Demo Hearth 39.9oz 2 {code}'
    for invalid in [{'green_oz':'NaN'},{'green_oz':'0'},{'mode':'either'},{'roast_level':'unknown'},{'coffee':'unsafe\nname'}]:
        try:roast_title({**description,**invalid})
        except ValidationError:pass
        else:raise AssertionError('Invalid title metadata accepted')
    with zipfile.ZipFile(io.BytesIO(package_bytes(entry,config,description))) as z:
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['profile_format']=='artisan-python-literal'
        assert manifest['roast_title']=='Demo Hearth 40.0oz 1 FC'
        assert z.read('roast-title.txt').decode().strip()==manifest['roast_title']
        for name,sha in manifest['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==sha
        assert ast.literal_eval(z.read('reference.alog').decode())['title']==manifest['roast_title']
        assert ast.literal_eval(raw.decode())==original
        assert manifest['files']['reference.alog']==hashlib.sha256(z.read('reference.alog')).hexdigest()
        assert ast.literal_eval(z.read('reference.alog').decode())['timex']==original['timex']
        helper=z.read('Prepare-Artisan.ps1').decode();assert "@('Large roaster','Small roaster')" not in helper and 'Get-Process -Name artisan' in helper
    incomplete={**original};incomplete.pop('temp1');bad=repr(incomplete).encode()
    broken={**entry,'original_b64':base64.b64encode(bad).decode(),'sha256':hashlib.sha256(bad).hexdigest()}
    try:derived(broken,config)
    except ValidationError:pass
    else:raise AssertionError('Incomplete background accepted')
    # Attach through the real signed preview/confirm flow and preserve every production measurement.
    from django.db import transaction
    from django.utils import timezone
    from django.core.files.uploadedfile import SimpleUploadedFile
    from portal.models import Batch,Coffee,Roaster,BatchArtisanLog
    from portal.roast_sheet import artisan_upload_url
    with transaction.atomic():
        batch=Batch.objects.create(date=timezone.localdate(),operator=user,coffee=Coffee.objects.get(name='Demo Hearth'),roaster=Roaster.objects.first(),green_oz=20,roasted_oz=17,roasted_at=timezone.now(),roast_level='Medium')
        url=artisan_upload_url(batch);assert url==f'/batches/{batch.pk}/artisan/upload/'
        before=(batch.green_oz,batch.roasted_oz,batch.roasted_at)
        preview=client.post(url,{'action':'preview','document':SimpleUploadedFile('finished.alog',raw)})
        assert preview.status_code==200,preview.content
        ticket=preview.context['ticket'];assert ticket and not BatchArtisanLog.objects.filter(batch=batch).exists()
        assert client.post(url,{'action':'attach','ticket':ticket}).status_code==409
        saved=client.post(url,{'action':'attach','ticket':ticket,'confirmed':'on','notes':'Fictional review note'})
        assert saved.status_code==302,saved.content
        log=BatchArtisanLog.objects.get(batch=batch)
        assert client.get(f'/artisan/logs/{log.pk}/').status_code==200
        assert client.get(f'/artisan/logs/{log.pk}/download/').content==raw
        assert client.post(url,{'action':'attach','ticket':ticket,'confirmed':'on'}).status_code==302
        assert BatchArtisanLog.objects.filter(batch=batch).count()==1
        batch.refresh_from_db();assert before==(batch.green_oz,batch.roasted_oz,batch.roasted_at)
        batch.roasted_at=None;batch.roasted_oz=None;assert artisan_upload_url(batch)==''
        transaction.set_rollback(True)
    print('PASS: Artisan-native Python literal files, booleans/null/tuples preserved, guarded alarms, complete background requirements and configurable machine names.')
