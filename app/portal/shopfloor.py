"""Manual supplies and user-defined maintenance, separate from roast completion."""
from datetime import timedelta
from decimal import Decimal,ROUND_CEILING
import hashlib,json,uuid
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction,IntegrityError
from django.db.models import Q,F
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import SupplyItem,SupplyMovement,FlavorSupplyRate,Coffee,IncomingOrderLine,PackingProgress,RoastPlan,MaintenanceTask,MaintenanceService,Roaster,Batch

SALT='coffee-supplies-and-service-v1'
TENTH=Decimal('.1')
SIZES=[Decimal('2.5'),Decimal(12),Decimal(16),Decimal(80)]

def ticket(user):return signing.dumps({'actor':user.pk,'request':str(uuid.uuid4())},salt=SALT)

def identity(post,user):
    try:
        data=signing.loads(post.get('ticket',''),salt=SALT,max_age=14400)
        if data['actor']!=user.pk:raise ValueError()
        key=uuid.UUID(data['request'])
    except (signing.BadSignature,KeyError,ValueError,TypeError):raise ValidationError('This form expired or belongs to another account. Reload before saving.')
    payload={k:post.getlist(k) for k in post if k not in ['ticket','csrfmiddlewaretoken']}
    return key,hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()

def quantity(value,integer=False):
    try:
        value=Decimal(str(value))
        if not value.is_finite() or value<0 or value>999999999 or value!=value.quantize(TENTH) or integer and value!=value.to_integral_value():raise ValueError()
        return value
    except (ValueError,TypeError,ArithmeticError):raise ValidationError('Enter a nonnegative whole count for bags/sheets, or a quantity in tenths for other units.')

class SupplyForm(forms.ModelForm):
    class Meta:
        model=SupplyItem
        fields=['name','kind','unit','size_oz','per_sheet','remaining','reorder_at','notes']
        labels={'remaining':'Starting count / quantity','size_oz':'Bag size in coffee ounces (bags only)','per_sheet':'Labels per sheet (4 or 8, sheets only)','reorder_at':'Reorder at or below'}
        widgets={'notes':forms.Textarea(attrs={'rows':2})}
    def clean(self):
        data=super().clean();kind=data.get('kind');unit=data.get('unit')
        if kind=='bags' and (unit!='each' or data.get('size_oz') not in SIZES):raise forms.ValidationError('Bags use Each and one of 2.5, 12, 16 or 80 oz.')
        if kind=='labels' and (unit!='sheets' or data.get('per_sheet') not in [4,8]):raise forms.ValidationError('Label stock uses Sheets with 4 or 8 labels per sheet.')
        if kind not in ['bags','labels'] and unit=='sheets':raise forms.ValidationError('Sheets is for label stock.')
        if kind=='flavoring' and unit not in ['ml','fl_oz','g','oz']:raise forms.ValidationError('Choose a volume or weight unit for flavoring. Fluid ounces and weight ounces are separate units.')
        data['size_oz']=data.get('size_oz') if kind=='bags' else None;data['per_sheet']=data.get('per_sheet') if kind=='labels' else None
        for field in ['remaining','reorder_at']:
            if field in data:
                try:data[field]=quantity(data[field],unit in ['each','sheets'])
                except ValidationError as exc:self.add_error(field,exc)
        return data

class FlavorRateForm(forms.Form):
    coffee=forms.ModelChoiceField(queryset=Coffee.objects.filter(active=True,kind='flavored'))
    item=forms.ModelChoiceField(queryset=SupplyItem.objects.filter(active=True,kind='flavoring'))
    units_per_lb=forms.DecimalField(min_value=Decimal('.001'),max_digits=9,decimal_places=3,label='Supply units per 1 lb of finished coffee')
    version=forms.IntegerField(min_value=0,initial=0,widget=forms.HiddenInput)

def save_supply(post,user):
    key,digest=identity(post,user)
    with transaction.atomic():
        prior=SupplyMovement.objects.filter(request_key=key).first()
        if prior:
            if prior.request_hash!=digest:raise ValidationError('This saved form had different values. Reload before changing stock.')
            return False
        action=post.get('action')
        if action=='create':
            form=SupplyForm(post)
            if not form.is_valid():raise ValidationError([str(e) for errors in form.errors.values() for e in errors])
            item=form.save(commit=False);item.recorded_by=user;item.save();before=Decimal(0);delta=item.remaining
        elif action=='rate':
            form=FlavorRateForm(post)
            if not form.is_valid():raise ValidationError([str(e) for errors in form.errors.values() for e in errors])
            data=form.cleaned_data;item=SupplyItem.objects.select_for_update().get(pk=data['item'].pk)
            rate=FlavorSupplyRate.objects.select_for_update().filter(item=item,coffee=data['coffee']).first()
            if data['version']!=(rate.version if rate else 0):raise ValidationError('This flavoring rate changed. Reload before saving.')
            if not rate:rate=FlavorSupplyRate(item=item,coffee=data['coffee'],updated_by=user)
            rate.units_per_lb=data['units_per_lb'];rate.version+=1;rate.updated_by=user;rate.save()
            return True
        else:
            item=get_object_or_404(SupplyItem.objects.select_for_update(),pk=post.get('item'))
            if str(item.version)!=post.get('version'):raise ValidationError('This supply balance changed. Reload and check the latest count.')
            before=item.remaining
            if action in ['deactivate','reactivate']:
                item.active=action=='reactivate';delta=Decimal(0)
            elif not item.active:raise ValidationError('Reactivate this supply before recording stock changes.')
            elif action=='settings':
                item.reorder_at=quantity(post.get('reorder_at'),item.unit in ['each','sheets']);item.notes=post.get('note','')[:2000];delta=Decimal(0)
            elif action in ['receipt','use','count']:
                value=quantity(post.get('quantity'),item.unit in ['each','sheets'])
                if action!='count' and not value:raise ValidationError('Enter a quantity greater than zero.')
                delta=value if action=='receipt' else -value if action=='use' else value-before;item.remaining+=delta
            else:raise ValidationError('Choose receipt, use, fresh count or reorder settings.')
            item.version+=1;item.save()
        SupplyMovement.objects.create(item=item,action=action,before=before,delta=delta,after=item.remaining,note=post.get('note','')[:300],actor=user,request_key=key,request_hash=digest)
    return True

def supply_requirements(plan=None):
    lines=IncomingOrderLine.objects.filter(group__plan__removed_at__isnull=True,group__plan__closed_at__isnull=True,group__plan__historical=False).select_related('product_coffee','group__coffee','group__plan')
    lines=lines.filter(group__plan=plan) if plan else lines.filter(group__plan__accepted_at__isnull=False)
    progress={p.line_id:p for p in PackingProgress.objects.filter(line_id__in=lines.values('pk'))}
    bags={size:0 for size in SIZES};labels={size:0 for size in SIZES};flavors={};unknown=[]
    for line in lines:
        state=progress.get(line.pk);coffee=line.ordered_coffee
        if coffee.kind=='flavored' and not (state and state.flavored_at):flavors[coffee.pk]=flavors.get(coffee.pk,Decimal(0))+line.finished_oz
        packs=line.packaging
        if not packs:unknown.append(line);continue
        valid=[]
        try:
            for pack in packs:
                size=Decimal(str(pack['size_oz']));number=Decimal(str(pack['bags']))
                if size not in SIZES or not number.is_finite() or number<=0 or number!=number.to_integral_value():raise ValueError()
                valid.append((size,int(number)))
            if sum(size*number for size,number in valid)!=line.finished_oz:raise ValueError()
        except (KeyError,ValueError,TypeError,ArithmeticError):unknown.append(line);continue
        for size,number in valid:
            if not (state and state.bagged_at):bags[size]+=number
            if not (state and state.labeled_at):labels[size]+=number
    rates=list(FlavorSupplyRate.objects.select_related('coffee','item').filter(item__active=True));mapped={rate.coffee_id for rate in rates}
    return {'bags':bags,'labels':labels,'flavors':flavors,'unknown':unknown,'rates':rates,
            'missing_flavors':list(Coffee.objects.filter(pk__in=set(flavors)-mapped)),'plan':plan}

@staff_member_required
@require_http_methods(['GET','POST'])
def supplies(request):
    error='';status=200
    if request.method=='POST':
        try:changed=save_supply(request.POST,request.user);messages.success(request,'Supply records saved.' if changed else 'That stock change was already saved.');return redirect('/supplies/')
        except (ValidationError,IntegrityError) as exc:error=' '.join(exc.messages) if isinstance(exc,ValidationError) else 'That supply name or saved request already exists. Reload to review it.';status=400
    selected=get_object_or_404(RoastPlan,pk=request.GET['plan']) if request.GET.get('plan','').isdigit() else None
    needed=supply_requirements(selected);items=list(SupplyItem.objects.filter(active=True));rate_lookup={}
    for rate in needed['rates']:rate_lookup[rate.pk]=str(rate.version)
    for item in items:
        if item.kind=='bags':need=Decimal(needed['bags'].get(item.size_oz,0))
        elif item.kind=='labels':
            sizes=[Decimal('2.5')] if item.per_sheet==8 else [Decimal(12),Decimal(16),Decimal(80)]
            need=sum(((Decimal(needed['labels'][size])/item.per_sheet).to_integral_value(rounding=ROUND_CEILING) for size in sizes),Decimal(0))
        elif item.kind=='flavoring':need=sum((needed['flavors'].get(rate.coffee_id,Decimal(0))/16*rate.units_per_lb for rate in needed['rates'] if rate.item_id==item.pk),Decimal(0)).quantize(TENTH,rounding=ROUND_CEILING)
        else:need=None
        item.needed=need;item.after_need=item.remaining-need if need is not None else item.remaining;item.low=item.after_need<=item.reorder_at
        item.ticket=ticket(request.user);item.settings_ticket=ticket(request.user)
    counts=[{'size':size,'bags':needed['bags'][size],'labels':needed['labels'][size]} for size in SIZES]
    response=render(request,'portal/supplies.html',{'items':items,'needed':needed,'bag_counts':counts,'error':error,'new_form':SupplyForm(request.POST if request.method=='POST' and request.POST.get('action')=='create' else None),'new_ticket':ticket(request.user),'rate_form':FlavorRateForm(),'rate_ticket':ticket(request.user),'rates':needed['rates'],'plans':RoastPlan.objects.all()[:50],'inactive_items':[{'item':i,'ticket':ticket(request.user)} for i in SupplyItem.objects.filter(active=False)],'movements':SupplyMovement.objects.select_related('item','actor')[:60]},status=status)
    response['Cache-Control']='private, no-store';return response

class MaintenanceForm(forms.ModelForm):
    class Meta:
        model=MaintenanceTask;fields=['roaster','name','interval_days','interval_batches','instructions']
        widgets={'instructions':forms.Textarea(attrs={'rows':2})}
    def clean(self):
        data=super().clean()
        if not data.get('interval_days') and not data.get('interval_batches'):raise forms.ValidationError('Set a positive day interval, batch interval, or both.')
        if any(data.get(key) is not None and not 1<=data[key]<=100000 for key in ['interval_days','interval_batches']):raise forms.ValidationError('Intervals must be positive and at most 100,000.')
        return data

def maintenance_rows():
    today=timezone.localdate();tasks=list(MaintenanceTask.objects.filter(active=True).select_related('roaster'));rows=[]
    services={}
    for service in MaintenanceService.objects.filter(task__in=tasks,date__lte=today,voided_at__isnull=True).order_by('date','recorded_at','pk'):services[service.task_id]=service
    for task in tasks:
        last=services.get(task.pk);date_due=last.date+timedelta(days=task.interval_days) if last and task.interval_days else None
        used=Batch.objects.filter(Q(roasted_at__isnull=False)|Q(roasted_oz__isnull=False),roaster=task.roaster,merged_into__isnull=True,date__lte=today)
        used=used.filter(date__gte=last.date).exclude(pk__in=last.known_batches) if last else used.none()
        count=used.count();due=bool(last and (date_due and date_due<=today or task.interval_batches and count>=task.interval_batches))
        rows.append({'task':task,'last':last,'date_due':date_due,'count':count,'due':due,'baseline_needed':not last,'batches':list(used.order_by('-date','-pk')[:20])})
    return sorted(rows,key=lambda row:(not row['baseline_needed'],not row['due'],row['task'].roaster.name,row['task'].name))

def save_service(post,user):
    key,digest=identity(post,user)
    with transaction.atomic():
        prior=MaintenanceService.objects.filter(request_key=key).first()
        if prior:
            if prior.request_hash!=digest:raise ValidationError('This saved service form had different values. Reload to add another record.')
            return False
        task=get_object_or_404(MaintenanceTask.objects.select_for_update(),pk=post.get('task'),active=True)
        if str(task.version)!=post.get('version'):raise ValidationError('This maintenance record changed. Reload before logging service.')
        date=forms.DateField().clean(post.get('date'))
        if date>timezone.localdate():raise ValidationError('Record service after it is performed, using today or an earlier date.')
        known=list(Batch.objects.filter(Q(roasted_at__isnull=False)|Q(roasted_oz__isnull=False),roaster=task.roaster,merged_into__isnull=True,date__lte=date).values_list('pk',flat=True))
        MaintenanceService.objects.create(task=task,date=date,note=post.get('note','')[:2000],actor=user,known_batches=known,request_key=key,request_hash=digest)
        task.version+=1;task.save(update_fields=['version'])
    return True

@staff_member_required
@require_http_methods(['GET','POST'])
def maintenance(request):
    error='';status=200
    if request.method=='POST':
        try:
            if request.POST.get('action')=='create':
                form=MaintenanceForm(request.POST)
                if not form.is_valid():raise ValidationError([str(e) for errors in form.errors.values() for e in errors])
                task=form.save(commit=False);task.updated_by=request.user;task.save()
            elif request.POST.get('action') in ['deactivate','reactivate']:
                with transaction.atomic():
                    task=get_object_or_404(MaintenanceTask.objects.select_for_update(),pk=request.POST.get('task'))
                    if str(task.version)!=request.POST.get('version'):raise ValidationError('This task changed. Reload before changing availability.')
                    task.active=request.POST['action']=='reactivate';task.version+=1;task.updated_by=request.user;task.save()
            elif request.POST.get('action')=='void':
                with transaction.atomic():
                    service=get_object_or_404(MaintenanceService.objects.select_for_update(),pk=request.POST.get('service'))
                    reason=request.POST.get('reason','').strip()
                    if not 1<=len(reason)<=300:raise ValidationError('Enter a correction reason of 1–300 characters.')
                    if not service.voided_at:
                        service.voided_at=timezone.now();service.voided_by=request.user;service.void_reason=reason;service.save(update_fields=['voided_at','voided_by','void_reason'])
                        MaintenanceTask.objects.filter(pk=service.task_id).update(version=F('version')+1)
            elif request.POST.get('action')=='settings':
                with transaction.atomic():
                    task=get_object_or_404(MaintenanceTask.objects.select_for_update(),pk=request.POST.get('task'),active=True)
                    if str(task.version)!=request.POST.get('version'):raise ValidationError('This schedule changed. Reload before editing.')
                    form=MaintenanceForm(request.POST,instance=task)
                    if not form.is_valid():raise ValidationError([str(e) for errors in form.errors.values() for e in errors])
                    task=form.save(commit=False);task.version+=1;task.updated_by=request.user;task.save()
            else:save_service(request.POST,request.user)
            messages.success(request,'Maintenance records saved.');return redirect('/roasters/maintenance/')
        except (ValidationError,IntegrityError) as exc:error=' '.join(exc.messages) if isinstance(exc,ValidationError) else 'That maintenance task or request already exists. Reload before adding another.';status=400
    rows=maintenance_rows()
    for row in rows:
        row['ticket']=ticket(request.user);row['settings_form']=MaintenanceForm(instance=row['task'],auto_id='maint-'+str(row['task'].pk)+'-%s')
    response=render(request,'portal/maintenance.html',{'rows':rows,'new_form':MaintenanceForm(),'error':error,'inactive_tasks':MaintenanceTask.objects.filter(active=False).select_related('roaster'),'service_history':MaintenanceService.objects.select_related('task__roaster','actor')[:60],'today':timezone.localdate()},status=status)
    response['Cache-Control']='private, no-store';return response

def tools_context(request):
    if not request.user.is_authenticated or not request.user.is_staff or request.path!='/':return {}
    return {'supply_reorder_count':SupplyItem.objects.filter(active=True,remaining__lte=F('reorder_at')).count(),'maintenance_review_count':sum(row['due'] or row['baseline_needed'] for row in maintenance_rows())}
