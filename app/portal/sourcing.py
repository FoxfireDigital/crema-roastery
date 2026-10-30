"""Supplier records, receipt costs and descriptive bean metadata."""
from decimal import Decimal
import hashlib,json,uuid
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction,IntegrityError
from django.db.models import Q
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import BeanSupplier,GreenBeanDetails,GreenPurchase,GreenBeanItem,GreenMovement,SourcingEvent
from .green_stock import amount

SALT='coffee-sourcing-v1'

def ticket(actor,kind,**extra):return signing.dumps({'actor':actor.pk,'kind':kind,'nonce':str(uuid.uuid4()),**extra},salt=SALT,compress=True)

def identity(post,actor,kind):
    try:
        data=signing.loads(post.get('ticket',''),salt=SALT,max_age=14400)
        assert data['actor']==actor.pk and data['kind']==kind
        key=uuid.UUID(data['nonce'])
    except (signing.BadSignature,KeyError,ValueError,TypeError,AssertionError):raise ValidationError('This form expired. Reload before saving.')
    body={k:post.getlist(k) for k in post if k not in ['csrfmiddlewaretoken','ticket']}
    fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
    prior=SourcingEvent.objects.filter(request_key=key).first()
    if prior and (prior.actor_id!=actor.pk or prior.kind!=kind or prior.request_hash!=fingerprint):raise ValidationError('This saved form has different values. Reload before another change.')
    return data,key,fingerprint,prior

def snapshot(instance,fields):return {name:str(getattr(instance,name)) if getattr(instance,name) is not None else None for name in fields}

def event(kind,obj,actor,before,key,fingerprint,reason=''):
    SourcingEvent.objects.create(kind=kind,object_id=obj.pk,actor=actor,before=before,after=snapshot(obj,[f.attname for f in obj._meta.concrete_fields if f.name not in ['created_at','updated_at']]),request_key=key,request_hash=fingerprint,reason=reason)

def validated(form):
    if not form.is_valid():raise ValidationError([str(e) for errors in form.errors.values() for e in errors])
    return form.cleaned_data

class SupplierForm(forms.ModelForm):
    version=forms.IntegerField(min_value=0,widget=forms.HiddenInput,initial=0)
    class Meta:
        model=BeanSupplier
        fields=['name','contact','email','phone','website','country','notes','active']
        widgets={'notes':forms.Textarea(attrs={'rows':3})}
    def clean_notes(self):return self.cleaned_data['notes'][:4000]

class DetailsForm(forms.ModelForm):
    version=forms.IntegerField(min_value=0,widget=forms.HiddenInput,initial=0)
    roast_levels=forms.MultipleChoiceField(choices=[(level,level) for level in ['Light','Light/Medium','Medium','Medium/Dark','Dark','French']],required=False,widget=forms.CheckboxSelectMultiple,label='Known suitable roast levels (optional)')
    class Meta:
        model=GreenBeanDetails
        fields=['supplier','country','region','farmer','variety','crop','processing','supplier_score','source_url','roast_levels','flavor_tags','caffeine']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['supplier'].queryset=BeanSupplier.objects.filter(Q(active=True)|Q(pk=self.instance.supplier_id))
        self.fields['supplier_score'].label='Supplier cupping score (0–100, optional)'
    def clean_supplier_score(self):
        value=self.cleaned_data['supplier_score']
        if value is not None and not 0<=value<=100:raise forms.ValidationError('Use a score between 0 and 100, or leave it blank.')
        return value

class PurchaseForm(forms.Form):
    item=forms.ModelChoiceField(queryset=GreenBeanItem.objects.none(),label='Green origin / lot')
    supplier=forms.ModelChoiceField(queryset=BeanSupplier.objects.none(),required=False,label='Seller (optional)')
    received_on=forms.DateField(widget=forms.DateInput(attrs={'type':'date'}))
    quantity=forms.DecimalField(max_digits=11,decimal_places=3,min_value=Decimal('.001'))
    unit=forms.ChoiceField(choices=[('lb','Pounds'),('oz','Ounces')])
    total_cost=forms.DecimalField(max_digits=12,decimal_places=2,min_value=0,required=False,label='Total landed cost (optional)')
    currency=forms.RegexField(r'^[A-Z]{3}$',max_length=3,initial='USD',label='Currency code, such as USD')
    reference=forms.CharField(max_length=120,required=False,label='Invoice / reference')
    notes=forms.CharField(max_length=4000,required=False,widget=forms.Textarea(attrs={'rows':2}))
    def __init__(self,*args,**kwargs):
        self.editing=kwargs.pop('editing',None);super().__init__(*args,**kwargs)
        self.fields['item'].queryset=GreenBeanItem.objects.filter(Q(active=True)|Q(pk=self.editing.item_id if self.editing else None))
        self.fields['supplier'].queryset=BeanSupplier.objects.filter(Q(active=True)|Q(pk=self.editing.supplier_id if self.editing else None))
        self.fields['received_on'].widget.attrs['max']=timezone.localdate().isoformat()
        if self.editing:
            for name in ['item','quantity','unit']:self.fields.pop(name)
    def clean_received_on(self):
        day=self.cleaned_data['received_on']
        if day>timezone.localdate():raise forms.ValidationError('Record a receipt on or before today; future purchases are not available stock.')
        return day

def save_supplier(post,actor):
    with transaction.atomic():
        _,key,fingerprint,prior=identity(post,actor,'supplier')
        if prior:return BeanSupplier.objects.get(pk=prior.object_id)
        obj=get_object_or_404(BeanSupplier.objects.select_for_update(),pk=post['pk']) if post.get('pk') else BeanSupplier(updated_by=actor)
        before=snapshot(obj,['name','contact','email','phone','website','country','notes','active','version']) if obj.pk else {}
        version=obj.version;form=SupplierForm(post,instance=obj);values=validated(form)
        if values['version']!=version:raise ValidationError('This supplier changed. Reload before saving.')
        obj=form.save(commit=False);obj.updated_by=actor;obj.version=version+1;obj.save()
        event('supplier',obj,actor,before,key,fingerprint);return obj

def save_details(post,actor,item):
    with transaction.atomic():
        packet,key,fingerprint,prior=identity(post,actor,'bean')
        if packet.get('item')!=item.pk:raise ValidationError('This form belongs to another green origin.')
        if prior:return
        GreenBeanItem.objects.select_for_update().get(pk=item.pk)
        obj=GreenBeanDetails.objects.filter(item=item).first() or GreenBeanDetails(item=item,updated_by=actor)
        before=snapshot(obj,['supplier_id','country','region','farmer','variety','crop','processing','supplier_score','source_url','roast_levels','flavor_tags','caffeine','version']) if obj.pk else {}
        version=obj.version;form=DetailsForm(post,instance=obj);values=validated(form)
        if values['version']!=version:raise ValidationError('These bean details changed. Reload before saving.')
        obj=form.save(commit=False);obj.updated_by=actor;obj.version=version+1;obj.save();event('bean',obj,actor,before,key,fingerprint)

def save_purchase(post,actor):
    with transaction.atomic():
        packet,key,fingerprint,prior=identity(post,actor,'purchase')
        if prior:return GreenPurchase.objects.get(pk=prior.object_id)
        obj=get_object_or_404(GreenPurchase.objects.select_for_update(),pk=post['pk']) if post.get('pk') else None
        values=validated(PurchaseForm(post,editing=obj))
        if obj:
            if obj.voided_at:raise ValidationError('This purchase is voided. Its original receipt remains in stock history.')
            if post.get('version')!=str(obj.version):raise ValidationError('This purchase changed. Reload before correcting it.')
            before=snapshot(obj,['supplier_id','supplier_name','received_on','total_cost','currency','reference','notes','version'])
        else:
            item=GreenBeanItem.objects.select_for_update().get(pk=values['item'].pk)
            if not item.active:raise ValidationError('This green origin is inactive. Reload before receiving it.')
            if packet.get('versions',{}).get(str(item.pk))!=item.version:raise ValidationError('The bean balance changed. Reload before receiving this purchase.')
            quantity=amount(values['quantity'],values['unit'])
            if quantity<=0:raise ValidationError('The received weight must round to at least 0.1 oz.')
            before_oz=item.remaining_oz;item.remaining_oz+=quantity;item.version+=1;item.save(update_fields=['remaining_oz','version','updated_at'])
            movement=GreenMovement.objects.create(item=item,actor=actor,action='receipt',delta_oz=quantity,before_oz=before_oz,after_oz=item.remaining_oz,note='Purchase receipt '+values['reference'][:120],request_key=key,request_hash=fingerprint)
            obj=GreenPurchase(item=item,bean_name=item.name,quantity_oz=quantity,receipt=movement,created_by=actor);before={}
        for name in ['supplier','received_on','total_cost','currency','reference','notes']:setattr(obj,name,values[name])
        obj.supplier_name=values['supplier'].name if values['supplier'] else '';obj.version+=1;obj.save();event('purchase',obj,actor,before,key,fingerprint);return obj

def void_purchase(post,actor):
    with transaction.atomic():
        _,key,fingerprint,prior=identity(post,actor,'purchase_void')
        if prior:return
        obj=get_object_or_404(GreenPurchase.objects.select_for_update(),pk=post.get('pk'))
        if post.get('version')!=str(obj.version):raise ValidationError('This purchase changed. Reload before voiding.')
        reason=post.get('reason','').strip()
        if not reason or len(reason)>300:raise ValidationError('Give a reason up to 300 characters.')
        if post.get('stock_unchanged')!='on':raise ValidationError('Confirm that this void affects purchase details only, not physical stock.')
        if obj.voided_at:raise ValidationError('This purchase is already voided.')
        before=snapshot(obj,['voided_at','void_reason','version']);obj.voided_at=timezone.now();obj.void_reason=reason;obj.version+=1;obj.save(update_fields=['voided_at','void_reason','version']);event('purchase_void',obj,actor,before,key,fingerprint,reason)

@staff_member_required
@require_http_methods(['GET','POST'])
def suppliers(request):
    error='';status=200;selected=get_object_or_404(BeanSupplier,pk=request.GET['edit']) if request.GET.get('edit','').isdigit() else None
    if request.method=='POST':
        try:save_supplier(request.POST,request.user);messages.success(request,'Supplier saved. Earlier changes remain in history.');return redirect('/suppliers/')
        except (ValidationError,IntegrityError) as exc:error='; '.join(exc.messages) if isinstance(exc,ValidationError) else 'That supplier name or saved request already exists.';status=400
    form=SupplierForm(request.POST if request.method=='POST' else None,instance=selected,initial={'version':selected.version if selected else 0})
    return render(request,'portal/suppliers.html',{'suppliers':BeanSupplier.objects.all(),'form':form,'selected':selected,'history':SourcingEvent.objects.filter(kind='supplier',object_id=selected.pk).select_related('actor')[:20] if selected else [],'ticket':ticket(request.user,'supplier'),'error':error},status=status)

@staff_member_required
@require_http_methods(['GET','POST'])
def bean_details(request,pk):
    item=get_object_or_404(GreenBeanItem,pk=pk);obj=GreenBeanDetails.objects.filter(item=item).first();error='';status=200
    if request.method=='POST':
        try:save_details(request.POST,request.user,item);messages.success(request,'Bean information saved. Stock and recipes are unchanged.');return redirect('/green-beans/'+str(pk)+'/details/')
        except (ValidationError,IntegrityError) as exc:error='; '.join(exc.messages) if isinstance(exc,ValidationError) else 'That request was already saved. Reload to review.';status=400
    return render(request,'portal/bean_details.html',{'item':item,'form':DetailsForm(request.POST if request.method=='POST' else None,instance=obj,initial={'version':obj.version if obj else 0}),'ticket':ticket(request.user,'bean',item=pk),'error':error,'history':SourcingEvent.objects.filter(kind='bean',object_id=obj.pk).select_related('actor')[:20] if obj else []},status=status)

@staff_member_required
@require_http_methods(['GET','POST'])
def purchases(request):
    error='';status=200;selected=get_object_or_404(GreenPurchase,pk=request.GET['edit']) if request.GET.get('edit','').isdigit() else None
    if request.method=='POST':
        try:
            if request.POST.get('action')=='void':void_purchase(request.POST,request.user);messages.success(request,'Purchase details voided. Physical stock is unchanged; use a fresh count if the received quantity was wrong.')
            else:save_purchase(request.POST,request.user);messages.success(request,'Purchase saved. New receipts add stock once; invoice corrections leave stock unchanged.')
            return redirect('/purchases/')
        except (ValidationError,IntegrityError) as exc:error='; '.join(exc.messages) if isinstance(exc,ValidationError) else 'That saved request exists. Reload to review it.';status=400
    initial={'received_on':timezone.localdate()}
    if selected:initial.update({name:getattr(selected,name) for name in ['supplier','received_on','total_cost','currency','reference','notes']})
    rows=list(GreenPurchase.objects.select_related('item','supplier','created_by')[:200]);totals={}
    for row in rows:
        row.pounds=row.quantity_oz/16;row.cost_per_lb=row.total_cost/row.pounds if row.total_cost is not None else None
        row.void_ticket=ticket(request.user,'purchase_void')
        if not row.voided_at and row.total_cost is not None:totals[row.currency]=totals.get(row.currency,Decimal(0))+row.total_cost
    return render(request,'portal/purchases.html',{'history':SourcingEvent.objects.filter(kind__in=['purchase','purchase_void'],object_id=selected.pk).select_related('actor')[:20] if selected else [],'rows':rows,'totals':sorted(totals.items()),'form':PurchaseForm(request.POST if request.method=='POST' else None,initial=initial,editing=selected),'selected':selected,'ticket':ticket(request.user,'purchase',versions={str(i.pk):i.version for i in GreenBeanItem.objects.filter(active=True)}),'error':error},status=status)
