"""Native-format interoperability checks using fictional curves only."""
def run_artisan_checks(client,user):
    import ast,base64,hashlib,json,io,zipfile
    from django.core.exceptions import ValidationError
    from portal.artisan_profiles import derived,package_bytes,roast_title,preparation_name,ROAST_CODES,PACKAGE_ROAST_NAMES,row_fingerprint
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
    named={**description,'planned_batch_id':33}
    assert preparation_name(named)=='First Full City - Custom Drum 7 - Roast 33'
    for level,name in PACKAGE_ROAST_NAMES.items():
        assert preparation_name({**named,'roast_level':level,'mode':'second'})==f'Second {name} - Custom Drum 7 - Roast 33'
    assert preparation_name({**named,'roaster':'Bad:"/\\?*\r\nname'})=='First Full City - Bad name - Roast 33'
    assert preparation_name({**named,'roaster':' . '})=='First Full City - Roaster - Roast 33'
    for invalid in [{'mode':'either'},{'roast_level':'unknown'},{'planned_batch_id':True},{'planned_batch_id':'../1'},{'planned_batch_id':0}]:
        try:preparation_name({**named,**invalid})
        except ValidationError:pass
        else:raise AssertionError('Unsafe package name metadata accepted')
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
    from portal.models import ArtisanProfileSource,ArtisanProfileRevision,ArtisanPreparation,RoastPlan,RoastGroup,IncomingOrderLine,PlannedBatch
    with transaction.atomic():
        coffee=Coffee.objects.get(name='Demo Hearth');machine=Roaster.objects.get(name='Demo Small')
        plan=RoastPlan.objects.create(created_by=user,accepted_at=timezone.now())
        group=RoastGroup.objects.create(plan=plan,key='friendly-package-fixture',coffee=coffee,roast_level='Medium')
        IncomingOrderLine.objects.create(group=group,finished_oz=16,reference='Fictional filename test')
        row=PlannedBatch.objects.create(group=group,roaster=machine,green_oz=20)
        source=ArtisanProfileSource.objects.create(sha256=entry['sha256'],filename=entry['file'],original_b64=entry['original_b64'],inspection={'file':entry['file'],'sha256':entry['sha256']},created_by=user)
        configuration={**config,'name':'First Full City','state':'active','machines':[machine.name],'coffee_id':None,'roast_level':'Medium','mode':'either','note':''}
        revision=ArtisanProfileRevision.objects.create(profile_key='friendly-package-fixture',revision=1,configuration=configuration,source=source,created_by=user)
        snapshot={**description,'roaster':machine.name,'green_oz':'20','planned_batch_id':row.pk,'plan_id':plan.pk,'profile_key':revision.profile_key,'configuration':configuration,'fingerprint':row_fingerprint(row),'name':configuration['name'],'revision':1,'original_name':entry['file']}
        prepared=ArtisanPreparation.objects.create(revision=revision,planned_batch=row,snapshot=snapshot,created_by=user)
        url=f'/artisan/preparations/{prepared.pk}/download/'
        response=client.get(url);assert response.status_code==200,response.content
        name=preparation_name(snapshot)
        assert response['Content-Disposition']==f'attachment; filename="{name}.zip"'
        assert name.encode() in client.get(f'/artisan/preparations/{prepared.pk}/').content
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            assert manifest['package_name']==name and manifest['preparation_id']==str(prepared.pk)
            assert all('/' not in member and '\\' not in member for member in archive.namelist())
            for member,digest in manifest['files'].items():assert hashlib.sha256(archive.read(member)).hexdigest()==digest
            # A name with spaces works without changing helper paths or commands.
            import os,tempfile,subprocess
            from pathlib import Path
            if os.name=='nt':
                with tempfile.TemporaryDirectory(prefix='crema-friendly-artisan-') as folder:
                    target=Path(folder)/name;target.mkdir();archive.extractall(target)
                    check=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(target/'Prepare-Artisan.ps1'),'-ValidateOnly'],capture_output=True,text=True,timeout=30)
                    assert check.returncode==0,check.stderr
                    assert json.loads(check.stdout)['valid'] is True
        plan.version+=1;plan.save(update_fields=['version'])
        assert client.get(url).status_code==409,'Friendly filename bypassed stale preparation protection'
        transaction.set_rollback(True)
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
