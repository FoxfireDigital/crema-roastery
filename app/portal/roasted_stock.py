"""Measured whole-bean stock. Reservations never masquerade as roasted batches."""
from datetime import date
from decimal import Decimal,ROUND_CEILING,ROUND_FLOOR
import hashlib,json,uuid
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum,F,Q,Case,When,Value,IntegerField
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from .models import Coffee,RoastPlan,RoastedStock,RoastedStockAllocation,RoastedStockLock,RoastedStockEvent,ROAST_LEVELS

TENTH=Decimal('.1')

def stock_coffees():
    return Coffee.objects.filter(active=True,experimental=False,bulk_stock_enabled=True).exclude(kind='flavored').order_by('name')


def totals(stock):
    reserved=stock.allocations.filter(status='reserved').aggregate(total=Sum('amount_oz'))['total'] or Decimal(0)
    return reserved,Decimal(0) if stock.needs_recount else max(Decimal(0),stock.remaining_oz-reserved)


def token(stock):
    return hashlib.sha256(json.dumps([stock.pk,stock.version,str(stock.remaining_oz),stock.active,stock.needs_recount,str(totals(stock)[0])]).encode()).hexdigest()


def quick_revision():
    rows=list(RoastedStock.objects.order_by('pk').values_list('id','version','remaining_oz','active','coffee_id','roast_level','target_finish_temp_f'))
    return hashlib.sha256(json.dumps([RoastedStockLock.objects.get(pk=1).version,rows,list(stock_coffees().values_list('id','standard_roast'))],default=str).encode()).hexdigest()


@transaction.atomic
def quick_measure(post,actor):
    coffees=list(stock_coffees())
    counts={}
    for coffee in coffees:
        if post.get(f'weighed-{coffee.pk}')!='on':continue
        value=post.get(f'count-{coffee.pk}')
        try:
            value=Decimal(str(value))
            if not value.is_finite() or value<0 or value>999999999 or value!=value.quantize(TENTH):raise ValueError()
        except (ValueError,TypeError,ArithmeticError):raise ValidationError('Enter each weighed count as a nonnegative number in tenths of an ounce.')
        counts[coffee.pk]=value
    if not counts:raise ValidationError('Check “I weighed this” for at least one coffee.')
    ids=RoastedStockAllocation.objects.filter(stock__coffee_id__in=counts,status='reserved').values_list('line__group__plan_id',flat=True)
    plans=list(RoastPlan.all_objects.select_for_update().filter(pk__in=ids).order_by('pk'))
    lock=RoastedStockLock.objects.select_for_update().get(pk=1)
    if post.get('quick_revision')!=quick_revision():raise ValidationError('Stock or reservations changed, or these counts were already saved. Reload before reweighing.')
    changed_plans=set()
    for coffee in coffees:
        if coffee.pk not in counts:continue
        lots=list(RoastedStock.objects.select_for_update().filter(coffee=coffee,roast_level=coffee.standard_roast,target_finish_temp_f__isnull=True,active=True).order_by('created_at','pk'))
        if not lots:
            lot=RoastedStock.objects.create(coffee=coffee,roast_level=coffee.standard_roast,remaining_oz=counts[coffee.pk],recorded_by=actor,measured_at=timezone.now(),note='Quick total measurement')
            event(lot,actor,'quick_measured',{}, {'remaining_oz':str(lot.remaining_oz),'measured_at':lot.measured_at.isoformat()});continue
        # Preserve container identities and give existing reservations first claim.
        budget=counts[coffee.pk];assigned={lot.pk:Decimal(0) for lot in lots}
        for lot in lots:
            take=min(budget,totals(lot)[0]);assigned[lot.pk]+=take;budget-=take
        for lot in lots:
            take=min(budget,max(Decimal(0),lot.remaining_oz-assigned[lot.pk]));assigned[lot.pk]+=take;budget-=take
        assigned[lots[0].pk]+=budget
        for lot in lots:
            before={'remaining_oz':str(lot.remaining_oz),'measured_at':lot.measured_at.isoformat() if lot.measured_at else None}
            lot.remaining_oz=assigned[lot.pk];lot.measured_at=timezone.now();lot.needs_recount=False;lot.version+=1;lot.save(update_fields=['remaining_oz','measured_at','needs_recount','version','updated_at'])
            event(lot,actor,'quick_measured',before,{'remaining_oz':str(lot.remaining_oz),'measured_at':lot.measured_at.isoformat()})
            available=lot.remaining_oz
            for allocation in lot.allocations.filter(status='reserved').select_related('line__group').order_by('pk'):
                kept=min(available,allocation.amount_oz);available-=kept
                if kept==allocation.amount_oz:continue
                changed_plans.add(allocation.line.group.plan_id)
                allocation.status='released';allocation.save(update_fields=['status'])
                event(lot,actor,'count_shortage',{'allocation':allocation.pk,'amount_oz':str(allocation.amount_oz)},{'kept_reserved_oz':str(kept),'remaining_oz':str(lot.remaining_oz)})
                if kept>0:RoastedStockAllocation.objects.create(stock=lot,line=allocation.line,amount_oz=kept)
    if not changed_plans.issubset({p.pk for p in plans}):raise ValidationError('Reservations changed while saving. Reload the stock page.')
    from .plan_actions import mark_revised
    from .autobatches import sync_plan as sync_batches
    for plan in plans:
        if plan.pk in changed_plans:
            mark_revised(plan,actor);sync_batches(plan,actor);plan.version+=1;plan.save(update_fields=['version'])
    lock.version+=1;lock.save(update_fields=['version'])
    return len(counts),len(changed_plans)


def credit(group):
    return RoastedStockAllocation.objects.filter(line__group=group,status__in=['reserved','used']).aggregate(total=Sum('amount_oz'))['total'] or Decimal(0)


def used_for(group):return RoastedStockAllocation.objects.filter(line__group=group,status='used').exists()


def matches(stock,line):
    group=line.group
    if not stock.active or stock.needs_recount or not stock.coffee.active or stock.coffee.kind=='flavored':return False
    if stock.roast_level!=group.roast_level or stock.target_finish_temp_f!=group.target_finish_temp_f:return False
    if stock.coffee_id==line.ordered_coffee.pk:return True
    return line.ordered_coffee.kind=='flavored' and stock.roast_level=='Medium' and stock.target_finish_temp_f is None and stock.coffee.flavor_base_eligible


def line_targets(lines,spillage):
    """Distribute one rounded group target without accumulating rounding extras."""
    spillage=Decimal(str(spillage))
    total=sum((line.finished_oz for line in lines),Decimal(0))
    if not total:return {}
    target=(total*(1+spillage/100)).quantize(TENTH,rounding=ROUND_CEILING)
    exact={line.pk:target*line.finished_oz/total for line in lines}
    amounts={key:value.quantize(TENTH,rounding=ROUND_FLOOR) for key,value in exact.items()}
    spare=int((target-sum(amounts.values(),Decimal(0)))*10)
    for key in sorted(exact,key=lambda key:(-(exact[key]-amounts[key]),key))[:spare]:amounts[key]+=TENTH
    return amounts


def event(stock,actor,action,before,after):RoastedStockEvent.objects.create(stock=stock,actor=actor,action=action,before=before,after=after)


def sync_plan(plan,actor=None):
    """Caller holds the plan lock. Serialize cross-plan stock promises."""
    if plan.closed_at:return False
    with transaction.atomic():
        lock=RoastedStockLock.objects.select_for_update().get(pk=1)
        groups=list(plan.groups.select_related('coffee').order_by('pk'))
        from .batch_state import group_started
        eligible=[group for group in groups if not group_started(group) and not used_for(group)]
        group_ids=[group.pk for group in eligible]
        old=list(RoastedStockAllocation.objects.filter(line__group_id__in=group_ids,status='reserved').select_related('stock','line'))
        lots=list(RoastedStock.objects.filter(active=True,coffee__active=True).exclude(coffee__kind='flavored').select_related('coffee').order_by(F('roasted_on').asc(nulls_last=True),'created_at','pk'))
        old_by_lot={}
        for allocation in old:old_by_lot[allocation.stock_id]=old_by_lot.get(allocation.stock_id,Decimal(0))+allocation.amount_oz
        free={lot.pk:totals(lot)[1]+old_by_lot.get(lot.pk,Decimal(0)) for lot in lots}
        desired={}
        if plan.use_roasted_stock and not plan.removed_at:
            # Specific sold coffees have first claim; flavors may use any other
            # suitable Medium beans, including stock outside the planned base.
            work=[]
            for group in eligible:
                lines=list(group.orders.select_related('group__coffee','product_coffee').order_by('pk'))
                targets=line_targets(lines,plan.spillage_pct)
                work.extend((line,targets[line.pk]) for line in lines)
            work.sort(key=lambda pair:(pair[0].ordered_coffee.kind=='flavored',pair[0].received_at,pair[0].pk))
            for line,needed in work:
                candidates=[lot for lot in lots if free[lot.pk]>0 and matches(lot,line)]
                candidates.sort(key=lambda lot:lot.coffee_id!=line.ordered_coffee.pk)
                for lot in candidates:
                    amount=min(needed,free[lot.pk]).quantize(TENTH,rounding=ROUND_FLOOR)
                    if amount>0:desired[(lot.pk,line.pk)]=amount;free[lot.pk]-=amount;needed-=amount
                    if needed<=0:break
        existing={(allocation.stock_id,allocation.line_id):allocation.amount_oz for allocation in old}
        if existing==desired:return False
        for allocation in old:
            key=(allocation.stock_id,allocation.line_id)
            if desired.get(key)==allocation.amount_oz:continue
            allocation.status='released';allocation.save(update_fields=['status'])
            event(allocation.stock,actor,'released',{'allocation':allocation.pk,'line':allocation.line_id,'amount_oz':str(allocation.amount_oz)},{'plan':plan.pk})
        for (stock_id,line_id),amount in desired.items():
            if existing.get((stock_id,line_id))==amount:continue
            allocation=RoastedStockAllocation.objects.create(stock_id=stock_id,line_id=line_id,amount_oz=amount)
            event(next(lot for lot in lots if lot.pk==stock_id),actor,'reserved',{}, {'allocation':allocation.pk,'plan':plan.pk,'line':line_id,'amount_oz':str(amount)})
        lock.version+=1;lock.save(update_fields=['version']);return True


def release_plan(plan,actor):
    with transaction.atomic():
        lock=RoastedStockLock.objects.select_for_update().get(pk=1)
        allocations=list(RoastedStockAllocation.objects.filter(line__group__plan=plan,status='reserved').select_related('stock'))
        for allocation in allocations:
            allocation.status='released';allocation.save(update_fields=['status'])
            event(allocation.stock,actor,'released',{'allocation':allocation.pk,'amount_oz':str(allocation.amount_oz)},{'plan':plan.pk,'reason':'plan_deleted'})
        if allocations:lock.version+=1;lock.save(update_fields=['version'])


def use_stock(plan,actor):
    if not plan.accepted_at or plan.removed_at or plan.closed_at:raise ValidationError('Accept an active plan before recording its stock as used.')
    with transaction.atomic():
        lock=RoastedStockLock.objects.select_for_update().get(pk=1)
        allocations=list(RoastedStockAllocation.objects.filter(line__group__plan=plan,status='reserved').select_related('stock').order_by('stock_id','pk'))
        if not allocations:raise ValidationError('No unused stock reservations remain for this plan.')
        for allocation in allocations:
            stock=RoastedStock.objects.select_for_update().get(pk=allocation.stock_id)
            if stock.needs_recount or stock.remaining_oz<allocation.amount_oz:raise ValidationError('A stock measurement needs review or a fresh count before recording usage.')
            before=stock.remaining_oz;stock.remaining_oz-=allocation.amount_oz;stock.version+=1
            stock.save(update_fields=['remaining_oz','version','updated_at'])
            allocation.status='used';allocation.save(update_fields=['status'])
            event(stock,actor,'used',{'remaining_oz':str(before)},{'remaining_oz':str(stock.remaining_oz),'allocation':allocation.pk,'plan':plan.pk,'amount_oz':str(allocation.amount_oz)})
        lock.version+=1;lock.save(update_fields=['version'])


class StockForm(forms.Form):
    request_key=forms.UUIDField(widget=forms.HiddenInput,required=False)
    revision=forms.CharField(widget=forms.HiddenInput,required=False)
    coffee=forms.ModelChoiceField(queryset=Coffee.objects.none())
    roast_level=forms.ChoiceField(choices=ROAST_LEVELS,label='Roast level of these beans')
    target_finish_temp_f=forms.DecimalField(max_digits=5,decimal_places=1,min_value=Decimal('.1'),required=False,widget=forms.HiddenInput)
    remaining_oz=forms.DecimalField(max_digits=10,decimal_places=1,min_value=0,label='Measured finished ounces on hand (including reserved beans)')
    roasted_on=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'}),label='Roasted on (optional)')
    note=forms.CharField(max_length=300,required=False,label='Container / batch reference or note')
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.fields['coffee'].queryset=stock_coffees()
    def clean(self):
        data=super().clean();coffee=data.get('coffee')
        if coffee and (data.get('roast_level')!=coffee.standard_roast or data.get('target_finish_temp_f') is not None):raise forms.ValidationError('Bulk stock uses this coffee’s standard roast and no custom temperature.')
        if data.get('roasted_on') and data['roasted_on']>timezone.localdate():self.add_error('roasted_on','Use today or an earlier roast date.')
        return data


@staff_member_required
def stock_page(request):
    editing=get_object_or_404(RoastedStock,pk=request.GET['edit']) if request.GET.get('edit') else None
    initial={'request_key':uuid.uuid4()}
    preferred=stock_coffees().first()
    if preferred:initial.update(coffee=preferred.pk,roast_level=preferred.standard_roast)
    if editing:initial.update({key:getattr(editing,key) for key in ['coffee_id','roast_level','target_finish_temp_f','remaining_oz','roasted_on','note']});initial.update(coffee=editing.coffee_id,revision=token(editing))
    form=StockForm(request.POST if request.method=='POST' and request.POST.get('action') in ['measure','update'] else None,initial=initial)
    try:
        if request.method=='POST':
            action=request.POST.get('action')
            if action=='quick_measure':
                count,affected=quick_measure(request.POST,request.user)
                messages.success(request,f'Saved {count} weighed coffee counts.'+(' Affected plans are back in review; started roast results are preserved.' if affected else ''))
                return redirect('/stock/')
            elif action in ['measure','update'] and form.is_valid():
                data=form.cleaned_data
                with transaction.atomic():
                    locked_plans=[]
                    if action=='update':
                        ids=RoastedStockAllocation.objects.filter(stock_id=request.POST.get('stock'),status='reserved').values_list('line__group__plan_id',flat=True)
                        locked_plans=list(RoastPlan.all_objects.select_for_update().filter(pk__in=ids).order_by('pk'))
                    lock=RoastedStockLock.objects.select_for_update().get(pk=1)
                    if action=='measure':
                        if not data.get('request_key'):raise ValidationError('Reload the stock form before saving.')
                        prior=RoastedStock.objects.filter(request_key=data['request_key']).first()
                        if prior:
                            messages.info(request,'That stock measurement was already recorded. Edit its entry to correct the weight.');return redirect('/stock/')
                        if data['remaining_oz']<=0:raise ValidationError('Enter a positive weight for new stock. Existing entries can be corrected to zero.')
                        lot=RoastedStock.objects.create(recorded_by=request.user,measured_at=timezone.now(),**{key:data[key] for key in ['request_key','coffee','roast_level','target_finish_temp_f','remaining_oz','roasted_on','note']})
                        event(lot,request.user,'measured',{}, {'remaining_oz':str(lot.remaining_oz),'coffee':lot.coffee_id,'roast':lot.roast_level})
                    else:
                        lot=get_object_or_404(RoastedStock.objects.select_for_update(),pk=request.POST.get('stock'))
                        if data['revision']!=token(lot):raise ValidationError('This stock entry or its reservations changed. Reload before correcting it.')
                        reserved,_=totals(lot)
                        changed_profile=data['coffee'].pk!=lot.coffee_id or data['roast_level']!=lot.roast_level or data['target_finish_temp_f']!=lot.target_finish_temp_f
                        if changed_profile and (reserved or lot.allocations.filter(status='used').exists()):raise ValidationError('An entry with reservations or recorded usage keeps its coffee and roast profile. Release reservations first, or add a separate entry for different beans.')
                        affected=list(lot.allocations.filter(status='reserved').select_related('line__group')) if data['remaining_oz']<reserved else []
                        affected_ids={allocation.line.group.plan_id for allocation in affected}
                        if not affected_ids.issubset({plan.pk for plan in locked_plans}):raise ValidationError('A plan reserved these beans while you were updating the count. Reload and enter the current measurement again.')
                        before={key:str(getattr(lot,key)) for key in ['remaining_oz','coffee_id','roast_level','target_finish_temp_f','roasted_on','note']}
                        for key in ['coffee','roast_level','target_finish_temp_f','remaining_oz','roasted_on','note']:setattr(lot,key,data[key])
                        lot.measured_at=timezone.now();lot.needs_recount=False;lot.version+=1;lot.save();event(lot,request.user,'corrected',before,{key:str(getattr(lot,key)) for key in before})
                        if affected:
                            budget=lot.remaining_oz;changed_plans=set()
                            for allocation in affected:
                                kept=min(budget,allocation.amount_oz);budget-=kept
                                if kept==allocation.amount_oz:continue
                                changed_plans.add(allocation.line.group.plan_id)
                                allocation.status='released';allocation.save(update_fields=['status'])
                                event(lot,request.user,'count_shortage',{'allocation':allocation.pk,'amount_oz':str(allocation.amount_oz)},{'remaining_oz':str(lot.remaining_oz),'kept_reserved_oz':str(kept)})
                                if kept>0:RoastedStockAllocation.objects.create(stock=lot,line=allocation.line,amount_oz=kept)
                            from .plan_actions import mark_revised
                            from .autobatches import sync_plan as sync_batches
                            for plan in locked_plans:
                                if plan.pk not in changed_plans:continue
                                mark_revised(plan,request.user)
                                sync_batches(plan,request.user)
                                plan.version+=1;plan.save(update_fields=['version'])
                            messages.warning(request,'The measured count is below the previous reservations. Affected plans are back in review; remaining roasts were recalculated and started records were preserved.')
                    RoastedStockLock.objects.filter(pk=1).update(version=F('version')+1)
                messages.success(request,'Stock measurement saved. Apply available stock to a plan below; existing started work keeps its allocation.');return redirect('/stock/')
            elif action in ['retire','restore']:
                with transaction.atomic():
                    lock=RoastedStockLock.objects.select_for_update().get(pk=1)
                    lot=get_object_or_404(RoastedStock.objects.select_for_update(),pk=request.POST.get('stock'))
                    if request.POST.get('revision')!=token(lot):raise ValidationError('This stock entry changed. Reload before updating it.')
                    if action=='retire' and totals(lot)[0]:raise ValidationError('Release the stock reservation before removing this entry from availability.')
                    lot.active=action=='restore';lot.version+=1;lot.save(update_fields=['active','version','updated_at'])
                    event(lot,request.user,action,{}, {'active':lot.active});lock.version+=1;lock.save(update_fields=['version'])
                return redirect('/stock/')
            elif action in ['apply','fresh','use']:
                with transaction.atomic():
                    plan=get_object_or_404(RoastPlan.objects.select_for_update(),pk=request.POST.get('plan'))
                    if request.POST.get('version')!=str(plan.version):raise ValidationError('The plan changed. Reload before updating its stock reservations.')
                    if action=='use':use_stock(plan,request.user)
                    else:
                        if action=='fresh' and (plan.groups.filter(planned_batches__batch__isnull=False).exists() or RoastedStockAllocation.objects.filter(line__group__plan=plan,status='used').exists()):raise ValidationError('This plan has started. Its committed stock allocations are preserved; use a new plan for different stock choices.')
                        plan.use_roasted_stock=action!='fresh';plan.save(update_fields=['use_roasted_stock'])
                        from .autobatches import sync_plan as sync_batches
                        sync_batches(plan,request.user)
                        from .plan_actions import mark_revised
                        mark_revised(plan,request.user)
                    plan.version+=1;plan.save(update_fields=['version'])
                messages.success(request,'Reserved stock recorded as used.' if action=='use' else 'Stock and automatic roast suggestions updated. Review and accept the plan.')
                return redirect('/stock/?plan='+str(plan.pk))
            elif action not in ['measure','update']:raise ValidationError('Choose a stock action from this page.')
    except (ValidationError,ValueError) as error:messages.error(request,'; '.join(error.messages) if isinstance(error,ValidationError) else 'Choose a valid stock entry.')
    lots=[]
    for lot in RoastedStock.objects.select_related('coffee','recorded_by'):
        reserved,available=totals(lot);lots.append({'stock':lot,'reserved':reserved,'available':available if lot.active else Decimal(0),'revision':token(lot),'older_count':not lot.measured_at or timezone.localdate(lot.measured_at)!=timezone.localdate()})
    quick_rows=[]
    for coffee in stock_coffees():
        entries=[row for row in lots if row['stock'].active and row['stock'].coffee_id==coffee.pk and row['stock'].roast_level==coffee.standard_roast and row['stock'].target_finish_temp_f is None]
        weighed=min((row['stock'].measured_at for row in entries if row['stock'].measured_at),default=None) if entries and all(row['stock'].measured_at for row in entries) else None
        quick_rows.append({'coffee':coffee,'remaining':sum((r['stock'].remaining_oz for r in entries),Decimal(0)) if entries else None,'available':sum((r['available'] for r in entries),Decimal(0)),'reserved':sum((r['reserved'] for r in entries),Decimal(0)),'containers':len(entries),'measured_at':weighed,'older_count':not weighed or timezone.localdate(weighed)!=timezone.localdate()})
    plans=list(RoastPlan.objects.all()[:50]);plan=next((plan for plan in plans if str(plan.pk)==request.GET.get('plan')),None) or (plans[0] if plans else None)
    allocations=RoastedStockAllocation.objects.filter(line__group__plan=plan,status__in=['reserved','used']).select_related('stock__coffee','line__group__coffee','line__product_coffee') if plan else []
    from .finished_coverage import plan_coverage
    return render(request,'portal/roasted_stock.html',{'coverage':plan_coverage(plan) if plan else None,'form':form,'editing':editing,'lots':lots,'quick_rows':quick_rows,'quick_revision':quick_revision(),'plans':plans,'plan':plan,'allocations':allocations,'coffees_json':{str(c.pk):{'roast':c.standard_roast,'locked':True} for c in stock_coffees()},'events':RoastedStockEvent.objects.select_related('stock__coffee','actor')[:40]})
