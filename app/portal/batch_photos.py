"""Optional still photographs. They never update production, inventory or hours."""
import hashlib,io,json,uuid,warnings
from PIL import Image,ImageOps,UnidentifiedImageError
from django import forms
from django.core import signing
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from django.db import transaction,IntegrityError
from django.http import HttpResponse,HttpResponseForbidden,JsonResponse
from django.shortcuts import render,get_object_or_404,redirect
from django.core.paginator import Paginator
from django.utils import timezone
from django.views.decorators.http import require_http_methods,require_GET,require_POST
from .models import Batch,BatchPhoto
from .artisan_uploads import batch_stamp,attachable

SALT='coffee-optional-batch-photo-v1'
MAX_PHOTO=10*1024*1024
MIMES={'JPEG':'image/jpeg','PNG':'image/png','WEBP':'image/webp'}
EXTENSIONS={'JPEG':'jpg','PNG':'png','WEBP':'webp'}

def validated_image(upload):
    if not 0<upload.size<=MAX_PHOTO:raise forms.ValidationError('Choose a photo up to 10 MB.')
    raw=upload.read(MAX_PHOTO+1)
    if len(raw)>MAX_PHOTO:raise forms.ValidationError('Choose a photo up to 10 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in MIMES or getattr(image,'n_frames',1)!=1:raise ValueError()
                if not 16<=image.width<=8000 or not 16<=image.height<=8000 or image.width*image.height>20_000_000:raise ValueError()
                fmt=image.format;width,height=image.size;image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image.load();thumb=ImageOps.exif_transpose(image)
                thumb.thumbnail((640,640))
                if thumb.mode in ('RGBA','LA') or 'transparency' in thumb.info:
                    rgba=thumb.convert('RGBA');back=Image.new('RGB',rgba.size,'white');back.paste(rgba,mask=rgba.getchannel('A'));thumb=back
                else:thumb=thumb.convert('RGB')
                output=io.BytesIO();thumb.save(output,format='JPEG',quality=82,optimize=True)
    except (UnidentifiedImageError,OSError,ValueError,SyntaxError,Image.DecompressionBombWarning,Image.DecompressionBombError):
        raise forms.ValidationError('Use a single PNG, JPEG or WebP photo, 16–8000 pixels per side and up to 20 megapixels.')
    name=''.join(c for c in str(upload.name).replace('\\','/').rsplit('/',1)[-1] if c.isprintable())[:180]
    return {'image_data':raw,'thumbnail_data':output.getvalue(),'sha256':hashlib.sha256(raw).hexdigest(),'source_name':name or 'batch-photo','image_format':fmt,'width':width,'height':height}

class PhotoForm(forms.Form):
    ticket=forms.CharField(widget=forms.HiddenInput)
    image=forms.FileField(label='Choose a photo instead',widget=forms.ClearableFileInput(attrs={'accept':'image/jpeg,image/png,image/webp'}))
    origin=forms.ChoiceField(choices=[('upload','Uploaded photo'),('camera','Camera capture')],initial='upload',widget=forms.HiddenInput)
    note=forms.CharField(required=False,max_length=1200,label='Photo / roast notes (optional)',widget=forms.Textarea(attrs={'rows':3}))
    confirmed=forms.BooleanField(label='I checked this is the cooled coffee from the batch shown above.')
    def clean_image(self):return validated_image(self.cleaned_data['image'])

def photo_stamp(batch):
    return hashlib.sha256((batch_stamp(batch)+'|'+batch.roast_level+'|'+str(batch.actual_finish_temp_f)).encode()).hexdigest()

def photo_ticket(batch,user):return signing.dumps({'batch':batch.pk,'actor':user.pk,'stamp':photo_stamp(batch),'request':str(uuid.uuid4())},salt=SALT,compress=True)

def ticket_data(value,batch,user):
    try:data=signing.loads(value,salt=SALT,max_age=24*60*60)
    except (signing.BadSignature,TypeError):raise ValidationError('This photo form expired or changed. Reload the batch photos page before saving.')
    if data.get('batch')!=batch.pk or data.get('actor')!=user.pk:raise ValidationError('This photo form belongs to another batch or account.')
    try:uuid.UUID(data['request'])
    except (KeyError,ValueError,TypeError):raise ValidationError('Reload the photo form before saving.')
    return data

def allowed(batch):
    try:attachable(batch);return True
    except ValidationError:return False

def photo_context(batch):
    return {'batch_photo_previews':batch.photos.filter(removed_at__isnull=True).defer('image_data','thumbnail_data').select_related('created_by')[:3],'batch_photos_allowed':allowed(batch)}

def save_photo(batch,user,data):
    token=ticket_data(data['ticket'],batch,user);image=data['image']
    digest=hashlib.sha256(json.dumps([batch.pk,image['sha256'],data['origin'],data['note']],sort_keys=True).encode()).hexdigest()
    with transaction.atomic():
        batch=Batch.all_objects.select_for_update().get(pk=batch.pk)
        prior=BatchPhoto.objects.filter(request_key=token['request']).first()
        if prior:
            if prior.request_hash!=digest or prior.created_by_id!=user.pk or prior.batch_id!=batch.pk:raise ValidationError('This save already recorded a different photo or note. Reload before adding another.')
            if prior.removed_at:raise ValidationError('This photo was unlinked. Reload to add it again deliberately.')
            return prior,True
        if not allowed(batch):raise ValidationError('Photos can be added after this batch is recorded as roasted. Excluded or merged inputs cannot receive new photos.')
        if token['stamp']!=photo_stamp(batch):raise ValidationError('This batch’s coffee, machine or measurements changed. Reload and confirm the correct batch before saving.')
        prior=BatchPhoto.objects.filter(batch=batch,sha256=image['sha256'],removed_at__isnull=True).first()
        if prior:return prior,True
        photo=BatchPhoto.objects.create(batch=batch,request_key=token['request'],request_hash=digest,origin=data['origin'],note=data['note'],created_by=user,**image)
    return photo,False

@login_required
@require_http_methods(['GET','POST'])
def batch_photos(request,pk):
    if not request.user.is_staff:return HttpResponseForbidden('Staff access is required.')
    batch=get_object_or_404(Batch.all_objects.select_related('coffee','roaster','operator'),pk=pk)
    error='';status=200;form=PhotoForm(initial={'ticket':photo_ticket(batch,request.user)})
    if request.method=='POST':
        form=PhotoForm(request.POST,request.FILES)
        if form.is_valid():
            try:
                photo,duplicate=save_photo(batch,request.user,form.cleaned_data)
                if request.headers.get('Accept')=='application/json':return JsonResponse({'saved':True,'duplicate':duplicate,'photo_url':'/batch-photos/'+str(photo.pk)+'/','batch_id':batch.pk})
                return redirect('batch_photo_detail',photo_id=photo.pk)
            except (ValidationError,IntegrityError) as exc:error=' '.join(exc.messages) if isinstance(exc,ValidationError) else 'Another photo save completed first. Reload to check the saved photos.';status=409
        else:error=' '.join(str(message) for errors in form.errors.values() for message in errors);status=400
        if request.headers.get('Accept')=='application/json':return JsonResponse({'saved':False,'error':error},status=status)
    removed=request.GET.get('removed')=='1'
    photos=batch.photos.filter(removed_at__isnull=not removed).defer('image_data','thumbnail_data').select_related('created_by','removed_by')
    page=Paginator(photos,12).get_page(request.GET.get('page'))
    response=render(request,'portal/batch_photos.html',{'batch':batch,'form':form,'photos':page,'removed':removed,'can_capture':allowed(batch),'capture_requested':request.method=='GET' and request.GET.get('capture')=='1','photo_error':error},status=status)
    response['Cache-Control']='private, no-store';return response

@login_required
@require_GET
def photo_detail(request,photo_id):
    if not request.user.is_staff:return HttpResponseForbidden('Staff access is required.')
    photo=get_object_or_404(BatchPhoto.objects.defer('image_data','thumbnail_data').select_related('batch__coffee','batch__roaster','created_by','removed_by'),pk=photo_id)
    response=render(request,'portal/batch_photo.html',{'photo':photo,'batch':photo.batch});response['Cache-Control']='private, no-store';return response

@login_required
@require_GET
def photo_image(request,photo_id,thumbnail=False):
    if not request.user.is_staff:return HttpResponseForbidden('Staff access is required.')
    photo=get_object_or_404(BatchPhoto.objects.only('id','batch_id','sha256','image_format','thumbnail_data' if thumbnail else 'image_data'),pk=photo_id)
    raw=bytes(photo.thumbnail_data if thumbnail else photo.image_data)
    if not thumbnail and hashlib.sha256(raw).hexdigest()!=photo.sha256:raise ValidationError('The saved original failed its integrity check.')
    response=HttpResponse(raw,content_type='image/jpeg' if thumbnail else MIMES[photo.image_format])
    response['Cache-Control']='private, max-age=3600';response['X-Content-Type-Options']='nosniff'
    response['Content-Disposition']=('attachment' if request.GET.get('download')=='1' and not thumbnail else 'inline')+'; filename="batch-'+str(photo.batch_id)+'-'+str(photo.pk)+('.jpg' if thumbnail else '.'+EXTENSIONS[photo.image_format])+'"'
    return response

@login_required
@require_POST
def unlink_photo(request,photo_id):
    if not request.user.is_staff:return HttpResponseForbidden('Staff access is required.')
    reason=request.POST.get('reason','').strip()
    if not 1<=len(reason)<=300:return HttpResponse('Enter a reason of 1–300 characters.',status=400)
    with transaction.atomic():
        photo=get_object_or_404(BatchPhoto.objects.select_for_update(),pk=photo_id)
        if not photo.removed_at:photo.removed_at=timezone.now();photo.removed_by=request.user;photo.removal_reason=reason;photo.save(update_fields=['removed_at','removed_by','removal_reason'])
    return redirect('batch_photo_detail',photo_id=photo.pk)
