"""Original label artwork, retained with the application's persistent database."""
from decimal import Decimal,InvalidOperation
import hashlib,io,warnings
from pathlib import Path
from PIL import Image,UnidentifiedImageError
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from .models import LabelArtwork,Coffee,LabelVariant,ROAST_LEVELS
from .artwork_rules import NEUTRAL_ROAST,NEUTRAL_CHOICE,neutral_allowed

ARTWORK_SIZES={'retail':(Decimal(16),Decimal(80),Decimal('2.5')),'wholesale':(Decimal(12),Decimal(80),Decimal('2.5'))}
SIZE_CHOICES=[('','Choose the printed bag weight'),('12','12 oz'),('16','16 oz / 1 lb'),('80','5 lb / 80 oz'),('2.5','2.5 oz frac')]
from .instance import assortment_names

class ArtworkForm(forms.Form):
    channel=forms.ChoiceField(choices=[('retail','Retail'),('wholesale','Wholesale')],initial='retail',label='Artwork checklist')
    coffee=forms.ModelChoiceField(queryset=Coffee.objects.filter(active=True,experimental=False))
    label_variant=forms.ModelChoiceField(queryset=LabelVariant.objects.filter(active=True),required=False,label='Special packaging label (optional)')
    size_oz=forms.DecimalField(min_value=Decimal('.1'),max_value=800,decimal_places=2,label='Printed bag weight',widget=forms.Select(choices=SIZE_CHOICES))
    roast_level=forms.ChoiceField(choices=[*ROAST_LEVELS,NEUTRAL_CHOICE],label='Roast printed on the artwork',help_text='Choose No fixed roast only for a 5 lb single-origin original with no fixed roast text. The order still specifies its actual roast.')
    per_sheet=forms.TypedChoiceField(coerce=int,choices=[(4,'Four per Letter sheet'),(8,'Eight horizontal frac labels per Letter sheet')])
    image=forms.FileField(label='Original PNG, JPEG or WebP image')
    ready=forms.BooleanField(required=False,label='Ready to print: I checked the coffee, roast, bag weight and special label against this original')
    def __init__(self,*args,**kwargs):
        # Earlier upload forms did not have an order-type field. Infer only
        # their existing size/label category; never convert a supplied weight.
        args=list(args);data=args[0] if args else kwargs.get('data')
        if data is not None and not data.get('channel'):
            data=data.copy()
            try:is_twelve=Decimal(str(data.get('size_oz','')))==12
            except InvalidOperation:is_twelve=False
            data['channel']='wholesale' if is_twelve or data.get('label_variant') else 'retail'
            if args:args[0]=data
            else:kwargs['data']=data
        super().__init__(*args,**kwargs)
    def clean_image(self):
        upload=self.cleaned_data['image']
        if upload.size>10*1024*1024:raise forms.ValidationError('Use an image smaller than 10 MB.')
        data=upload.read(10*1024*1024+1)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.format not in ['PNG','JPEG','WEBP'] or image.width*image.height>20000000 or max(image.size)>8000:raise ValueError()
                    if getattr(image,'n_frames',1)!=1:raise ValueError()
                    metadata={'image_format':image.format,'width':image.width,'height':image.height}
                    image.verify()
            # Verify full decoding as well as the image header.
            with Image.open(io.BytesIO(data)) as image:
                # Some label editors write 0 (undefined) for an already upright
                # original. It requests no transform; keep the exact bytes.
                if image.getexif().get(274,1) not in (0,1):raise forms.ValidationError('Save an upright copy without camera rotation before uploading.')
                image.load()
        except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise forms.ValidationError('Choose a valid, single-frame PNG, JPEG or WebP, up to 20 megapixels and 8000 pixels per side.')
        return {'image_data':data,'sha256':hashlib.sha256(data).hexdigest(),'source_name':Path(upload.name).name[:150],**metadata}
    def clean(self):
        values=super().clean();label=values.get('label_variant');coffee=values.get('coffee');image=values.get('image')
        channel=values.get('channel');size=values.get('size_oz');layout=values.get('per_sheet')
        if channel in ARTWORK_SIZES and size is not None and size not in ARTWORK_SIZES[channel]:self.add_error('size_oz','Wholesale uses 12 oz, 5 lb and 2.5 oz fracs.' if channel=='wholesale' else 'Retail uses 16 oz, 5 lb and 2.5 oz fracs. Use Wholesale for 12 oz artwork.')
        if label and channel=='retail':self.add_error('label_variant','Special customer labels belong in Wholesale. Choose Standard label for retail.')
        if size is not None and layout and layout!=(8 if size==Decimal('2.5') else 4):self.add_error('per_sheet','Use eight horizontal positions for fracs and four positions for regular bags.')
        if label and coffee and label.coffee_id!=coffee.pk:self.add_error('label_variant','Choose the special label belonging to this coffee.')
        if values.get('roast_level')==NEUTRAL_ROAST and coffee and not neutral_allowed(coffee,values.get('size_oz'),values.get('per_sheet')):
            self.add_error('roast_level','No fixed roast is only available for 5 lb single origins, four per sheet.')
        if values.get('ready') and coffee:
            size=values.get('size_oz');roast=values.get('roast_level')
            if roast and roast!=NEUTRAL_ROAST and size and (coffee.roast_locked or size<80) and roast!=coffee.standard_roast:self.add_error('roast_level','This coffee uses '+coffee.standard_roast+'. Supply an original with the correct roast before marking it ready.')
        return values


def coverage(channel=None):
    from .label_sheets import find_art,catalog
    rows=[]
    for coffee in Coffee.objects.filter(active=True,experimental=False).order_by('name'):
        for label in ([None] if channel=='retail' else [None,*LabelVariant.objects.filter(coffee=coffee,active=True)]):
            cells=[]
            sizes=[Decimal(16),Decimal(80)] if channel=='retail' else [Decimal(12),Decimal(80)] if channel=='wholesale' or label else [Decimal(12),Decimal(16),Decimal(80)]
            for size in sizes:
                art,issue=find_art(coffee.name,label.name if label else '',size,coffee.standard_roast)
                cells.append({'size':size,'size_label':'5 lb' if size==80 else str(size)+' oz','art':art,'issue':issue})
            rows.append({'coffee':coffee,'label':label,'cells':cells})
    active=set(Coffee.objects.filter(active=True,experimental=False).values_list('name',flat=True))
    unmatched=sorted({a['coffee'] for a in catalog() if a['coffee'] not in active})
    return rows,unmatched

def coverage_sections():
    result=[]
    for channel,title in [('retail','Retail artwork'),('wholesale','Wholesale artwork')]:
        rows,_=coverage(channel)
        result.append({'channel':channel,'title':title,'sizes':['16 oz','5 lb'] if channel=='retail' else ['12 oz','5 lb'],'rows':rows,
                       'missing':[{**row,'cells':[cell for cell in row['cells'] if cell['issue']]} for row in rows if any(cell['issue'] for cell in row['cells'])]})
    return result

def frac_coverage():
    from .label_sheets import find_art
    rows=[]
    for coffee in Coffee.objects.filter(name__in=assortment_names(),active=True).order_by('name'):
        art,issue=find_art(coffee.name,'',Decimal('2.5'),coffee.standard_roast)
        rows.append({'coffee':coffee.name,'roast':coffee.standard_roast,'art':art,'issue':issue or ('Confirm eight-per-sheet artwork.' if art.get('per_sheet')!=8 else '')})
    return rows


@staff_member_required
def library(request):
    channel=request.GET.get('channel','retail')
    if channel not in ARTWORK_SIZES:channel='retail'
    form=ArtworkForm(request.POST if request.method=='POST' and request.POST.get('action')=='upload' else None,request.FILES or None,initial={'channel':channel})
    if request.method=='POST':
        if request.POST.get('action')=='upload' and form.is_valid():
            data=form.cleaned_data
            LabelArtwork.objects.create(coffee=data['coffee'],label_variant=data['label_variant'],size_oz=data['size_oz'],roast_level=data['roast_level'],per_sheet=data['per_sheet'],active=data['ready'],uploaded_by=request.user,events=[{'actor':request.user.pk,'at':timezone.now().isoformat(),'action':'uploaded_ready' if data['ready'] else 'uploaded_draft','channel':data['channel']}],**data['image'])
            messages.success(request,'Original artwork saved. '+('It is available for matching label sheets.' if data['ready'] else 'It remains a draft until checked and marked ready.'))
            return redirect('/labels/artwork/?channel='+data['channel']+'#'+data['channel']+'-artwork')
        if request.POST.get('action') in ['deactivate','activate']:
            with transaction.atomic():
                art=get_object_or_404(LabelArtwork.objects.select_for_update(),pk=request.POST.get('asset'))
                active=request.POST['action']=='activate'
                if active and not art.coffee.active:
                    messages.error(request,'This coffee is inactive. Its original is retained for history. Review the coffee’s availability before enabling new labels.');return redirect('/labels/artwork/')
                if active and art.roast_level==NEUTRAL_ROAST and not neutral_allowed(art.coffee,art.size_oz,art.per_sheet):
                    messages.error(request,'Roast-neutral artwork is only for 5 lb single origins, four per sheet.');return redirect('/labels/artwork/')
                if active and art.roast_level!=NEUTRAL_ROAST and (art.coffee.roast_locked or art.size_oz<80) and art.roast_level!=art.coffee.standard_roast:
                    messages.error(request,'The artwork metadata conflicts with the roast rule. Upload a corrected original.');return redirect('/labels/artwork/')
                if active and request.POST.get('checked')!='on':
                    messages.error(request,'Check the original image before marking it ready.');return redirect('/labels/artwork/')
                art.active=active;art.events.append({'actor':request.user.pk,'at':timezone.now().isoformat(),'action':'activated' if active else 'retired'});art.save(update_fields=['active','events'])
            messages.success(request,'Artwork marked ready.' if active else 'Artwork retired from new sheets. Saved print runs retain their original image.');return redirect('/labels/artwork/')
    rows,unmatched=coverage()
    return render(request,'portal/artwork_library.html',{'form':form,'coverage':rows,'coverage_sections':coverage_sections(),'unmatched':unmatched,'fracs':frac_coverage(),'artwork_label_map':{str(l.pk):str(l.coffee_id) for l in LabelVariant.objects.filter(active=True)},'uploads':LabelArtwork.objects.defer('image_data').select_related('coffee','label_variant','uploaded_by')[:100]})
