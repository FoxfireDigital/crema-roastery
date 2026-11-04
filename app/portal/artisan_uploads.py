"""Private, confirmed Artisan imports and append-only batch documentation."""
import base64,copy,hashlib,uuid
from datetime import date
from django import forms
from django.core import signing
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from django.db import transaction,IntegrityError
from django.http import HttpResponse,HttpResponseForbidden,Http404
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods,require_GET,require_POST
from .models import ArtisanProfileSource,ArtisanProfileRevision,BatchArtisanLog,Batch,ArtisanPreparation,PlannedBatch
from .artisan_files import MAX_FILE,inspect,source_entry,bytes_for,curve,comparison
from .artisan_profiles import catalog,entry_for,library_entries,current,defaults,attachment

SALT='coffee-artisan-confirmed-upload-v1'

class UploadForm(forms.Form):
    document=forms.FileField(label='Artisan .alog file',widget=forms.ClearableFileInput(attrs={'accept':'.alog'}))
    def clean_document(self):
        file=self.cleaned_data['document']
        if not 0<file.size<=MAX_FILE:raise forms.ValidationError('Choose an .alog file no larger than 2 MB.')
        if not file.name.lower().endswith('.alog'):raise forms.ValidationError('Choose an Artisan .alog file.')
        return file

def save_source(raw,filename,user,reference=False):
    _,metadata=inspect(raw,filename,reference=reference)
    source,_=ArtisanProfileSource.objects.get_or_create(sha256=metadata['sha256'],defaults={'filename':metadata['file'],'original_b64':base64.b64encode(raw).decode(),'inspection':metadata,'created_by':user})
    return source

def make_ticket(source,user,purpose,target,expected):
    return signing.dumps({'source':str(source.pk),'actor':user.pk,'purpose':purpose,'target':str(target or ''),'expected':expected,'request':str(uuid.uuid4())},salt=SALT,compress=True)

def read_ticket(value,user,purpose,target):
    try:data=signing.loads(value,salt=SALT,max_age=3600)
    except (signing.BadSignature,TypeError):raise ValidationError('This preview expired or changed. Upload the file again.')
    if data.get('actor')!=user.pk or data.get('purpose')!=purpose or data.get('target')!=str(target or ''):raise ValidationError('This preview belongs to another upload or account.')
    return data,get_object_or_404(ArtisanProfileSource,pk=data['source'])

def source_raw(source):return bytes_for(source_entry(source,''))

def duplicate_entry(source):
    return next((e for e in library_entries() if e['sha256']==source.sha256),None)

@login_required
@require_http_methods(['GET','POST'])
def upload_profile(request,key=None):
    if not request.user.is_staff:return HttpResponseForbidden('Staff access is required.')
    target=entry_for(key) if key else None
    if key and not target:raise Http404
    latest=current(target) if target else None
    form=UploadForm(request.POST or None,request.FILES or None);error='';source=None;ticket='';status=200
    if request.method=='POST':
        try:
            if request.POST.get('action')=='preview':
                if not form.is_valid():return render(request,'portal/artisan_upload.html',{'form':form,'target':target},status=400)
                file=form.cleaned_data['document'];source=save_source(file.read(MAX_FILE+1),file.name,request.user,reference=True)
                ticket=make_ticket(source,request.user,'profile',key,latest.revision if latest else 0)
            elif request.POST.get('action')=='save':
                data,source=read_ticket(request.POST.get('ticket',''),request.user,'profile',key)
                if not request.POST.get('confirmed'):raise ValidationError('Confirm you reviewed the curve and its Charge / Drop points.')
                raw=source_raw(source);inspect(raw,source.filename,reference=True)
                name=request.POST.get('name','').strip();note=request.POST.get('note','').strip()
                if not 1<=len(name)<=120 or len(note)>1200:raise ValidationError('Use a name of 1–120 characters and notes of at most 1200 characters.')
                profile_key=key or hashlib.sha256(('uploaded:'+source.sha256).encode()).hexdigest()
                with transaction.atomic():
                    # The immutable source serializes repeated saves and edits to this upload.
                    ArtisanProfileSource.objects.select_for_update().get(pk=source.pk)
                    retry=ArtisanProfileRevision.objects.filter(upload_key=data['request']).first()
                    if retry:return redirect('/artisan/profiles/'+retry.profile_key+'/?revision='+str(retry.revision))
                    duplicate=duplicate_entry(source)
                    if not key and duplicate:return redirect('/artisan/profiles/'+duplicate['key']+'/')
                    entry=entry_for(profile_key);previous=current(entry) if entry else None
                    if (previous.revision if previous else 0)!=data['expected']:raise ValidationError('This profile changed after preview. Upload again against its latest revision.')
                    if target and entry['sha256']==source.sha256:return redirect('/artisan/profiles/'+profile_key+'/')
                    config=copy.deepcopy(previous.configuration) if previous else defaults(source_entry(source,profile_key))
                    config.update(name=name,note=note,state='review',charge=str(round_target(source.inspection['charge']['bt'])),drop=str(round_target(source.inspection['drop']['bt'])))
                    saved=ArtisanProfileRevision.objects.create(profile_key=profile_key,revision=(previous.revision if previous else 0)+1,configuration=config,source=source,upload_key=data['request'],created_by=request.user)
                return redirect('/artisan/profiles/'+profile_key+'/')
            else:raise ValidationError('Choose Preview file before saving.')
        except (ValidationError,IntegrityError) as exc:error=' '.join(exc.messages) if isinstance(exc,ValidationError) else 'Another upload was saved first. Reload the latest profile and review again.';status=409
    chart=comparison(curve(source_raw(source),source.filename)) if source else None
    return render(request,'portal/artisan_upload.html',{'form':form,'target':target,'source':source,'ticket':ticket,'curve_chart':chart,'error':error,'duplicate':duplicate_entry(source) if source else None},status=status)

def round_target(value):
    from .artisan_profiles import tenths
    return tenths(value)

def batch_stamp(batch):
    return hashlib.sha256(str([batch.pk,batch.coffee_id,batch.roaster_id,str(batch.date),str(batch.green_oz),str(batch.roasted_oz),str(batch.roasted_at),str(batch.removed_at),batch.merged_into_id]).encode()).hexdigest()

def attachable(batch):
    if batch.removed_at or batch.merged_into_id:raise ValidationError('Attach a log to the actual active batch, not an excluded or merged input.')
    if not batch.roasted_at and batch.roasted_oz is None:raise ValidationError('Record that this batch was roasted before attaching a completed log. The log will not mark it roasted for you.')

def reference_choices(batch):
    rows=list(PlannedBatch.all_objects.filter(batch=batch).values_list('pk',flat=True))
    result=[('','No reference comparison')]
    for prepared in ArtisanPreparation.objects.filter(planned_batch_id__in=rows)[:30]:
        s=prepared.snapshot;result.append(('prepared:'+str(prepared.pk),f"Prepared {s.get('name','reference')} · r{s.get('revision')} · {prepared.created_at:%Y-%m-%d}"))
    for entry in library_entries():
        rev=current(entry);config=rev.configuration if rev else defaults(entry)
        result.append(('revision:'+str(rev.pk) if rev else 'original:'+entry['key'],config['name']+' · '+('revision '+str(rev.revision) if rev else 'supplied original')))
    return result

def default_reference(batch):
    """Use the most recent preparation bound to this physical batch's row."""
    rows=PlannedBatch.all_objects.filter(batch=batch).values_list('pk',flat=True)
    for prepared in ArtisanPreparation.objects.filter(planned_batch_id__in=rows).order_by('-created_at','-pk'):
        snapshot=prepared.snapshot
        if snapshot.get('roaster')==batch.roaster.name and snapshot.get('coffee')==batch.coffee.name and snapshot.get('roast_level')==batch.roast_level:
            return 'prepared:'+str(prepared.pk)
    return ''


def resolve_reference(value,batch):
    if not value:return {},None,None
    kind,_,identifier=value.partition(':')
    if kind=='prepared':
        prepared=get_object_or_404(ArtisanPreparation,pk=identifier)
        if not PlannedBatch.all_objects.filter(pk=prepared.planned_batch_id,batch=batch).exists():raise ValidationError('Choose a preparation for this batch.')
        revision=prepared.revision;entry=entry_for(revision.profile_key,revision);config=prepared.snapshot['configuration']
    elif kind=='revision' and identifier.isdecimal():
        revision=get_object_or_404(ArtisanProfileRevision,pk=int(identifier));entry=entry_for(revision.profile_key,revision);config=revision.configuration
    elif kind=='original':
        entry=next((e for e in catalog()['profiles'] if e['key']==identifier),None)
        if not entry:raise ValidationError('Choose a reference from the library.')
        revision=None;config=defaults(entry)
    else:raise ValidationError('Choose a valid reference.')
    snapshot={'key':entry['key'],'sha256':entry['sha256'],'file':entry['file'],'name':config['name'],'configuration':copy.deepcopy(config),'revision':revision.revision if revision else 0,'source_id':entry.get('source_id')}
    return snapshot,entry,revision.source if revision and revision.source_id else None

def saved_reference(log):
    s=log.reference_snapshot
    if not s:return None
    if log.reference_source_id:entry=source_entry(log.reference_source,s['key'])
    else:entry=next((e for e in catalog()['profiles'] if e['key']==s['key']),None)
    if not entry or entry['sha256']!=s['sha256']:raise ValidationError('Saved reference checksum mismatch.')
    return curve(bytes_for(entry),entry['file'])


def batch_log_context(batch,page_number=None):
    """Inline previews use verified originals and the attachment's frozen reference."""
    from django.core.paginator import Paginator
    logs=batch.artisan_logs.select_related('source','reference_source','created_by','removed_by').order_by('-created_at','-pk')
    page=Paginator(logs,5).get_page(page_number)
    previews=[]
    for log in page:
        chart=None;error=''
        try:
            actual=curve(source_raw(log.source),log.source.filename)
            try:reference=saved_reference(log)
            except ValidationError:
                reference=None;error='The saved reference could not be verified. Only the uploaded roast is shown.'
            chart=comparison(actual,reference)
        except ValidationError:
            error='This stored curve could not be verified for preview. Review the log details before using it.'
        previews.append({'log':log,'curve_chart':chart,'error':error})
    return {'artisan_log_previews':previews,'artisan_log_page':page}

@login_required
@require_http_methods(['GET','POST'])
def upload_batch_log(request,pk):
    if not request.user.is_staff:return HttpResponseForbidden('Staff access is required.')
    batch=get_object_or_404(Batch.all_objects.select_related('coffee','roaster'),pk=pk)
    try:attachable(batch)
    except ValidationError as exc:return render(request,'portal/artisan_log_upload.html',{'batch':batch,'error':' '.join(exc.messages)},status=409)
    form=UploadForm(request.POST or None,request.FILES or None);source=None;ticket='';error='';status=200;selected=request.POST.get('reference',default_reference(batch));reference=None;reference_snapshot={};notes=request.POST.get('notes','')
    try:
        if request.method=='POST':
            if request.POST.get('action')=='preview':
                if not form.is_valid():return render(request,'portal/artisan_log_upload.html',{'batch':batch,'form':form,'reference_choices':reference_choices(batch)},status=400)
                file=form.cleaned_data['document'];source=save_source(file.read(MAX_FILE+1),file.name,request.user)
                ticket=make_ticket(source,request.user,'batch',pk,batch_stamp(batch))
            elif request.POST.get('action')=='attach':
                data,source=read_ticket(request.POST.get('ticket',''),request.user,'batch',pk)
                ticket=request.POST.get('ticket','')
                if not request.POST.get('confirmed'):raise ValidationError('Confirm this file records the selected batch and you reviewed its curve.')
                if len(notes)>1200:raise ValidationError('Keep notes within 1200 characters.')
                reference_snapshot,entry,ref_source=resolve_reference(selected,batch)
                with transaction.atomic():
                    batch=Batch.all_objects.select_for_update().get(pk=pk);attachable(batch)
                    if data['expected']!=batch_stamp(batch):raise ValidationError('Batch results changed after preview. Upload and review the current batch again.')
                    existing=BatchArtisanLog.objects.filter(batch=batch,source=source,removed_at__isnull=True).first()
                    if existing:return redirect('artisan_batch_log',log_id=existing.pk)
                    log=BatchArtisanLog.objects.create(batch=batch,source=source,reference_source=ref_source,reference_snapshot=reference_snapshot,notes=notes,created_by=request.user)
                return redirect('artisan_batch_log',log_id=log.pk)
            else:raise ValidationError('Preview the file before attaching it.')
        if selected:reference_snapshot,reference,_=resolve_reference(selected,batch)
    except (ValidationError,ValueError,IntegrityError) as exc:error=' '.join(exc.messages) if isinstance(exc,ValidationError) else 'Choose a valid reference and try again.';status=409
    actual=curve(source_raw(source),source.filename) if source else None
    ref=curve(bytes_for(reference),reference['file']) if reference else None
    return render(request,'portal/artisan_log_upload.html',{'batch':batch,'form':form,'source':source,'ticket':ticket,'notes':notes,'reference_choices':reference_choices(batch),'selected_reference':selected,'reference_snapshot':reference_snapshot,'curve_chart':comparison(actual,ref) if actual else None,'error':error,'date_mismatch':bool(source and source.inspection.get('date') and source.inspection['date']!=str(batch.date))},status=status)

@login_required
@require_GET
def batch_log_detail(request,log_id):
    if not request.user.is_staff:return HttpResponseForbidden('Staff access is required.')
    log=get_object_or_404(BatchArtisanLog.objects.select_related('batch__coffee','batch__roaster','source','reference_source','created_by','removed_by'),pk=log_id)
    raw=source_raw(log.source)
    actual=curve(raw,log.source.filename)
    from .artisan_files import decode_document
    from .cupping import artisan_flavors
    flavor_chart=artisan_flavors(decode_document(raw))
    from .batch_photos import photo_context
    return render(request,'portal/artisan_log.html',{**photo_context(log.batch),'log':log,'batch':log.batch,'curve_chart':comparison(actual,saved_reference(log)),'flavor_chart':flavor_chart})

@login_required
@require_GET
def batch_log_download(request,log_id):
    if not request.user.is_staff:return HttpResponseForbidden('Staff access is required.')
    log=get_object_or_404(BatchArtisanLog.objects.select_related('source'),pk=log_id)
    return attachment(source_raw(log.source),'batch-'+str(log.batch_id)+'-'+log.source.sha256[:12]+'.alog','application/octet-stream')

@login_required
@require_POST
def unlink_batch_log(request,log_id):
    if not request.user.is_staff:return HttpResponseForbidden('Staff access is required.')
    with transaction.atomic():
        log=get_object_or_404(BatchArtisanLog.objects.select_for_update(),pk=log_id)
        reason=request.POST.get('reason','').strip()
        if not 1<=len(reason)<=300:return HttpResponse('Enter a reason of 1–300 characters.',status=400)
        if not log.removed_at:log.removed_at=timezone.now();log.removed_by=request.user;log.removal_reason=reason;log.save(update_fields=['removed_at','removed_by','removal_reason'])
    return redirect('artisan_batch_log',log_id=log.pk)
