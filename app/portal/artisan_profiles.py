"""Versioned reference profiles; preparation never records production or controls a roaster."""
import ast,base64,copy,hashlib,io,json,zipfile
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction,IntegrityError
from django.http import HttpResponse,HttpResponseForbidden,Http404
from django.shortcuts import get_object_or_404,render,redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods,require_GET,require_POST
from .models import ArtisanProfileRevision,ArtisanPreparation,Coffee,PlannedBatch,ROAST_LEVELS
from .artisan_files import bytes_for,source_entry,decode_document,comparison,curve

ROOT=Path(__file__).resolve().parent
ALARM_KEYS={'alarmflags':'alarmflag','alarmguards':'alarmguard','alarmnegguards':'alarmnegguard','alarmtimes':'alarmtime','alarmoffsets':'alarmoffset','alarmconds':'alarmcond','alarmsources':'alarmsource','alarmtemperatures':'alarmtemperature','alarmactions':'alarmaction','alarmbeep':'alarmbeep','alarmstrings':'alarmstrings'}

@lru_cache(maxsize=1)
def catalog():
    data=json.loads((ROOT/'artisan_catalog.json').read_text(encoding='utf-8'))
    for item in data['profiles']:
        raw=base64.b64decode(item['original_b64'],validate=True)
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Profile original failed its integrity check.')
    return data

def entry_for(key,revision=None):
    selected=revision or ArtisanProfileRevision.objects.filter(profile_key=key).select_related('source').first()
    if selected and selected.source_id:return source_entry(selected.source,key)
    return next((x for x in catalog()['profiles'] if x['key']==key),None)

def library_entries():
    entries={x['key']:x for x in catalog()['profiles']};seen=set()
    for revision in ArtisanProfileRevision.objects.select_related('source').defer('source__original_b64'):
        if revision.profile_key in seen:continue
        seen.add(revision.profile_key)
        if revision.source_id:entries[revision.profile_key]=source_entry(revision.source,revision.profile_key)
    return list(entries.values())

def tenths(value):
    try:n=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError):raise ValidationError('Enter a finite Fahrenheit temperature.')
    if not n.is_finite() or not Decimal('32')<=n<=Decimal('600'):raise ValidationError('Enter a Fahrenheit target between 32.0 and 600.0.')
    return n.quantize(Decimal('.1'),rounding=ROUND_HALF_UP)

def defaults(entry):
    name=entry['file'].lower()
    return {'name':Path(entry['file']).stem,'state':'retired' if 'defunct' in name else 'trial' if 'trial' in name else 'review',
            'machines':[],'coffee_id':None,'roast_level':'','mode':'first' if Path(name).name.startswith('first ') else 'second' if Path(name).name.startswith('second ') else 'either',
            'charge':str(tenths(entry['charge']['bt'])) if entry.get('charge') and entry['charge'].get('bt') is not None else '',
            'drop':str(tenths(entry['drop']['bt'])) if entry.get('drop') and entry['drop'].get('bt') is not None else '', 'note':''}

def current(entry):return ArtisanProfileRevision.objects.filter(profile_key=entry['key']).first()

def alarms_for(configuration):
    charge=tenths(configuration['charge']);drop=tenths(configuration['drop'])
    if drop<=charge or drop+Decimal('.1')>600:raise ValidationError('Drop must exceed Charge and leave room for Off at Drop + 0.1°F.')
    # From START / CHARGE / DROP, with zero-based guards: Drop follows Charge,
    # and Off cannot run until the actual DROP event has been marked.
    return {'alarmflags':[1,1,1],'alarmguards':[-1,0,1],'alarmnegguards':[-1,-1,-1],
            'alarmtimes':[-1,0,6],'alarmoffsets':[0,0,0],'alarmconds':[1,1,1],
            'alarmsources':[1,1,1],'alarmtemperatures':[float(charge),float(drop),float(drop+Decimal('.1'))],
            'alarmactions':[16,13,15],'alarmbeep':[0,0,0],'alarmstrings':['Charge','Drop','Off']}

def derived(entry,configuration):
    original=bytes_for(entry);profile=decode_document(original)
    if not isinstance(profile,dict) or profile.get('mode')!='F':raise ValidationError('This profile needs a Fahrenheit review.')
    result=copy.deepcopy(profile);alarms=alarms_for(configuration)
    for external,internal in ALARM_KEYS.items():result[internal]=alarms[external]
    result['alarmsetlabel']='Crema — Charge / Drop / Off'
    # Change only embedded alarm fields; original curves, events and weights stay intact.
    return json.dumps(result,ensure_ascii=True,separators=(',',':')).encode(),json.dumps(alarms,separators=(',',':')).encode()

class ProfileForm(forms.Form):
    revision=forms.IntegerField(min_value=0,widget=forms.HiddenInput)
    name=forms.CharField(max_length=120,label='Display name')
    state=forms.ChoiceField(choices=[('review','Needs review'),('active','Approved for production'),('trial','Trial'),('retired','Retired')])
    machines=forms.MultipleChoiceField(choices=[],widget=forms.CheckboxSelectMultiple,required=False,label='Approved roasters')
    coffee=forms.ModelChoiceField(queryset=Coffee.objects.none(),required=False,label='Specific coffee (optional)')
    roast_level=forms.ChoiceField(choices=[('','Choose roast')]+ROAST_LEVELS,required=False,label='Roast level')
    mode=forms.ChoiceField(choices=[('first','First — cold / idle 10+ minutes'),('second','Second — warm / continuing'),('either','Either — choose deliberately')])
    charge=forms.DecimalField(decimal_places=1,max_digits=4,min_value=32,max_value=600,label='Charge target (°F)')
    drop=forms.DecimalField(decimal_places=1,max_digits=4,min_value=32,max_value=Decimal('599.9'),label='Drop target (°F)')
    note=forms.CharField(max_length=1200,required=False,widget=forms.Textarea,label='Notes / coffee exceptions')
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.fields['coffee'].queryset=Coffee.objects.order_by('name')
        from .models import Roaster
        self.fields['machines'].choices=[(r.name,r.name) for r in Roaster.objects.filter(active=True)]
        for name in ('charge','drop'):self.fields[name].widget.attrs['step']='0.1'
    def clean(self):
        data=super().clean()
        if data.get('charge') is not None and data.get('drop') is not None and data['drop']<=data['charge']:self.add_error('drop','Drop must be above Charge.')
        if data.get('state')=='active' and (not data.get('machines') or not data.get('roast_level')):raise forms.ValidationError('Choose the approved roaster(s) and roast level before approving production use.')
        return data

def configuration(data):
    return {'name':data['name'],'state':data['state'],'machines':sorted(data['machines']),'coffee_id':data['coffee'].pk if data['coffee'] else None,'roast_level':data['roast_level'],'mode':data['mode'],'charge':str(tenths(data['charge'])),'drop':str(tenths(data['drop'])),'note':data['note']}

def staff(request):return request.user.is_staff

@login_required
@require_GET
def profile_library(request):
    if not staff(request):return HttpResponseForbidden('Staff access is required.')
    latest={}
    for revision in ArtisanProfileRevision.objects.all():latest.setdefault(revision.profile_key,revision)
    items=[];query=request.GET.get('q','').strip().casefold();state=request.GET.get('state','')
    for entry in library_entries():
        rev=latest.get(entry['key']);config=rev.configuration if rev else defaults(entry)
        if query and query not in (entry['file']+' '+config['name']+' '+config['note']).casefold():continue
        if state and state!=config['state']:continue
        items.append({'entry':entry,'config':config,'revision':rev.revision if rev else 0,'off':tenths(config['drop'])+Decimal('.1') if config['drop'] else None})
    return render(request,'portal/artisan_library.html',{'profiles':items,'q':request.GET.get('q',''),'state':state,'archive_sha':catalog().get('archive_sha256','')})

@login_required
@require_http_methods(['GET','POST'])
def profile_detail(request,key):
    if not staff(request):return HttpResponseForbidden('Staff access is required.')
    entry=entry_for(key)
    if entry is None:from django.http import Http404;raise Http404
    rev=current(entry);config=rev.configuration if rev else defaults(entry);initial={**config,'coffee':config['coffee_id'],'revision':rev.revision if rev else 0}
    readonly=False
    if request.method=='GET' and request.GET.get('revision'):
        number=request.GET['revision']
        if not number.isdecimal():return HttpResponse('Choose a valid revision.',status=400)
        rev=get_object_or_404(ArtisanProfileRevision,profile_key=key,revision=int(number));entry=entry_for(key,rev);config=rev.configuration
        initial={**config,'coffee':config['coffee_id'],'revision':rev.revision};readonly=True
    form=ProfileForm(request.POST if request.method=='POST' else None,initial=initial);status=200
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                # Serialize approvals, including the first revision; originals stay static.
                from django.contrib.auth import get_user_model
                get_user_model().objects.select_for_update().get(pk=request.user.pk)
                latest=current(entry)
                if form.cleaned_data['revision']!=(latest.revision if latest else 0):raise ValidationError('This profile changed in another tab. Reload before saving.')
                saved=configuration(form.cleaned_data);derived(entry,saved)
                if not latest or latest.configuration!=saved:ArtisanProfileRevision.objects.create(profile_key=key,revision=(latest.revision if latest else 0)+1,configuration=saved,source=latest.source if latest else None,created_by=request.user)
            return redirect('artisan_profile',key=key)
        except (ValidationError,IntegrityError) as exc:form.add_error(None,exc.messages if isinstance(exc,ValidationError) else 'Another person saved this profile. Reload and review.');status=409
    elif request.method=='POST':status=400
    chart=comparison(curve(bytes_for(entry),entry['file']))
    return render(request,'portal/artisan_profile.html',{'entry':entry,'config':config,'form':form,'revision':rev,'readonly_revision':readonly,'curve_chart':chart,'off':tenths(config['drop'])+Decimal('.1') if config['drop'] else None,'revisions':ArtisanProfileRevision.objects.filter(profile_key=key).select_related('created_by')[:12]},status=status)

def attachment(content,name,mime):
    response=HttpResponse(content,content_type=mime);response['Content-Disposition']='attachment; filename="'+name+'"';response['Cache-Control']='private, no-store';response['X-Content-Type-Options']='nosniff';return response

@login_required
@require_GET
def profile_download(request,key,kind):
    if not staff(request):return HttpResponseForbidden('Staff access is required.')
    from django.http import Http404
    entry=entry_for(key)
    if entry is None:raise Http404
    rev=current(entry);config=rev.configuration if rev else defaults(entry)
    if request.GET.get('revision'):
        number=request.GET['revision']
        if not number.isdecimal():return HttpResponse('Choose a valid revision.',status=400)
        rev=get_object_or_404(ArtisanProfileRevision,profile_key=key,revision=int(number));entry=entry_for(key,rev);config=rev.configuration
    if kind=='original':return attachment(bytes_for(entry),'original-'+key[:12]+'.alog','application/octet-stream')
    profile,alarms=derived(entry,config)
    if kind=='profile':return attachment(profile,'reference-'+key[:12]+'.alog','application/octet-stream')
    if kind=='alarms':return attachment(alarms,'alarms-'+key[:12]+'.alrm','application/octet-stream')
    raise Http404

def eligible(entry,revision,row,mode):
    c=revision.configuration
    if c['state']!='active' or row.roaster.name not in c['machines'] or c['roast_level']!=row.group.roast_level or c['mode'] not in [mode,'either']:return False
    if c['coffee_id'] is not None and c['coffee_id']!=row.group.coffee_id:return False
    # A generic curve may be chosen for an experiment, but no guess is made automatically.
    return True

def row_fingerprint(row):
    batch=row.batch if row.batch_id else None
    weight=Decimal(str(batch.green_oz if batch else row.green_oz)).quantize(Decimal('.01'))
    raw=[row.pk,row.group.plan.version,row.group.coffee_id,row.group.roast_level,str(row.group.target_finish_temp_f),row.roaster_id,str(weight),row.batch_id,str(batch.roasted_at) if batch else None,str(batch.roasted_oz) if batch else None]
    return hashlib.sha256(json.dumps(raw).encode()).hexdigest()

def preparation_row(pk,lock=False):
    query=PlannedBatch.objects
    if lock:query=query.select_for_update(of=('self',))
    return get_object_or_404(query.select_related('roaster','batch','group__coffee','group__plan'),pk=pk)

def usable_row(row):
    if row.group.plan.removed_at or row.group.plan.closed_at or not row.group.plan.accepted_at or not row.group.orders.exists():raise ValidationError('Use an accepted, active plan with coffee orders.')
    if row.batch_id and (row.batch.removed_at or row.batch.merged_into_id or row.batch.roasted_at or row.batch.roasted_oz is not None):raise ValidationError('This roast already has a result or was removed. Prepare only an unroasted load.')
    if not row.roaster.active:raise ValidationError('This roaster is inactive.')
    green=row.batch.green_oz if row.batch_id else row.green_oz
    if green<=0 or not row.roaster.capacity or green>row.roaster.capacity:raise ValidationError('Check the green load and roaster capacity before preparing.')

@login_required
@require_http_methods(['GET','POST'])
def prepare_artisan(request,pk):
    if not staff(request):return HttpResponseForbidden('Staff access is required.')
    row=preparation_row(pk);error='';status=200
    mode=request.POST.get('mode','first') if request.method=='POST' else request.GET.get('mode','first')
    if mode not in ['first','second']:mode='first'
    try:usable_row(row)
    except ValidationError as exc:error=' '.join(exc.messages);status=409
    options=[]
    for entry in library_entries():
        revision=current(entry)
        if revision and eligible(entry,revision,row,mode):options.append({'entry':entry,'revision':revision,'config':revision.configuration})
    if request.method=='POST' and not error:
        try:
            if not request.POST.get('confirmed'):raise ValidationError('Confirm the machine, First/Second choice and temperatures.')
            with transaction.atomic():
                from .models import RoastPlan
                RoastPlan.objects.select_for_update().get(pk=row.group.plan_id)
                row=preparation_row(pk,lock=True);usable_row(row)
                if request.POST.get('fingerprint')!=row_fingerprint(row):raise ValidationError('The load changed. Reload and review the current weight and roast.')
                choice=request.POST.get('profile','')
                if not choice.isdecimal():raise ValidationError('Choose an approved profile.')
                revision=get_object_or_404(ArtisanProfileRevision,pk=int(choice))
                entry=entry_for(revision.profile_key)
                if not entry or current(entry).pk!=revision.pk or not eligible(entry,revision,row,mode):raise ValidationError('Choose a current approved profile for this roast, roaster and session.')
                c=copy.deepcopy(revision.configuration)
                requested=row.group.target_finish_temp_f
                # Explicit custom finish targets always replace the reference drop target.
                if requested is not None:c['drop']=str(tenths(requested))
                profile,alarms=derived(entry,c)
                snapshot={'profile_key':entry['key'],'original_name':entry['file'],'original_sha256':entry['sha256'],'revision':revision.revision,'name':c['name'],'mode':mode,'roaster':row.roaster.name,'coffee':row.group.coffee.name,'roast_level':row.group.roast_level,'green_oz':str(row.batch.green_oz if row.batch_id else row.green_oz),'requested_drop':str(requested) if requested is not None else None,'charge':c['charge'],'drop':c['drop'],'off':str(tenths(c['drop'])+Decimal('.1')),'plan_id':row.group.plan_id,'planned_batch_id':row.pk,'fingerprint':row_fingerprint(row),'configuration':c}
                prepared=ArtisanPreparation.objects.create(revision=revision,planned_batch=row,snapshot=snapshot,created_by=request.user)
            return redirect('artisan_preparation',preparation_id=prepared.pk)
        except (ValidationError,ValueError) as exc:error=' '.join(exc.messages) if isinstance(exc,ValidationError) else 'Choose a valid profile.';status=409
    return render(request,'portal/artisan_prepare.html',{'row':row,'mode':mode,'options':options,'error':error,'fingerprint':row_fingerprint(row)},status=status)

@login_required
@require_GET
def preparation_detail(request,preparation_id):
    if not staff(request):return HttpResponseForbidden('Staff access is required.')
    prepared=get_object_or_404(ArtisanPreparation,pk=preparation_id)
    stale=not preparation_current(prepared)
    return render(request,'portal/artisan_prepared.html',{'prepared':prepared,'s':prepared.snapshot,'stale':stale})

def preparation_current(prepared):
    try:
        row=preparation_row(prepared.planned_batch_id);usable_row(row)
        entry=entry_for(prepared.snapshot['profile_key'])
        return bool(entry and row_fingerprint(row)==prepared.snapshot['fingerprint'] and current(entry).pk==prepared.revision_id)
    except (ValidationError,AttributeError):return False

def package_bytes(entry,configuration,description,prepared=None):
    profile,alarms=derived(entry,configuration)
    payload={'reference.alog':profile,'alarms.alrm':alarms}
    manifest={**description,'format':1,'created_utc':timezone.now().isoformat(),'files':{name:hashlib.sha256(content).hexdigest() for name,content in payload.items()},'preparation_id':str(prepared.pk) if prepared else None}
    payload['manifest.json']=json.dumps(manifest,indent=2).encode()
    payload['Prepare-Artisan.ps1']=(ROOT/'artisan_helper.ps1').read_bytes()
    payload['Prepare-Artisan.cmd']=b'@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Prepare-Artisan.ps1"\r\n'
    payload['READ-ME.txt']=("Extract this complete folder on the Windows roasting computer, then run Prepare-Artisan.cmd. It reuses the existing main Artisan instance or starts Artisan if closed. Confirm idle state and the connected roaster before sending. It never starts monitoring, recording or a roast. A sent request is not a verified load: inspect the background and Config > Alarms in Artisan.\n\nEnable Config > Alarms > Load from background when using embedded alarms. The helper also sends the explicit paired .alrm file. Targets are BT rises ABOVE the displayed value, as supported by Artisan, not a guarantee of an exact crossing sample. Off is Artisan's monitoring action, not a guaranteed physical heater shutdown.\n\nSaved reference weights are original metadata. Use the portal's displayed green load; do not copy reference weights. First applies after this particular machine was idle for at least 10 minutes; Second is for continuing warm roasting.\n\nIf the plan/profile changes after downloading, discard this folder and prepare again. Packages do not receive live updates. No portal password or Shopify credential is included.\n").encode()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,content in payload.items():archive.writestr(name,content)
    return buffer.getvalue()

@login_required
@require_GET
def preparation_download(request,preparation_id):
    if not staff(request):return HttpResponseForbidden('Staff access is required.')
    prepared=get_object_or_404(ArtisanPreparation,pk=preparation_id)
    if not preparation_current(prepared):return HttpResponse('This load or profile changed. Prepare it again before downloading.',status=409)
    entry=entry_for(prepared.snapshot['profile_key'])
    return attachment(package_bytes(entry,prepared.snapshot['configuration'],prepared.snapshot,prepared),'artisan-prepare-'+str(prepared.pk)+'.zip','application/zip')

@login_required
@require_GET
def all_alarm_copies(request):
    if not staff(request):return HttpResponseForbidden('Staff access is required.')
    output=io.BytesIO();manifest=[]
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for entry in library_entries():
            rev=current(entry);config=rev.configuration if rev else defaults(entry);profile,alarms=derived(entry,config);folder=entry['key'][:16]
            archive.writestr(folder+'/reference.alog',profile);archive.writestr(folder+'/alarms.alrm',alarms)
            manifest.append({'folder':folder,'original':entry['file'],'original_sha256':entry['sha256'],'configuration':config,'derived_sha256':hashlib.sha256(profile).hexdigest(),'off':str(tenths(config['drop'])+Decimal('.1'))})
        archive.writestr('manifest.json',json.dumps(manifest,indent=2))
        archive.writestr('READ-ME.txt','Derived review copies with Charge / Drop / Off alarms. Trial and retired status is preserved in manifest.json. Do not assume these are approved production defaults. Original curves/weights/events are preserved; only embedded alarms are replaced. Load from Background must be enabled to use embedded alarms. Explicit .alrm files are included. Off changes Artisan monitoring, not a guaranteed roaster heater shutdown.\n')
    return attachment(output.getvalue(),'artisan-profile-alarm-copies.zip','application/zip')

@login_required
@require_GET
def supplied_alarm_download(request):
    if not staff(request):return HttpResponseForbidden('Staff access is required.')
    if not catalog()['alarms']:raise Http404('No bundled alarm schedule. Upload your own reference and prepare alarms after review.')
    item=catalog()['alarms'][0];raw=base64.b64decode(item['original_b64'],validate=True)
    if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValidationError('Original alarm checksum mismatch.')
    return attachment(raw,'supplied-original.alrm','application/octet-stream')
