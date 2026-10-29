"""A tasting notebook; scores never change production or yield evidence."""
import math
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction,IntegrityError
from django.db.models import Q
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import CuppingRecord,Batch,GreenBeanItem,SourcingEvent
from .sourcing import ticket,identity,validated,snapshot,event

AXES=[('aroma','Aroma'),('flavor','Flavor'),('acidity','Acidity'),('body','Body'),('sweetness','Sweetness'),('finish','Finish'),('balance','Balance')]

def radar(labels,values,scale=10):
    if not 3<=len(labels)<=16 or len(labels)!=len(values):return None
    if not math.isfinite(float(scale)) or scale<=0:return None
    size=380;center=190;radius=110;axes=[];points=[];complete=True
    for i,(label,value) in enumerate(zip(labels,values)):
        angle=2*math.pi*i/len(labels)-math.pi/2;x=math.cos(angle);y=math.sin(angle)
        numeric=float(value) if value is not None else None
        if numeric is not None and (not math.isfinite(numeric) or not 0<=numeric<=scale):return None
        point={'label':str(label)[:60],'x':round(center+x*radius,2),'y':round(center+y*radius,2),'label_x':round(center+x*(radius+32),2),'label_y':round(center+y*(radius+32),2),'value':value,'point_x':round(center+x*radius*numeric/scale,2) if numeric is not None else None,'point_y':round(center+y*radius*numeric/scale,2) if numeric is not None else None}
        axes.append(point)
        if numeric is None:complete=False
        else:points.append(f"{point['point_x']},{point['point_y']}")
    return {'axes':axes,'points':' '.join(points) if complete else '', 'complete':complete,'scale':scale,'rings':[round(radius*n/4,2) for n in range(1,5)]}

class CuppingForm(forms.ModelForm):
    version=forms.IntegerField(min_value=0,widget=forms.HiddenInput,initial=0)
    archived=forms.BooleanField(required=False,label='Archive this tasting (keep history)')
    reason=forms.CharField(max_length=300,required=False,label='Reason for archiving or restoring')
    class Meta:
        model=CuppingRecord
        fields=['title','tasted_on','batch','green_item','taster','brew_method','notes']
        widgets={'tasted_on':forms.DateInput(attrs={'type':'date'}),'notes':forms.Textarea(attrs={'rows':4})}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        valid=Q(removed_at__isnull=True,merged_into__isnull=True)&(Q(roasted_at__isnull=False)|Q(roasted_oz__isnull=False))
        self.fields['batch'].queryset=Batch.objects.filter(valid|Q(pk=self.instance.batch_id)).select_related('coffee','roaster').order_by('-date','-pk')
        self.fields['batch'].label_from_instance=lambda b:f'#{b.pk} · {b.date} · {b.coffee.name} · {b.roast_level} · {b.roaster.name}'
        self.fields['batch'].label='Roasted batch (optional)'
        self.fields['green_item'].label='Green origin / sample lot (optional)'
        self.fields['green_item'].queryset=GreenBeanItem.objects.filter(Q(active=True)|Q(pk=self.instance.green_item_id))
        self.fields['tasted_on'].widget.attrs['max']=timezone.localdate().isoformat()
        for key,label in AXES:self.fields[key]=forms.DecimalField(min_value=0,max_value=10,decimal_places=1,max_digits=3,required=False,label=label+' (0–10)',initial=(self.instance.ratings or {}).get(key),widget=forms.NumberInput(attrs={'step':'.1'}))
    def clean(self):
        data=super().clean();day=data.get('tasted_on');batch=data.get('batch')
        if day and day>timezone.localdate():self.add_error('tasted_on','Choose today or an earlier tasting date.')
        if batch and day and day<batch.date:self.add_error('tasted_on','A tasting cannot precede the linked roast.')
        if not batch and not data.get('green_item'):raise forms.ValidationError('Link the tasting to a roasted batch or a green origin / sample lot.')
        if bool(data.get('archived'))!=bool(self.instance.archived_at) and not data.get('reason'):self.add_error('reason','Give a reason to archive or restore a tasting.')
        return data

def save_tasting(post,actor):
    with transaction.atomic():
        _,key,fingerprint,prior=identity(post,actor,'cupping')
        if prior:return CuppingRecord.objects.get(pk=prior.object_id)
        obj=get_object_or_404(CuppingRecord.objects.select_for_update(),pk=post['pk']) if post.get('pk') else CuppingRecord(created_by=actor)
        before=snapshot(obj,['title','tasted_on','batch_id','green_item_id','taster','brew_method','notes','archived_at','version']) if obj.pk else {}
        if obj.pk:before['ratings']=obj.ratings.copy()
        version=obj.version;form=CuppingForm(post,instance=obj);values=validated(form)
        if values['version']!=version:raise ValidationError('This tasting changed. Reload before saving.')
        obj=form.save(commit=False);obj.ratings={key:str(values[key]) for key,_ in AXES if values[key] is not None}
        obj.archived_at=(obj.archived_at or timezone.now()) if values['archived'] else None
        if values['reason']:obj.archive_reason=values['reason']
        obj.version=version+1;obj.save();event('cupping',obj,actor,before,key,fingerprint,values['reason']);return obj

@staff_member_required
@require_http_methods(['GET','POST'])
def cupping_page(request):
    error='';status=200;selected=get_object_or_404(CuppingRecord,pk=request.GET['edit']) if request.GET.get('edit','').isdigit() else None
    if request.method=='POST':
        try:save_tasting(request.POST,request.user);messages.success(request,'Tasting saved. Roast results, stock and orders are unchanged.');return redirect('/cupping/')
        except (ValidationError,IntegrityError) as exc:error='; '.join(exc.messages) if isinstance(exc,ValidationError) else 'That request was already saved. Reload to review.';status=400
    initial={'tasted_on':timezone.localdate(),'taster':request.user.username,'version':selected.version if selected else 0,'archived':bool(selected and selected.archived_at),'reason':selected.archive_reason if selected else ''}
    if not selected and request.GET.get('batch','').isdigit():initial['batch']=request.GET['batch']
    rows=CuppingRecord.objects.select_related('batch__coffee','green_item','created_by')
    if request.GET.get('archived')!='1':rows=rows.filter(archived_at__isnull=True)
    search=request.GET.get('q','').strip()[:160]
    if search:rows=rows.filter(Q(title__icontains=search)|Q(notes__icontains=search)|Q(taster__icontains=search))
    rows=list(rows[:100])
    for row in rows:
        row.chart=radar([label for _,label in AXES],[row.ratings.get(key) for key,_ in AXES])
        row.scores=[{'label':label,'value':row.ratings.get(key)} for key,label in AXES]
    return render(request,'portal/cupping.html',{'rows':rows,'form':CuppingForm(request.POST if request.method=='POST' else None,instance=selected,initial=initial),'selected':selected,'ticket':ticket(request.user,'cupping'),'error':error,'history':SourcingEvent.objects.filter(kind='cupping',object_id=selected.pk).select_related('actor')[:20] if selected else [],'search':search,'archived':request.GET.get('archived')=='1'},status=status)

def artisan_flavors(data):
    """Keep source labels and scores; choose an explicitly labelled display scale."""
    labels=data.get('flavorlabels');values=data.get('flavors')
    if not isinstance(labels,list) or not isinstance(values,list) or not 3<=len(labels)<=16 or len(labels)!=len(values):return None
    if any(not isinstance(label,str) or not label.strip() or len(label)>60 for label in labels):return None
    if any(isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or value>100 for value in values):return None
    # The document contains values without an axis maximum. Show the original
    # values and identify this display scale; do not infer an official score.
    scale=max(10,max(values))
    return radar(labels,values,scale)
