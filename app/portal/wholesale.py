"""Repeat-safe multi-line wholesale entry using the existing plan rules."""
from decimal import Decimal
import hashlib,json,uuid
from django import forms
from django.forms import formset_factory
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import Coffee,LabelVariant,RoastPlan,WholesaleOrder,IncomingOrderLine,PlanEvent,ROAST_LEVELS,GRIND_CHOICES,WholesaleCustomer
from .planning import IncomingForm,group_for

SIZES=[('80','5 lb'),('12','12 oz'),('2.5','2.5 oz frac bag'),('frac_pack','Frac assortment — 4 × 2.5 oz')]
from .instance import assortment_names
SALT='coffee-wholesale-order'


class HeaderForm(forms.Form):
    customer=forms.CharField(max_length=120,label='Customer / business')
    reference=forms.CharField(max_length=100,required=False,label='Order reference (optional)')
    plan=forms.ChoiceField(label='Add to roast plan')
    plan_date=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'}),label='New plan date')
    version=forms.CharField(required=False,widget=forms.HiddenInput)
    request_token=forms.CharField(widget=forms.HiddenInput)
    customer_version=forms.CharField(required=False,widget=forms.HiddenInput)
    usual_grind=forms.ChoiceField(choices=[c for c in GRIND_CHOICES if c[0] in ('whole','regular','fine','coarse')],initial='whole',required=False,label='Usual grind')
    remember_customer=forms.BooleanField(required=False,label='Save these choices as this customer’s usual order')
    def __init__(self,*args,plans,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['plan'].choices=[('new','Create a new roast plan')]+[(str(p.pk),f'#{p.pk} · {p.date:%b %d, %Y}'+(' · Accepted' if p.accepted_at else ' · Draft')) for p in plans]
    def clean(self):
        data=super().clean()
        if data.get('plan')=='new' and not data.get('plan_date'):self.add_error('plan_date','Choose a date for the new roast plan.')
        return data


class ItemForm(forms.Form):
    coffee=forms.ModelChoiceField(queryset=Coffee.objects.none(),required=False,empty_label='Choose coffee')
    size=forms.ChoiceField(choices=[('','Choose bag size')]+SIZES,label='Bag size',initial='12')
    count=forms.IntegerField(min_value=1,max_value=10000,label='Bags / assortment packs',initial=1)
    grind=forms.ChoiceField(choices=[c for c in GRIND_CHOICES if c[0] in ('whole','regular','fine','coarse')],initial='whole')
    label_variant=forms.ModelChoiceField(queryset=LabelVariant.objects.none(),required=False,empty_label='Standard label',label='Packaging label')
    roast_level=forms.ChoiceField(choices=[('','Use standard roast')]+ROAST_LEVELS,required=False,label='Roast override')
    target_finish_temp_f=forms.DecimalField(max_digits=5,decimal_places=1,min_value=Decimal('.1'),required=False,label='Custom finish temperature (°F)')
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['coffee'].queryset=Coffee.objects.filter(active=True,experimental=False).select_related('roast_base')
        self.fields['label_variant'].queryset=LabelVariant.objects.filter(active=True,coffee__active=True)
        self.fields['count'].widget.attrs.update({'inputmode':'numeric','step':'1'})
    def clean(self):
        data=super().clean()
        if self.errors:return data
        size=data['size'];count=data['count'];coffee=data['coffee']
        if size=='frac_pack':
            if data.get('label_variant') or data.get('roast_level') or data.get('target_finish_temp_f') is not None:
                raise ValidationError('Frac assortments use each coffee’s standard roast and label. Add separate coffee rows for special labels.')
            coffees=list(Coffee.objects.filter(name__in=assortment_names(),active=True))
            if len(coffees)!=4:raise ValidationError('Configure four active assortment coffees in Administration → Portal configuration.')
            coffees.sort(key=lambda c:assortment_names().index(c.name));size=Decimal('2.5')
        else:
            if not coffee:raise ValidationError('Choose a coffee for this row.')
            coffees=[coffee];size=Decimal(size)
        expanded=[]
        for c in coffees:
            roast=data.get('roast_level') or c.standard_roast
            validation=IncomingForm({'coffee':c.pk,'label_variant':data['label_variant'].pk if data.get('label_variant') else '',
                'extra_oz':str(size*count),'roast_level':roast,'target_finish_temp_f':data.get('target_finish_temp_f') or '',
                'grind':data['grind']})
            if not validation.is_valid():
                raise ValidationError([f'{c.name}: {message}' for errors in validation.errors.values() for message in errors])
            expanded.append({**validation.cleaned_data,'packaging':[{'size_oz':str(size),'bags':count,'per_sheet':8 if size==Decimal('2.5') else 4}]})
        data['expanded']=expanded
        return data


ItemForms=formset_factory(ItemForm,extra=1,min_num=0,validate_min=False,max_num=50,validate_max=True,absolute_max=50,can_delete=True)


def original_items(forms):
    return [{key:(value.pk if isinstance(value,(Coffee,LabelVariant)) else str(value) if isinstance(value,Decimal) else value)
             for key,value in form.cleaned_data.items() if key in ('coffee','size','count','grind','label_variant','roast_level','target_finish_temp_f')}
            for form in forms if form.cleaned_data and not form.cleaned_data.get('DELETE')]


def payload_hash(post):
    # Exclude revision and CSRF so an exact retry can return its saved receipt.
    fields={key:post.getlist(key) for key in sorted(post) if key not in ('csrfmiddlewaretoken','request_token','version','items-INITIAL_FORMS','items-MIN_NUM_FORMS','items-MAX_NUM_FORMS')}
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()


@transaction.atomic
def save_order(request,header,items):
    try:
        packet=signing.loads(request.POST.get('request_token',''),salt=SALT,max_age=4*3600)
        key=uuid.UUID(packet['nonce']);assert packet['user']==request.user.pk
    except (signing.BadSignature,KeyError,ValueError,TypeError,AssertionError):
        raise ValidationError('This order page expired. Open Add wholesale order again before saving.')
    actor=get_user_model().objects.select_for_update().get(pk=request.user.pk)
    fingerprint=payload_hash(request.POST)
    saved=WholesaleOrder.objects.select_related('plan').filter(request_key=key).first()
    if saved:
        if saved.created_by_id!=actor.pk or saved.request_hash!=fingerprint:raise ValidationError('This save was already used for a different order. Open a fresh wholesale order page.')
        if saved.plan.removed_at or saved.plan.historical or saved.plan.closed_at:raise ValidationError('This wholesale order was already saved in a deleted, closed or past plan. Review that plan before adding another order.')
        return saved,False
    if not header.is_valid() or not items.is_valid():return None,False
    rows=[form for form in items if form.cleaned_data and not form.cleaned_data.get('DELETE')]
    if not rows:raise ValidationError('Add at least one coffee row.')
    data=header.cleaned_data
    if data['plan']=='new':
        plan=RoastPlan.objects.create(date=data['plan_date'],created_by=actor)
        plan.refresh_from_db()
    else:
        plan=get_object_or_404(RoastPlan.objects.select_for_update(),pk=data['plan'])
        if str(plan.version)!=data.get('version'):raise ValidationError('That plan changed while this order was open. Reload and review the latest plan before saving.')
    if data.get('remember_customer'):
        from .customer_preferences import save_preferences
        save_preferences(actor,{**data,'usual_grind':data.get('usual_grind') or 'whole'},rows)
    saved=WholesaleOrder.objects.create(plan=plan,customer=data['customer'],reference=data['reference'],request_key=key,request_hash=fingerprint,original_items=original_items(rows),created_by=actor)
    # Nonflavored demand first lets flavors share a suitable real Medium roast.
    expanded=[entry for form in rows for entry in form.cleaned_data['expanded']]
    expanded.sort(key=lambda entry:entry['coffee'].kind=='flavored')
    created=[]
    for index,entry in enumerate(expanded):
        group=group_for(plan,entry)
        line=IncomingOrderLine.objects.create(group=group,wholesale_order=saved,reference=data['reference'] or f'Wholesale #{saved.pk}',customer=data['customer'],
            finished_oz=entry['finished_oz'],product_coffee=entry['coffee'],product_label=entry.get('label_variant'),packaging=entry['packaging'],grind=entry['grind'],
            source='manual',external_id=f'wholesale:{key}:{index}')
        created.append(line.pk)
    from .autobatches import sync_plan
    from .plan_actions import mark_revised
    sync_plan(plan,actor);revised=mark_revised(plan,actor)
    plan.version+=1;plan.save(update_fields=['version'])
    PlanEvent.objects.create(plan=plan,actor=actor,action='wholesale_added',details={'order':saved.pk,'customer':saved.customer,'lines':created,'revised':revised})
    return saved,True


@staff_member_required
@require_http_methods(['GET','POST'])
def wholesale_order(request):
    plans=list(RoastPlan.objects.all()[:100]);initial={'plan':'new','plan_date':timezone.localdate(),
        'request_token':signing.dumps({'user':request.user.pk,'nonce':str(uuid.uuid4())},salt=SALT)}
    if any(str(p.pk)==request.GET.get('plan') for p in plans):
        initial['plan']=request.GET['plan'];initial['version']=next(p.version for p in plans if str(p.pk)==initial['plan'])
    copied=None;item_initial=None;preference_customer=None;size_review=False
    if request.method=='GET' and request.GET.get('customer'):
        preference_customer=get_object_or_404(WholesaleCustomer,pk=request.GET['customer'])
        initial.update(customer=preference_customer.name,customer_version=preference_customer.version,usual_grind=preference_customer.default_grind)
        item_initial=preference_customer.usual_items
    if request.method=='GET' and request.GET.get('repeat'):
        copied=get_object_or_404(WholesaleOrder,pk=request.GET['repeat'])
        initial['customer']=copied.customer
        item_initial=copied.original_items
    if item_initial is not None:
        # Preserve old receipts/preferences. A discontinued size requires an
        # explicit new choice rather than silently changing its bag weight.
        allowed={size for size,_ in SIZES}
        size_review=any(str(row.get('size','')) not in allowed for row in item_initial)
        item_initial=[{**row,'size':row.get('size') if str(row.get('size','')) in allowed else ''} for row in item_initial]
    header=HeaderForm(request.POST if request.method=='POST' else None,plans=plans,initial=initial)
    items=ItemForms(request.POST if request.method=='POST' else None,prefix='items',initial=item_initial)
    # Repeats contain exactly their saved rows, without an extra blank item.
    if item_initial is not None:items.extra=0
    status=200
    if request.method=='POST':
        try:
            if request.POST.get('action')=='save_preferences':
                from .customer_preferences import PreferenceForm,save_preferences
                preference=PreferenceForm(request.POST)
                if not preference.is_valid():raise ValidationError('Enter a customer and a valid usual grind before saving preferences.')
                if not items.is_valid():raise ValidationError('Correct the coffee rows before saving preferences.')
                rows=[f for f in items if f.cleaned_data and not f.cleaned_data.get('DELETE')]
                if not rows:raise ValidationError('Add at least one usual coffee row.')
                customer=save_preferences(request.user,preference.cleaned_data,rows)
                messages.success(request,'Customer preferences saved. No order or roast plan was created.')
                return redirect('/wholesale/?customer='+str(customer.pk))
            saved,created=save_order(request,header,items)
            if saved:
                messages.success(request,f'Wholesale order #{saved.pk} '+('saved. Review the suggested batches and accept the plan when ready.' if created else 'was already saved. No duplicate order was added.'))
                return redirect('/planning/?plan='+str(saved.plan_id)+'#incoming-orders')
        except ValidationError as error:header.add_error(None,error)
        status=400
    coffees=[{'id':c.pk,'name':c.name,'roast':c.standard_roast,'locked':c.roast_locked} for c in Coffee.objects.filter(active=True,experimental=False)]
    customers=[{'id':c.pk,'name':c.name,'key':c.name_key,'grind':c.default_grind,'version':c.version,'items':c.usual_items} for c in WholesaleCustomer.objects.all()]
    return render(request,'portal/wholesale.html',{'header':header,'items':items,'copied':copied,'coffees':coffees,'customers':customers,'preference_customer':preference_customer,'size_review':size_review,
        'label_coffees':{str(v.pk):v.coffee_id for v in LabelVariant.objects.filter(active=True)},
        'plan_versions':{str(p.pk):p.version for p in plans},'recent':WholesaleOrder.objects.select_related('plan','created_by')[:15]},status=status)
