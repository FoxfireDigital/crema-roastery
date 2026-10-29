"""Native-format interoperability checks using fictional curves only."""
def run_artisan_checks():
    import ast,base64,hashlib,json,io,zipfile
    from django.core.exceptions import ValidationError
    from portal.artisan_profiles import derived,package_bytes
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
    description={'roaster':'Custom Drum 7','mode':'first','charge':'320.0','drop':'400.0','off':'400.1'}
    with zipfile.ZipFile(io.BytesIO(package_bytes(entry,config,description))) as z:
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['profile_format']=='artisan-python-literal'
        assert manifest['files']['reference.alog']==hashlib.sha256(z.read('reference.alog')).hexdigest()
        assert ast.literal_eval(z.read('reference.alog').decode())['timex']==original['timex']
        helper=z.read('Prepare-Artisan.ps1').decode();assert "@('Large roaster','Small roaster')" not in helper and 'Get-Process -Name artisan' in helper
    incomplete={**original};incomplete.pop('temp1');bad=repr(incomplete).encode()
    broken={**entry,'original_b64':base64.b64encode(bad).decode(),'sha256':hashlib.sha256(bad).hexdigest()}
    try:derived(broken,config)
    except ValidationError:pass
    else:raise AssertionError('Incomplete background accepted')
    print('PASS: Artisan-native Python literal files, booleans/null/tuples preserved, guarded alarms, complete background requirements and configurable machine names.')
