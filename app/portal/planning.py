from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, InvalidOperation
import hashlib,json
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from .models import Coffee,LabelVariant,Roaster,Batch,CustomOrder,RoastPlan,RoastGroup,IncomingOrderLine,PlannedBatch,ROAST_LEVELS,GRIND_CHOICES

CENT=Decimal('.01')
TENTH=Decimal('.1')
def number(value):
    try:result=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError):raise ValidationError('Enter a valid quantity.')
    if not result.is_finite():raise ValidationError('Enter a finite quantity.')
    return result

def split_weights(total,capacity):
    total=number(total).quantize(TENTH,rounding=ROUND_CEILING);capacity=number(capacity).quantize(TENTH,rounding=ROUND_FLOOR)
    if total<=0:return []
    if capacity<TENTH:raise ValidationError('Configure a roaster capacity of at least 0.1 oz.')
    count=int((total/capacity).to_integral_value(rounding=ROUND_CEILING))
    if count>1000:raise ValidationError('This plan exceeds 1,000 batches; reduce the planning quantity.')
    units=int(total*10);low,extra=divmod(units,count)
    return [Decimal(low+(i<extra))/10 for i in range(count)]

def profile_key(coffee,roast,temp,label,legacy=None):
    return hashlib.sha256(json.dumps([coffee,roast,str(temp.normalize()) if temp is not None else None,label,legacy]).encode()).hexdigest()

def summary(group,loss,spillage=None):
    loss=number(group.loss_override if group.loss_override is not None else loss)
    target=group.orders.aggregate(total=Sum('finished_oz'))['total'] or Decimal(0)
    spillage=number(group.plan.spillage_pct if spillage is None else spillage)
    production_target=(target*(1+spillage/100)).quantize(TENTH,rounding=ROUND_CEILING)
    rows=list(group.planned_batches.select_related('roaster','batch'))
    from .yield_learning import row_loss
    for row in rows:row.display_loss=row_loss(row,loss)
    yield_factor=1-loss/100
    from .batch_state import committed
    actual_rows=[r for r in rows if r.batch_id and committed(r.batch)]
    started=sum((r.batch.roasted_oz if r.batch.roasted_oz is not None else r.batch.green_oz*(1-r.display_loss/100) for r in actual_rows),Decimal(0))
    drafted=sum((r.green_oz for r in rows if r not in actual_rows),Decimal(0))
    from .roasted_stock import credit,used_for
    stock=credit(group);covered=started+stock
    started_work=bool(actual_rows) or used_for(group)
    required_target=target if started_work else production_target
    need=(max(Decimal(0),required_target-covered)/yield_factor).quantize(TENTH,rounding=ROUND_CEILING)
    expected=covered+sum((r.green_oz*(1-r.display_loss/100) for r in rows if r not in actual_rows),Decimal(0))
    return {'group':group,'loss':loss,'target':target,'production_target':production_target,'required_target':required_target,'started_work':started_work,'customer_shortfall':max(Decimal(0),target-expected),'reserve_shortfall':max(Decimal(0),production_target-max(target,expected)),'reserve':production_target-target,'target_lb':target/16,'started':started,'stock':stock,'covered':covered,'green_needed':need,'rows':rows,'draft_green':drafted,'expected':expected,'difference':expected-production_target}

class IncomingForm(forms.Form):
    reference=forms.CharField(max_length=100,required=False,label='Order / stock reference')
    customer=forms.CharField(max_length=120,required=False)
    coffee=forms.ModelChoiceField(queryset=Coffee.objects.none())
    label_variant=forms.ModelChoiceField(queryset=LabelVariant.objects.none(),required=False,label='Packaging label')
    bags_1lb=forms.IntegerField(min_value=0,max_value=100000,required=False,label='1 lb bags',initial=0)
    bags_5lb=forms.IntegerField(min_value=0,max_value=10000,required=False,label='5 lb bags',initial=0)
    extra_oz=forms.DecimalField(max_digits=10,decimal_places=2,min_value=0,required=False,label='Other finished oz',initial=0)
    roast_level=forms.ChoiceField(choices=ROAST_LEVELS,initial='Medium')
    target_finish_temp_f=forms.DecimalField(max_digits=5,decimal_places=1,min_value=Decimal('.1'),required=False,label='Custom finish temperature (°F, optional)')
    grind=forms.ChoiceField(choices=GRIND_CHOICES,initial='unknown',required=False,label='Bagging / grind')
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        coffees=Coffee.objects.filter(active=True,experimental=False);labels=LabelVariant.objects.filter(active=True,coffee__active=True)
        self.fields['coffee'].queryset=coffees;self.fields['label_variant'].queryset=labels
        self.fields['coffee'].widget.attrs['data-incoming-policies']=json.dumps({str(c.pk):{'locked':c.roast_locked,'roast':c.standard_roast} for c in coffees})
        self.fields['label_variant'].widget.attrs['data-label-map']=json.dumps({str(l.pk):l.coffee_id for l in labels})
    def clean(self):
        data=super().clean()
        quantity=Decimal(data.get('bags_1lb') or 0)*16+Decimal(data.get('bags_5lb') or 0)*80+(data.get('extra_oz') or 0)
        data['finished_oz']=quantity
        if quantity<=0:self.add_error('bags_1lb','Enter the finished quantity ordered, using any of the three quantity fields.')
        c=data.get('coffee');label=data.get('label_variant')
        if c:
            if c.kind=='flavored' and (not c.roast_base_id or not c.roast_base.active):self.add_error('coffee','Choose an active Medium default roast base for this flavor in Coffee Admin.')
            locked=c.roast_locked or quantity<80
            if locked:
                if not c.standard_roast:self.add_error('coffee','Set this coffee’s standard roast in Admin first.')
                elif data.get('roast_level')!=c.standard_roast:self.add_error('roast_level',f'This order uses standard {c.standard_roast}. Only single-origin lines of 5 lb or more can change roast.')
                if data.get('target_finish_temp_f') is not None:self.add_error('target_finish_temp_f','This order cannot request a custom temperature.')
            if label and label.coffee_id!=c.pk:self.add_error('label_variant','This label belongs to a different coffee.')
        return data

def group_for(plan,data,legacy=None):
    from .flavoring import production_profile
    coffee,label=production_profile(plan,data,legacy)
    key=profile_key(coffee.pk,data['roast_level'],data.get('target_finish_temp_f'),label.pk if label else None,legacy.pk if legacy else None)
    group,_=RoastGroup.objects.get_or_create(plan=plan,key=key,defaults={'coffee':coffee,'roast_level':data['roast_level'],'target_finish_temp_f':data.get('target_finish_temp_f'),'label_variant':label,'legacy_order':legacy})
    return group

@staff_member_required
def planner(request):
    plan_id=request.POST.get('plan') or request.GET.get('plan')
    if request.method=='GET' and plan_id and str(plan_id).isdigit():
        completed=RoastPlan.all_objects.filter(pk=plan_id,closed_at__isnull=False).first()
        if completed:return redirect('completed_plan',pk=completed.pk)
        archived=RoastPlan.all_objects.filter(pk=plan_id,historical=True).first()
        if archived:return redirect('past_plan',pk=archived.pk)
    plan=get_object_or_404(RoastPlan,pk=plan_id) if plan_id else RoastPlan.objects.first()
    form=IncomingForm()
    status=200
    editing=None
    if plan and request.GET.get('edit'):
        editing=get_object_or_404(IncomingOrderLine,pk=request.GET['edit'],group__plan=plan)
        if editing.source!='manual':return redirect('order_detail',pk=editing.group.legacy_order_id)
        g=editing.group
        bags1=sum(int(item['bags']) for item in editing.packaging if Decimal(str(item['size_oz']))==16)
        bags5=sum(int(item['bags']) for item in editing.packaging if Decimal(str(item['size_oz']))==80)
        form=IncomingForm(initial={'reference':editing.reference,'customer':editing.customer,'coffee':editing.ordered_coffee.pk,'label_variant':editing.ordered_label.pk if editing.ordered_label else None,'bags_1lb':bags1,'bags_5lb':bags5,'extra_oz':max(Decimal(0),editing.finished_oz-bags1*16-bags5*80),'roast_level':g.roast_level,'target_finish_temp_f':g.target_finish_temp_f,'grind':editing.grind})
    if request.method=='POST':
        action=request.POST.get('action','')
        if action.startswith('import_') and action!='import_orders':
            from .order_import import stage_export,add_selected,remove_import
            try:
                if action=='import_upload':
                    upload=request.FILES.get('orders_csv')
                    if not upload or upload.size>5*1024*1024:raise ValidationError('Choose a Shopify orders CSV smaller than 5 MB.')
                    count=stage_export(upload.read());messages.success(request,f'Refreshed {count} orders. Ready orders can be selected below; other orders show what needs attention.')
                elif action=='import_add':
                    if not plan:raise ValidationError('Create a roast plan first.')
                    if request.POST.get('remove_order'):
                        remove_import(request.POST['remove_order'],request.user);messages.success(request,'Order removed from the plan. Select it in the review list to restore it.')
                    else:
                        count=add_selected(plan,request.POST.getlist('orders'),request.user);messages.success(request,f'Added {count} orders. Their coffee totals and batch controls are below.')
                elif action=='import_remove':remove_import(request.POST.get('order'),request.user);messages.success(request,'Order removed from the plan. Its original items are retained in the review list for restoring.')
                else:raise ValidationError('Unknown order action.')
            except ValidationError as error:messages.error(request,'; '.join(error.messages))
            return redirect('/planning/'+('?plan='+str(plan.pk) if plan else '')+'#order-review')
        try:
            if action=='new_plan':
                from django.utils.dateparse import parse_date
                day=parse_date(request.POST.get('date','')) if request.POST.get('date') else timezone.localdate()
                if day is None:raise ValidationError('Choose a valid date for the roast plan.')
                plan=RoastPlan.objects.create(created_by=request.user,date=day)
                return redirect('/planning/?plan='+str(plan.pk))
            if not plan:raise ValidationError('Create a roast plan first.')
            with transaction.atomic():
                plan=RoastPlan.objects.select_for_update().get(pk=plan.pk)
                if request.POST.get('version')!=str(plan.version):
                    raise ValidationError('This plan changed in another tab. Refresh before saving so you do not overwrite that change.')
                if action in ('add_order','edit_order'):
                    if action=='edit_order':editing=get_object_or_404(IncomingOrderLine,pk=request.POST.get('line'),group__plan=plan,source='manual')
                    form=IncomingForm(request.POST)
                    if not form.is_valid():
                        status=400
                    else:
                        data=form.cleaned_data
                        line=None
                        if action=='edit_order':
                            line=get_object_or_404(IncomingOrderLine,pk=request.POST.get('line'),group__plan=plan,source='manual')
                            old=line.group
                            from .flavoring import production_profile
                            roast_coffee,roast_label=production_profile(plan,data)
                            new_key=profile_key(roast_coffee.pk,data['roast_level'],data.get('target_finish_temp_f'),roast_label.pk if roast_label else None)
                            from .roasted_stock import used_for
                            if old.key!=new_key and (old.planned_batches.filter(batch__isnull=False).exists() or used_for(old)):raise ValidationError('This coffee profile has already started. Keep its roast and label; add a new line for a different profile.')
                        g=group_for(plan,data)
                        if line is None:line=IncomingOrderLine(group=g)
                        from .flavoring import manual_packaging
                        packaging=manual_packaging(data)
                        if line.wholesale_order_id and len(line.packaging)==1 and not packaging:
                            pack=line.packaging[0];size=Decimal(str(pack['size_oz']));bags=data['finished_oz']/size
                            if bags!=bags.to_integral_value() or not 1<=bags<=10000:
                                raise ValidationError(f'Keep this wholesale row in whole {size:g} oz bags, or remove it and add a new row for a different bag size.')
                            packaging=[{**pack,'bags':int(bags)}]
                        line.group=g;line.reference=data['reference'];line.customer=data['customer'];line.finished_oz=data['finished_oz'];line.product_coffee=data['coffee'];line.product_label=data.get('label_variant');line.packaging=packaging;line.grind=data.get('grind') or 'unknown';line.save()
                        messages.success(request,'Order saved. Suggested drafts update automatically; any manually adjusted drafts keep their saved weights.')
                elif action=='remove_order':
                    line=get_object_or_404(IncomingOrderLine,pk=request.POST.get('line'),group__plan=plan,source='manual')
                    from .roasted_stock import used_for
                    if line.group.planned_batches.filter(batch__isnull=False).exists() or used_for(line.group):raise ValidationError('This profile has started production or used stock. Keep its order history and record corrections separately.')
                    g=line.group;line.removed_at=timezone.now();line.save(update_fields=['removed_at'])
                elif action=='restore_order':
                    line=get_object_or_404(IncomingOrderLine.all_objects,pk=request.POST.get('line'),group__plan=plan,source='manual',removed_at__isnull=False)
                    line.removed_at=None;line.save()
                    messages.success(request,'Order restored. Review the updated coffee total before sizing batches.')
                elif action=='restore_batch':
                    row=get_object_or_404(PlannedBatch.all_objects,pk=request.POST.get('row'),group__plan=plan,batch__isnull=True,removed_at__isnull=False)
                    if not row.group.orders.exists() or not row.roaster.active:raise ValidationError('Restore the order and choose an active roaster before restoring this draft.')
                    row.group.auto_batches=False;row.group.save(update_fields=['auto_batches'])
                    row.removed_at=None;row.save()
                elif action=='profile_loss':
                    g=get_object_or_404(RoastGroup,pk=request.POST.get('group'),plan=plan)
                    loss=number(request.POST.get('profile_loss'))
                    if loss<0 or loss>=50:raise ValidationError('Use a profile loss estimate from 0 to less than 50%.')
                    g.loss_override=loss.quantize(Decimal('.1'));g.save(update_fields=['loss_override']);g.planned_batches.filter(batch__isnull=True).update(estimated_loss_pct=None,yield_basis={})
                    from .models import PlanEvent
                    PlanEvent.objects.create(plan=plan,actor=request.user,action='profile_loss',details={'group':g.pk,'coffee':g.coffee_id,'roast':g.roast_level,'loss':str(g.loss_override)})
                    messages.success(request,'Loss estimate saved for this coffee and roast. Actual green inputs and finished weights are preserved; started profiles do not gain automatic top-ups.')
                elif action in ('apply_yield','reset_yield'):
                    g=get_object_or_404(RoastGroup,pk=request.POST.get('group'),plan=plan)
                    if action=='apply_yield':raise ValidationError('Choose the machine and load-specific estimate beside a draft batch. Reload the plan.')
                    g.loss_override=None;g.save(update_fields=['loss_override'])
                    g.planned_batches.filter(batch__isnull=True).update(estimated_loss_pct=None,yield_basis={})
                elif action in ('apply_load_yield','reset_load_yield'):
                    from .yield_learning import suggestion,band,row_loss
                    row=get_object_or_404(PlannedBatch.objects.select_related('group__coffee','roaster'),pk=request.POST.get('row'),group__plan=plan,batch__isnull=True)
                    if action=='reset_load_yield':row.estimated_loss_pct=None;row.yield_basis={}
                    else:
                        estimate=suggestion(row.group,row.roaster,row.green_oz,row_loss(row,row.group.loss_override if row.group.loss_override is not None else plan.estimated_loss_pct))
                        if not estimate or request.POST.get('yield_revision')!=estimate['revision']:raise ValidationError('The matching roast history changed or lacks three reliable samples. Reload and review the current estimate.')
                        if not estimate['fits'] or not estimate['same_band']:raise ValidationError('The estimated weight crosses this load band or machine capacity. Split or resize deliberately, then review a matching estimate.')
                        row.green_oz=estimate['recommended_green'];row.estimated_loss_pct=estimate['loss']
                        row.yield_basis={key:str(value) if isinstance(value,Decimal) else value for key,value in estimate.items() if key in ['roaster','machine','band','loss','samples','records','revision']}
                    row.full_clean();row.save();row.group.auto_batches=False;row.group.save(update_fields=['auto_batches'])
                    from .models import PlanEvent
                    PlanEvent.objects.create(plan=plan,actor=request.user,action='load_yield',details={'row':row.pk,'green':str(row.green_oz),'basis':row.yield_basis})
                    messages.success(request,'Draft estimate updated for this machine and green-load range. Actual batches remain unchanged.')
                elif action=='loss':
                    loss=number(request.POST.get('loss'))
                    if loss<0 or loss>=50:raise ValidationError('Use a roast-loss estimate from 0 to less than 50%.')
                    plan.estimated_loss_pct=loss.quantize(Decimal('.1'))
                elif action=='spillage':
                    allowance=number(request.POST.get('spillage'))
                    if allowance<0 or allowance>25:raise ValidationError('Use a spillage allowance from 0 to 25%.')
                    plan.spillage_pct=allowance.quantize(TENTH)
                elif action=='import_orders':
                    imported=0
                    for order in CustomOrder.objects.filter(fulfilled_at__isnull=True,cancelled_at__isnull=True).select_related('coffee','label_variant'):
                        if RoastGroup.objects.filter(legacy_order=order).exists():continue
                        qty=max(Decimal(0),Decimal(order.target_roasted_oz)-Decimal(str(order.sealed_roasted_oz)))
                        if not qty:continue
                        if order.batches.filter(sealed_at__isnull=True).exists():continue
                        data={'coffee':order.coffee,'label_variant':order.label_variant,'roast_level':order.roast_level,'target_finish_temp_f':order.target_finish_temp_f}
                        # Existing legacy records retain their original requests.
                        g=group_for(plan,data,order)
                        IncomingOrderLine.objects.bulk_create([IncomingOrderLine(group=g,product_coffee=order.coffee,product_label=order.label_variant,packaging=[{'size_oz':'80','bags':order.bags_5lb}] if qty==order.target_roasted_oz else [],reference=order.order_reference or f'Custom #{order.pk}',customer=order.customer_name,finished_oz=qty,source='custom_order',received_at=order.created_at)])
                        imported+=1
                    messages.success(request,f'Imported {imported} open custom orders. Orders with an in-progress batch were left in their existing workflow.')
                elif action in ('suggest','suggest_auto'):
                    g=get_object_or_404(RoastGroup,pk=request.POST.get('group'),plan=plan)
                    if action=='suggest_auto':
                        machines=sorted([r for r in Roaster.objects.filter(active=True) if r.capacity and r.capacity>0],key=lambda r:r.capacity)
                        if not machines:raise ValidationError('Set up an active roaster first.')
                        needed=summary(g,plan.estimated_loss_pct)['green_needed'];roaster=next((r for r in machines if r.capacity>=needed),machines[-1])
                    else:roaster=get_object_or_404(Roaster,pk=request.POST.get('roaster'),active=True)
                    if not roaster.capacity:raise ValidationError('Configure this roaster’s capacity first.')
                    g.auto_batches=action=='suggest_auto';g.save(update_fields=['auto_batches'])
                    weights=split_weights(summary(g,plan.estimated_loss_pct)['green_needed'],roaster.capacity)
                    g.planned_batches.filter(batch__isnull=True).update(removed_at=timezone.now())
                    for weight in weights:PlannedBatch.objects.create(group=g,roaster=roaster,green_oz=weight)
                elif action=='add_batch':
                    g=get_object_or_404(RoastGroup,pk=request.POST.get('group'),plan=plan)
                    g.auto_batches=False;g.save(update_fields=['auto_batches'])
                    roaster=get_object_or_404(Roaster,pk=request.POST.get('roaster'),active=True)
                    PlannedBatch.objects.create(group=g,roaster=roaster,green_oz=min((roaster.capacity or Decimal(0)).quantize(TENTH,rounding=ROUND_FLOOR),max(TENTH,summary(g,plan.estimated_loss_pct)['green_needed'])))
                elif action in ('save_batch','split_batch','remove_batch','start_batch'):
                    row=get_object_or_404(PlannedBatch.objects.select_related('group__coffee','group__label_variant'),pk=request.POST.get('row'),group__plan=plan)
                    if row.batch_id:raise ValidationError('This batch has already started; its production record is preserved.')
                    if action!='start_batch':row.group.auto_batches=False;row.group.save(update_fields=['auto_batches'])
                    if action=='remove_batch':row.removed_at=timezone.now();row.save(update_fields=['removed_at'])
                    else:
                        row.roaster=get_object_or_404(Roaster,pk=request.POST.get('roaster'),active=True)
                        weight=number(request.POST.get('green_oz'))
                        if weight!=weight.quantize(TENTH):raise ValidationError('Enter green weight in tenths of an ounce, for example 40.0.')
                        row.green_oz=weight.quantize(TENTH)
                        row.full_clean()
                        if action=='split_batch':
                            if row.green_oz<Decimal('.2'):raise ValidationError('At least 0.2 oz is needed to split this row.')
                            second=(row.green_oz/2).quantize(TENTH,rounding=ROUND_FLOOR)
                            row.green_oz-=second
                            PlannedBatch.objects.create(group=row.group,roaster=row.roaster,green_oz=second)
                        if action=='start_batch':
                            if not row.group.orders.exists():raise ValidationError('This profile no longer has any demand. Remove the draft batch.')
                            from .models import ImportOrder
                            ids=[line.external_id.split(':')[0] for line in row.group.orders.filter(source__in=['shopify','store'])]
                            included=ImportOrder.objects.filter(external_id__in=ids)
                            if included.filter(source_changed=True).exists() or included.exclude(financial_status='paid',fulfillment_status='unfulfilled',cancelled=False).exists():raise ValidationError('An included Shopify order changed after import. Review it in the order list before starting production.')
                            # Save only after weighing; this never controls the machine.
                            b=Batch.objects.create(date=plan.date,operator=request.user,roaster=row.roaster,coffee=row.group.coffee,label_variant=row.group.label_variant,green_oz=row.green_oz,roast_level=row.group.roast_level,order=row.group.legacy_order,planned_group=row.group,measured_at=timezone.now(),note=f'Roast plan #{plan.pk}; '+(f'target {row.group.target_finish_temp_f} F' if row.group.target_finish_temp_f is not None else 'standard roast'))
                            row.batch=b
                        from .yield_learning import row_loss
                        if row.estimated_loss_pct is not None and row_loss(row,Decimal(-1))<0:row.estimated_loss_pct=None;row.yield_basis={}
                        row.save()
                else:raise ValidationError('Unknown planning action.')
                if status==200:
                    from .autobatches import sync_plan
                    if action!='start_batch' or not plan.accepted_at:sync_plan(plan,request.user)
                    from .plan_actions import mark_revised
                    if action!='start_batch' and mark_revised(plan,request.user):messages.info(request,'Plan changed. Accept the updated plan to return it to the front page.')
                    plan.version+=1;plan.save(update_fields=['version','estimated_loss_pct','spillage_pct'])
                    if action=='start_batch':return redirect('batch_detail',pk=row.batch_id)
                    return redirect('/planning/?plan='+str(plan.pk))
        except (ValidationError,InvalidOperation,ValueError) as error:
            messages.error(request,'; '.join(error.messages) if isinstance(error,ValidationError) else 'Enter a valid quantity.')
            status=400
        if plan:plan.refresh_from_db()
    from .production import yield_suggestion
    groups=[];total_target=Decimal(0);total_green=Decimal(0)
    if plan:
        from .finished_coverage import plan_coverage
        finished=plan_coverage(plan)
        by_group={item['group_id']:item for item in finished['rows']}
        for group in plan.groups.select_related('coffee','label_variant','legacy_order'):
            data=summary(group,plan.estimated_loss_pct)
            data['finished_coverage']=by_group.get(group.pk)
            data['suggestion']=None
            for row in data['rows']:
                row.yield_suggestion=yield_suggestion(group,row.roaster,row.green_oz,row.display_loss) if not row.batch_id else None
            data['references']=list(group.orders.values_list('reference',flat=True).distinct())
            if data['target'] or data['rows']:groups.append(data)
            total_target+=data['target'];total_green+=data['green_needed']
    orders=IncomingOrderLine.objects.filter(group__plan=plan).select_related('group__coffee','group__label_variant','import_order__store') if plan else []
    missing_defaults=Coffee.objects.filter(active=True,experimental=False,kind='single_origin',standard_roast='')
    context={'plan':plan,'plans':RoastPlan.objects.all()[:25],'form':form,'editing':editing,'groups':groups,'orders':orders,'roasters':Roaster.objects.filter(active=True),'total_target':total_target,'total_green':total_green,'missing_defaults':missing_defaults}
    for machine in context['roasters']:machine.yield_mid=(machine.capacity or Decimal(0))/2
    context['coverage']=finished if plan else None
    from .views import clock_context
    from .order_import import import_rows
    from .models import HistoricalRoast
    rows=import_rows()
    context.update(clock_context(request.user))
    from .plan_actions import accepted_boards
    context.update({'frontpage':request.path=='/','accepted_boards':accepted_boards() if request.path=='/' else []})
    if context['accepted_boards']:
        accepted_ids={row.group.plan_id for board in context['accepted_boards'] for row in board['rows']}
        context['total_target']=IncomingOrderLine.objects.filter(group__plan_id__in=accepted_ids).aggregate(total=Sum('finished_oz'))['total'] or Decimal(0)
    context.update({'rows':rows,'ready_count':sum(row['ready'] for row in rows),'review_count':sum(row['category']=='review' for row in rows),'held_count':sum(row['category']=='held' for row in rows),'workbench':True,'today':timezone.localdate(),'active_batches':Batch.objects.filter(sealed_at__isnull=True,merged_into__isnull=True).select_related('coffee','roaster','label_variant','planned_group','order').order_by('date','pk')[:50],'historical_count':HistoricalRoast.objects.count(),'removed_orders':IncomingOrderLine.all_objects.filter(group__plan=plan,removed_at__isnull=False,source='manual').select_related('group__coffee')[:30] if plan else [],'removed_drafts':PlannedBatch.all_objects.filter(group__plan=plan,removed_at__isnull=False,batch__isnull=True).select_related('group__coffee','roaster').order_by('-removed_at')[:30] if plan else []})
    from .production import state_token
    context['active_batches']=list(context['active_batches'])
    for batch in context['active_batches']:batch.revision=state_token(batch)
    from .green_review import review_context
    context['green_review']=review_context(plan) if plan else None
    return render(request,'portal/planning.html',context,status=status)
