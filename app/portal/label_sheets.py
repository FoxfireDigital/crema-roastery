"""Artwork sheets and a separate advance-label reservation queue."""
from decimal import Decimal,InvalidOperation
from functools import lru_cache
from pathlib import Path
import hashlib,io,json,uuid,re
from urllib.parse import urlencode
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.http import FileResponse,Http404,HttpResponse
from django.shortcuts import get_object_or_404,render,redirect
from .models import Coffee,RoastPlan,IncomingOrderLine,LabelPrintRun,LabelQueueLock,LabelArtwork,ArtworkCoffeeDecision
from .packing import packing_token
from .artwork_rules import NEUTRAL_ROAST,neutral_allowed,validate_masks
from .artwork_grind import DOT_RADIUS, grind_box, grind_boxes, valid_boxes

ART_ROOT=settings.BASE_DIR/'label_artwork'
MAX_LABELS=1000

@lru_cache(maxsize=1)
def bundled_catalog():
    rows=json.loads((ART_ROOT/'catalog.json').read_text(encoding='utf-8'))
    # Bundled catalog is empty; each installation uploads its own originals.
    return rows


def saved_art_record(art):
    neutral=art.roast_level==NEUTRAL_ROAST and neutral_allowed(art.coffee,art.size_oz,art.per_sheet)
    validate_masks(art.print_masks)
    approved=next((event.get('production_roast') for event in reversed(art.events)
                   if event.get('action')=='approved_roast_mismatch' and event.get('artwork_sha256')==art.sha256
                   and event.get('printed_roast')==art.roast_level),None)
    record={'id':str(art.pk),'db':True,'coffee':art.coffee.name,'label':art.label_variant.name if art.label_variant else '',
            'size_oz':str(art.size_oz),'roast':art.roast_level,'width':art.width,'height':art.height,'sha256':art.sha256,
            'per_sheet':art.per_sheet,'preferred':True,'blocked':'','created_at':art.created_at.isoformat(),
            'ground_only':any(event.get('printed_grind')=='ground' for event in art.events),
            'roast_neutral':neutral,'print_masks':art.print_masks if neutral else []}
    if approved and approved==art.coffee.standard_roast and approved!=art.roast_level and not neutral:
        record['approved_production_roast']=approved
    boxes=grind_boxes(art)
    if boxes:
        record['grind_boxes']=boxes
    return record


def catalog():
    decisions={d.source_name:d for d in ArtworkCoffeeDecision.objects.select_related('coffee')}
    rows=[]
    for original in bundled_catalog():
        art=dict(original);decision=decisions.get(art['coffee'])
        if decision and decision.state=='unavailable':continue
        if decision and decision.state=='matched':
            art['source_coffee']=art['coffee'];art['coffee']=decision.coffee.name
            if not decision.coffee.active:art['blocked']='Matched coffee is inactive. Review its label match in Check info.'
        rows.append(art)
    for art in LabelArtwork.objects.filter(active=True,coffee__active=True).defer('image_data').select_related('coffee','label_variant').order_by('created_at','pk'):
        rows.append(saved_art_record(art))
    return rows


def art_bytes(art):
    if art.get('db'):
        saved=get_object_or_404(LabelArtwork,pk=art['id']);data=bytes(saved.image_data)
    else:data=art_path(art).read_bytes()
    if hashlib.sha256(data).hexdigest()!=art['sha256']:raise ValueError('Artwork integrity check failed.')
    return data

def art_path(art):
    path=(ART_ROOT/art['file']).resolve()
    if path.parent!=ART_ROOT.resolve() or not path.is_file():raise Http404('Artwork unavailable.')
    return path

def find_art(coffee,label,size,roast,temp=None,grind=None):
    candidates=[a for a in catalog() if a['coffee']==coffee and a['label']==label and Decimal(a['size_oz'])==size]
    if not candidates:
        return None,('Special-label artwork missing: '+label+'.') if label else 'No matching artwork for this coffee and bag weight.'
    matching=[a for a in candidates if (a['roast']==roast or a.get('roast_neutral') and size==80
                                      or a.get('approved_production_roast')==roast) and not a['blocked']]
    if temp is not None:
        matching=[a for a in matching if a.get('roast_neutral') and size==80]
        if not matching:return None,'Custom finish temperature: use roast-neutral 5 lb single-origin artwork.'
    if not matching:
        reason=next((a['blocked'] for a in candidates if a['blocked']),'Artwork roast differs from this order ('+roast+').')
        return None,reason
    if grind=='whole':
        matching=[a for a in matching if not a.get('ground_only')]
        if not matching:return None,'Artwork says ground coffee. Supply whole-bean artwork for this bag.'
    approved=any(a.get('approved_production_roast')==roast for a in matching)
    def rank(art):
        if approved:
            priority=2*(art['roast']==roast)+(art.get('approved_production_roast')==roast)
        else:
            priority=bool(art.get('roast_neutral'))
        return priority,bool(art.get('db')),art.get('created_at',''),art['preferred'],art['width']*art['height']
    return max(matching,key=rank),''

def order_labels(plan,standard_labels=()):
    rows=[]
    if not plan:return rows
    lines=IncomingOrderLine.objects.filter(group__plan=plan).select_related('group__plan','group__coffee','group__label_variant','product_coffee','product_label')
    for line in lines:
        packs=[];total=Decimal(0)
        for item in line.packaging:
            try:
                size=Decimal(str(item['size_oz']));raw_bags=Decimal(str(item['bags']));bags=int(raw_bags)
                if not size.is_finite() or size<=0 or bags<=0 or raw_bags!=bags:raise ValueError()
                layout=int(item.get('per_sheet') or (4 if size in (12,16,80) else 0))
            except (KeyError,ValueError,TypeError,InvalidOperation,OverflowError):
                packs=[];break
            total+=size*bags;packs.append((size,bags,layout))
        coffee=line.ordered_coffee.name;label=line.ordered_label.name if line.ordered_label else ''
        if not packs or total!=line.finished_oz:
            rows.append({'key':f'{line.pk}-missing','coffee':coffee,'label':label,'reference':line.reference,'grind':line.get_grind_display(),'issue':'Confirm bag sizes and counts in Bagging / labels.','bags':None})
            continue
        for index,(size,bags,layout) in enumerate(packs):
            key=f'{line.pk}-{index}'
            roast=line.group.roast_level
            art,issue=find_art(coffee,label,size,roast,line.group.target_finish_temp_f,grind=line.grind)
            if art and art.get('per_sheet',layout)!=layout:issue='Artwork sheet layout differs from this bag’s packaging. Review it in the artwork library.'
            known_grind=line.grind in ('whole','regular','fine','coarse')
            if not issue and not known_grind:issue='Confirm grind size in Bagging / labels.'
            if not issue and layout not in (4,8):issue='Confirm four- or eight-per-sheet layout in Bagging / labels.'
            standard=line.ordered_coffee.standard_roast
            fallback=None
            if not art and line.ordered_coffee.kind=='single_origin' and standard and known_grind and layout in (4,8) and (roast!=standard or line.group.target_finish_temp_f is not None):
                candidate,_=find_art(coffee,label,size,standard,grind=line.grind)
                if candidate and candidate.get('per_sheet',layout)==layout:
                    fallback=candidate
            override=bool(fallback and key in standard_labels)
            if override:art,issue=fallback,''
            rows.append({'key':key,'line_token':packing_token(line),'coffee':coffee,'label':label,
                         'reference':line.reference,'size':format(size.normalize(),'f'),'grind':line.get_grind_display(),'grind_code':line.grind,
                         'bags':bags,'layout':layout,'art':art,'issue':issue,'standard_art':fallback,
                         'standard_override':override,'planned_roast':roast})
    return rows

def order_revision(plan,rows):
    body=[plan.pk if plan else None,plan.removed_at.isoformat() if plan and plan.removed_at else None,
          [{k:r.get(k) for k in ['key','line_token','bags','layout','issue','standard_override','planned_roast']} for r in rows],
          hashlib.sha256(json.dumps(catalog(),sort_keys=True).encode()).hexdigest()]
    return hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()

def sheet_revision(plan,rows):
    from .label_filler import forecast_revision
    return hashlib.sha256((order_revision(plan,rows)+forecast_revision()).encode()).hexdigest()

class SheetForm(forms.Form):
    revision=forms.CharField(widget=forms.HiddenInput)
    queue_token=forms.CharField(widget=forms.HiddenInput)
    fill_subscriptions=forms.BooleanField(required=False,initial=True,label='Fill unused positions from subscriptions due in the next 14 days')
    fill_bestsellers=forms.BooleanField(required=False,initial=True,label='Fill remaining positions with the most-ordered matching label from the last 21 days')
    selected=forms.MultipleChoiceField(required=False,widget=forms.CheckboxSelectMultiple)
    standard_labels=forms.MultipleChoiceField(required=False,widget=forms.MultipleHiddenInput)
    layout=forms.TypedChoiceField(choices=[(4,'4 labels per Letter sheet'),(8,'8 labels per Letter sheet - fracs')],coerce=int,initial=4,label='Sheet layout')
    start_slot=forms.IntegerField(min_value=1,max_value=8,initial=1,label='First unused position on the first sheet')
    left=forms.DecimalField(min_value=0,max_value=2,decimal_places=4,initial=Decimal('.0625'),label='Left margin (inches)')
    top=forms.DecimalField(min_value=0,max_value=2,decimal_places=4,initial=Decimal('.0625'),label='Top margin (inches)')
    width=forms.DecimalField(min_value=1,max_value=4.25,decimal_places=5,initial=Decimal('4.15625'),label='Label width (inches)')
    height=forms.DecimalField(min_value=1,max_value=5.5,decimal_places=5,initial=Decimal('5.40625'),label='Label height (inches)')
    gap_x=forms.DecimalField(min_value=0,max_value=2,decimal_places=4,initial=Decimal('.0625'),label='Gap between columns (inches)')
    gap_y=forms.DecimalField(min_value=0,max_value=2,decimal_places=4,initial=Decimal('.0625'),label='Gap between rows (inches)')
    offset_x=forms.DecimalField(min_value=-1,max_value=1,decimal_places=3,initial=0,label='Move right (+) / left (-), inches')
    offset_y=forms.DecimalField(min_value=-1,max_value=1,decimal_places=3,initial=0,label='Move down (+) / up (-), inches')
    checked=forms.BooleanField(required=False,label='I checked the selected artwork and quantities, and tested the sheet alignment.')
    def __init__(self,*args,rows,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['selected'].choices=[(r['key'],r['coffee']) for r in rows if not r['issue']]
        self.fields['standard_labels'].choices=[(r['key'],r['coffee']) for r in rows if r.get('standard_art')]
        for row in rows:
            if not row['issue']:self.fields['count_'+row['key']]=forms.IntegerField(min_value=0,max_value=row['bags'],required=False,initial=row['bags'],label='Labels to print for '+row['coffee'])
    def clean(self):
        data=super().clean()
        if self.errors:return data
        layout=data['layout'];nr=layout//2
        if layout==8 and data['width']<=data['height']:self.add_error('width','Frac labels print horizontally: width must be greater than height.')
        if data['start_slot']>layout:self.add_error('start_slot','Choose a position within this sheet.')
        x=data['left']+data['offset_x'];y=data['top']+data['offset_y']
        if x<0 or y<0 or x+2*data['width']+data['gap_x']>Decimal('8.5') or y+nr*data['height']+(nr-1)*data['gap_y']>11:
            raise forms.ValidationError('These dimensions run outside Letter paper. Reduce the label size, margins, gaps or shift.')
        return data

def placements(data):
    out=[]
    for pos in range(data['layout']):
        row,col=divmod(pos,2)
        x=data['left']+data['offset_x']+col*(data['width']+data['gap_x'])
        top=data['top']+data['offset_y']+row*(data['height']+data['gap_y'])
        out.append(tuple(float(n)*72 for n in (x,Decimal(11)-top-data['height'],data['width'],data['height'])))
    return out

def make_pdf(rows,data,alignment=False):
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    result=io.BytesIO();c=canvas.Canvas(result,pagesize=(612,792),pageCompression=1)
    c.setTitle('Coffee labels - Letter - print at actual size');c.setAuthor('Crema')
    boxes=placements(data)
    def black_page():
        c.setFillColorRGB(0,0,0);c.rect(0,0,612,792,stroke=0,fill=1)
        # Cutting ticks stay outside the entire label grid, so they never
        # touch artwork even when the user chooses a zero-gap layout.
        left=min(b[0] for b in boxes);right=max(b[0]+b[2] for b in boxes)
        bottom=min(b[1] for b in boxes);top=max(b[1]+b[3] for b in boxes)
        c.setStrokeColorRGB(.5,.5,.5);c.setLineWidth(.4)
        for x in sorted({edge for b in boxes for edge in (b[0],b[0]+b[2])}):
            if 792-top>=3:c.line(x,top+1,x,top+1+min(5,792-top-2))
            if bottom>=3:c.line(x,bottom-1-min(5,bottom-2),x,bottom-1)
        for y in sorted({edge for b in boxes for edge in (b[1],b[1]+b[3])}):
            if left>=3:c.line(left-1-min(5,left-2),y,left-1,y)
            if 612-right>=3:c.line(right+1,y,right+1+min(5,612-right-2),y)
    if alignment:
        for i,(x,y,w,h) in enumerate(boxes,1):
            c.setStrokeColorRGB(.35,.35,.35);c.setLineWidth(.5);c.rect(x,y,w,h)
            c.setFont('Helvetica-Bold',14);c.drawCentredString(x+w/2,y+h/2+14,'Position '+str(i))
            c.setFont('Helvetica',8);c.drawCentredString(x+w/2,y+h/2,'ALIGNMENT TEST - plain paper - 100% / Actual size')
            c.drawCentredString(x+w/2,y+h/2-12,f'{data["width"]} x {data["height"]} inches')
            c.line(x+w/2-36,y+h/2-30,x+w/2+36,y+h/2-30)
            c.drawCentredString(x+w/2,y+h/2-43,'This line must measure 1 inch')
        c.showPage()
    else:
        black_page()
        slot=data['start_slot']-1;count=0
        for r in rows:
            original_bytes=art_bytes(r['art']);reader=ImageReader(io.BytesIO(original_bytes))
            box=grind_box(r.get('grind_code'))
            point=valid_boxes(r['art'].get('grind_boxes')).get(box)
            for _ in range(r['bags']):
                if slot==data['layout']:c.showPage();black_page();slot=0
                x,y,w,h=boxes[slot]
                iw,ih=reader.getSize()
                rotated=data['layout']==8 and iw<ih
                c.saveState()
                if rotated:
                    # The owner supplies portrait frac originals. Turn the
                    # complete drawing on the horizontal sheet; never rewrite
                    # its pixels, text, proportions or saved original.
                    c.translate(x+w,y);c.rotate(90)
                    x,y,w,h=0,0,h,w
                scale=min(w/iw,h/ih);dw,dh=iw*scale,ih*scale
                left,bottom=x+(w-dw)/2,y+(h-dh)/2
                c.drawImage(reader,left,bottom,width=dw,height=dh,mask='auto')
                masks=r['art'].get('print_masks',[])
                if masks and not rotated:
                    if not r['art'].get('roast_neutral') or data['layout']!=4:raise ValueError('Invalid neutral label print metadata.')
                    validate_masks(masks)
                    from .neutral_print import cover_fixed_roast
                    cover_fixed_roast(c,original_bytes,masks,left,bottom,dw,dh)
                if point:
                    c.setFillColorRGB(0,0,0)
                    c.circle(left+dw*point[0],bottom+dh*(1-point[1]),min(dw,dh)*DOT_RADIUS,stroke=0,fill=1)
                c.restoreState()
                slot+=1;count+=1
        if not count:raise ValueError('No labels selected.')
        c.showPage()
    c.save();result.seek(0);return result.getvalue()

def run_revision(run):
    return hashlib.sha256(json.dumps([str(run.pk),run.status,run.events],sort_keys=True).encode()).hexdigest()

def pdf_response(pdf,mode,name,run=None,advance=0,stock=0):
    response=HttpResponse(pdf,content_type='application/pdf')
    response['Content-Disposition']=('attachment' if mode=='download' else 'inline')+'; filename="'+name+'.pdf"'
    response['Cache-Control']='private, no-store'
    response['X-Coffee-Advance-Labels']=str(sum(row['bags'] for row in run.subscription_labels if row.get('kind')!='bestseller') if run else advance)
    response['X-Coffee-Stock-Labels']=str(sum(row['bags'] for row in run.subscription_labels if row.get('kind')=='bestseller') if run else stock)
    if run:
        response['X-Coffee-Label-Run']=str(run.pk)
    return response


@login_required
def artwork_print_preview(request,asset_id):
    art=get_object_or_404(LabelArtwork.objects.select_related('coffee','label_variant'),pk=asset_id)
    settings={'layout':4,'start_slot':1,**{k:Decimal(v) for k,v in {'left':'.0625','top':'.0625','width':'4.15625','height':'5.40625','gap_x':'.0625','gap_y':'.0625','offset_x':'0','offset_y':'0'}.items()}}
    if art.per_sheet==8:settings.update(layout=8,left=Decimal('.25'),top=Decimal('.25'),width=Decimal(4),height=Decimal('2.625'),gap_x=Decimal(0),gap_y=Decimal(0))
    return pdf_response(make_pdf([{'art':saved_art_record(art),'bags':1,'grind_code':request.GET.get('grind')}],settings),'preview','label-print-preview')

@login_required
def reprint_run(request,pk):
    run=get_object_or_404(LabelPrintRun,pk=pk)
    if run.status=='released':raise Http404('This queue entry was released. Start a fresh sheet.')
    data={key:Decimal(value) if key in ['left','top','width','height','gap_x','gap_y','offset_x','offset_y'] else value for key,value in run.sheet_settings.items()}
    return pdf_response(make_pdf(run.rows,data),'download' if request.GET.get('download')=='1' else 'preview','coffee-labels-'+str(run.pk),run)

@staff_member_required
@require_POST
def update_run(request,pk):
    with transaction.atomic():
        lock=LabelQueueLock.objects.select_for_update().get(pk=1)
        run=get_object_or_404(LabelPrintRun.objects.select_for_update(),pk=pk)
        new=request.POST.get('status')
        if request.POST.get('revision')!=run_revision(run):messages.error(request,'This label queue entry changed. Reload before updating it.')
        elif new not in ['printed','released'] or run.status=='released' or new=='printed' and run.status!='queued':messages.error(request,'That label queue change is unavailable.')
        else:
            run.events.append({'actor':request.user.pk,'at':timezone.now().isoformat(),'before':run.status,'after':new})
            run.status=new;run.save(update_fields=['status','events']);lock.version+=1;lock.save(update_fields=['version'])
            messages.success(request,'Advance labels marked printed.' if new=='printed' else 'Advance-label reservation released. Discard any printed copies before making replacements.')
    return redirect('/labels/'+('?plan='+str(run.plan_id) if run.plan_id else ''))

@login_required
def artwork(request,asset_id):
    art=next((a for a in catalog() if a['id']==asset_id),None)
    if not art:art=next((a for a in bundled_catalog() if a['id']==asset_id),None)
    if not art:
        saved=LabelArtwork.objects.filter(pk=asset_id).first() if re.fullmatch('[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',asset_id) else None
        if saved:art={'id':str(saved.pk),'db':True,'sha256':saved.sha256}
    if not art:raise Http404('Artwork not found.')
    response=FileResponse(io.BytesIO(art_bytes(art)),content_type='application/octet-stream' if art.get('db') else 'image/png' if art['file'].endswith('.png') else 'image/jpeg')
    if art.get('db'):response['Content-Type']={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp'}[LabelArtwork.objects.get(pk=asset_id).image_format]
    response['Cache-Control']='private, max-age=3600'
    return response

@login_required
def label_sheets(request):
    from .label_filler import upcoming_labels,fill_last_sheet,forecast_revision
    plan_id=request.POST.get('plan') if request.method=='POST' else request.GET.get('plan')
    plan=get_object_or_404(RoastPlan.all_objects,pk=plan_id) if plan_id else RoastPlan.objects.filter(accepted_at__isnull=False).first() or RoastPlan.objects.first()
    standard_labels=set((request.POST if request.method=='POST' else request.GET).getlist('standard_labels'))
    rows=order_labels(plan,standard_labels);revision=sheet_revision(plan,rows)
    token=signing.dumps({'nonce':str(uuid.uuid4()),'user':request.user.pk,'plan':plan.pk if plan else None},salt='coffee-label-sheet')
    active_overrides={r['key'] for r in rows if r.get('standard_override')}
    initial={'revision':revision,'queue_token':token,'selected':[r['key'] for r in rows if not r['issue']],
             'standard_labels':sorted(active_overrides)}
    form=SheetForm(request.POST if request.method=='POST' else None,rows=rows,initial=initial)
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data;mode=request.POST.get('action')
        chosen=[{**r,'bags':data.get('count_'+r['key']) if data.get('count_'+r['key']) is not None else r['bags']} for r in rows if r['key'] in data['selected']]
        chosen=[r for r in chosen if r['bags']>0]
        try:
            packet=signing.loads(data['queue_token'],salt='coffee-label-sheet',max_age=4*3600)
            assert packet['user']==request.user.pk and packet['plan']==(plan.pk if plan else None)
            nonce=uuid.UUID(packet['nonce'])
        except (signing.BadSignature,AssertionError,KeyError,ValueError,TypeError):
            form.add_error(None,'This label page expired. Reload it before preparing a sheet.');nonce=None
        if mode not in ('alignment','preview','download'):form.add_error(None,'Choose preview, download or alignment test.')
        elif mode!='alignment' and not data['checked']:form.add_error('checked','Check the artwork and alignment before creating label sheets.')
        elif mode!='alignment' and (not chosen or any(r.get('layout')!=data['layout'] for r in chosen)):form.add_error(None,'Select at least one ready row, all using the chosen sheet layout.')
        elif mode!='alignment' and sum(r['bags'] for r in chosen)>MAX_LABELS:form.add_error(None,'Select at most 1,000 labels per PDF.')
        if not form.errors and mode=='alignment':return pdf_response(make_pdf([],data,alignment=True),mode,'coffee-alignment')
        if not form.errors:
            with transaction.atomic():
                lock=LabelQueueLock.objects.select_for_update().get(pk=1)
                if plan:plan.refresh_from_db()
                current_rows=order_labels(plan,set(data['standard_labels']));current_revision=order_revision(plan,current_rows)
                source_revision=forecast_revision(include_queue=False)
                request_hash=hashlib.sha256(json.dumps({k:v for k,v in data.items() if k!='queue_token'},sort_keys=True,default=str).encode()).hexdigest()
                run=LabelPrintRun.objects.filter(request_key=nonce).first()
                if run:
                    if run.created_by_id!=request.user.pk or run.request_hash!=request_hash or run.order_revision!=current_revision or run.source_revision!=source_revision or run.status=='released':
                        form.add_error(None,'Orders or artwork changed, or this preview used different settings. Reload this page before creating a fresh sheet.')
                    else:
                        saved={k:Decimal(v) if k in ['left','top','width','height','gap_x','gap_y','offset_x','offset_y'] else v for k,v in run.sheet_settings.items()}
                        return pdf_response(make_pdf(run.rows,saved),mode,'coffee-labels-'+str(run.pk),run)
                elif data['revision']!=sheet_revision(plan,current_rows):form.add_error(None,'Orders or artwork changed, or the advance-label queue changed. Reload this page and review the current quantities.')
                else:
                    from .label_bestsellers import bestseller_labels
                    pool,_=upcoming_labels();extras=fill_last_sheet(chosen,data,pool,bestseller_labels())
                    if sum(r['bags'] for r in chosen+extras)>MAX_LABELS:form.add_error(None,'Select at most 1,000 labels including page fillers per PDF.')
                    else:
                        pdf=make_pdf(chosen+extras,data)
                        if mode=='preview' or not extras:return pdf_response(pdf,mode,'coffee-labels-plan-'+str(plan.pk),advance=sum(row['bags'] for row in extras if row.get('kind')!='bestseller'),stock=sum(row['bags'] for row in extras if row.get('kind')=='bestseller'))
                        settings={k:data[k] for k in ['layout','start_slot','left','top','width','height','gap_x','gap_y','offset_x','offset_y']}
                        snapshot=lambda value:json.loads(json.dumps(value,default=str))
                        run=LabelPrintRun.objects.create(request_key=nonce,request_hash=request_hash,order_revision=current_revision,source_revision=source_revision,
                            created_by=request.user,plan=plan,rows=snapshot(chosen+extras),subscription_labels=snapshot(extras),sheet_settings=snapshot(settings),
                            events=[{'actor':request.user.pk,'at':timezone.now().isoformat(),'before':None,'after':'queued'}])
                        if extras:lock.version+=1;lock.save(update_fields=['version'])
                        return pdf_response(pdf,mode,'coffee-labels-'+str(run.pk),run)
    selected=set(form['selected'].value() or [])
    for r in rows:
        r['selected']=r['key'] in selected
        if not r['issue']:r['count_field']=form['count_'+r['key']]
        if r.get('standard_art'):
            toggled=active_overrides ^ {r['key']}
            r['standard_toggle']='?'+urlencode([('plan',plan.pk), *[('standard_labels',key) for key in sorted(toggled)]])
    choices=[]
    standards=dict(Coffee.objects.values_list('name','standard_roast'))
    for art in catalog():
        item=dict(art)
        standard=standards.get(art['coffee'])
        item['warning']=art['blocked'] or (f"Artwork says {art['roast']}; standard {art['coffee']} is {standard}." if standard and art['roast']!=standard and not art.get('roast_neutral') else '')
        if art.get('approved_production_roast')==standard and standard:
            item['warning']+=f' Approved for {standard} orders.'
        choices.append(item)
    pool,forecast_issues=upcoming_labels()
    from .label_bestsellers import bestseller_labels
    bestsellers=bestseller_labels()
    runs=list(LabelPrintRun.objects.exclude(subscription_labels=[]).select_related('created_by')[:20])
    for run in runs:run.revision=run_revision(run)
    return render(request,'portal/label_sheets.html',{'plan':plan,'plans':RoastPlan.objects.all()[:100],'rows':rows,'form':form,
             'ready_count':sum(not r['issue'] for r in rows),'blocked_count':sum(bool(r['issue']) for r in rows),'artworks':choices,
             'upcoming_pool':pool,'bestseller_pool':bestsellers,'forecast_issues':forecast_issues,'label_runs':runs,
             'geometry_fields':[form[name] for name in ['left','top','width','height','gap_x','gap_y','offset_x','offset_y']]})
