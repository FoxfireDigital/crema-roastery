"""Read-only selection estimates and atomic multi-row planning changes."""
import json,uuid
from decimal import Decimal,ROUND_CEILING
from types import SimpleNamespace
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404,redirect
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from .models import Coffee,RoastPlan,RoastGroup,PlannedBatch,IncomingOrderLine,ImportOrder,PlanEvent,Roaster,RoastedStock,RoastedStockAllocation


def selected_orders(ids):
    from .order_import import readiness
    try:ids={int(value) for value in ids}
    except (ValueError,TypeError):raise ValidationError('Select valid orders.')
    if not ids or len(ids)>250:raise ValidationError('Select between 1 and 250 orders.')
    orders=list(ImportOrder.objects.filter(pk__in=ids).order_by('pk'))
    if len(orders)!=len(ids):raise ValidationError('The selected order list changed. Refresh it.')
    for order in orders:
        ready,reason=readiness(order)
        if not ready:raise ValidationError(f'{order.reference}: {reason}')
    return orders


def selection_estimate(ids,plan=None):
    """Use the same capacity, spillage, yield and stock matching rules, without writes."""
    from .order_import import line_data
    from .planning import IncomingForm,split_weights
    from .roasted_stock import totals,line_targets,matches,credit
    orders=selected_orders(ids);entries=[];groups={};fake_id=-1
    if plan:
        for line in IncomingOrderLine.objects.filter(group__plan=plan).select_related('group__coffee','product_coffee','product_label'):
            entries.append({'line':line,'coffee':line.group.coffee,'label_id':line.group.label_variant_id,'temp':line.group.target_finish_temp_f,'roast':line.group.roast_level,'legacy':line.group.legacy_order_id,'saved':line.group,'existing':True})
    coffees={c.pk:c for c in Coffee.objects.select_related('roast_base').all()}
    for order in orders:
        for item in order.lines:
            data=line_data(item)
            if data is None:continue
            form=IncomingForm(data);assert form.is_valid()
            clean=form.cleaned_data;c=coffees[clean['coffee'].pk]
            line=SimpleNamespace(pk=fake_id,finished_oz=clean['finished_oz'],ordered_coffee=c,received_at=order.received_at)
            fake_id-=1
            entries.append({'line':line,'coffee':c,'label_id':clean['label_variant'].pk if clean.get('label_variant') else None,'temp':clean.get('target_finish_temp_f'),'roast':clean['roast_level'],'legacy':None,'saved':None,'existing':False})
    real_medium=[]
    for position,entry in enumerate(entries):
        c=entry['line'].ordered_coffee
        if c.kind!='flavored' and c.flavor_base_eligible and entry['roast']=='Medium' and entry['temp'] is None and entry['label_id'] is None and entry['legacy'] is None:real_medium.append((c,entry['saved'].pk if entry['saved'] else 1000000000+position))
    from .instance import default_base
    preferred=default_base()
    real_medium.sort(key=lambda pair:(pair[0].pk!=getattr(preferred,'pk',None),pair[1]))
    for entry in entries:
        c=entry['line'].ordered_coffee;saved=entry['saved']
        committed=saved and (saved.planned_batches.filter(batch__isnull=False).exists() or RoastedStockAllocation.objects.filter(line__group=saved,status='used').exists())
        if c.kind=='flavored' and c.roast_base_id and not committed:
            entry['coffee']=real_medium[0][0] if real_medium else coffees[c.roast_base_id];entry['label_id']=None
        key=(entry['coffee'].pk,entry['roast'],entry['temp'],entry['label_id'],entry['legacy'])
        group=groups.setdefault(key,{'coffee':entry['coffee'],'roast':entry['roast'],'temp':entry['temp'],'entries':[],'saved':[]})
        group['entries'].append(entry)
        if saved and saved.pk not in [g.pk for g in group['saved']]:group['saved'].append(saved)
    lots=list(RoastedStock.objects.filter(active=True,coffee__active=True).exclude(coffee__kind='flavored').select_related('coffee').order_by('created_at','pk'))
    free={lot.pk:totals(lot)[1] for lot in lots};work=[]
    loss=plan.estimated_loss_pct if plan else Decimal(16);spillage=plan.spillage_pct if plan else Decimal(5)
    for group in groups.values():
        started_rows=[row for saved in group['saved'] for row in saved.planned_batches.select_related('batch') if row.batch_id]
        group['committed']=bool(started_rows) or any(RoastedStockAllocation.objects.filter(line__group=saved,status='used').exists() for saved in group['saved'])
        group['stock']=sum((credit(saved) for saved in group['saved']),Decimal(0)) if group['committed'] else Decimal(0)
        overrides={saved.loss_override for saved in group['saved'] if saved.loss_override is not None}
        group['loss']=next(iter(overrides)) if len(overrides)==1 else loss
        factor=1-group['loss']/100
        group['started']=sum((row.batch.roasted_oz if row.batch.roasted_oz is not None else row.green_oz*factor for row in started_rows),Decimal(0))
        if not group['committed']:
            for allocation in RoastedStockAllocation.objects.filter(line__group__in=group['saved'],status='reserved'):
                free[allocation.stock_id]=free.get(allocation.stock_id,Decimal(0))+allocation.amount_oz
            lines=[entry['line'] for entry in group['entries']];targets=line_targets(lines,spillage)
            for line in lines:
                probe=SimpleNamespace(roast_level=group['roast'],target_finish_temp_f=group['temp'])
                # Real ORM objects here are read-only; avoid assigning a fake FK.
                work.append((SimpleNamespace(pk=line.pk,ordered_coffee=line.ordered_coffee,received_at=line.received_at,group=probe),targets[line.pk],group))
    if not plan or plan.use_roasted_stock:
        work.sort(key=lambda job:(job[0].ordered_coffee.kind=='flavored',job[0].received_at,job[0].pk))
        for line,need,group in work:
            candidates=[lot for lot in lots if free[lot.pk]>0 and matches(lot,line)]
            candidates.sort(key=lambda lot:lot.coffee_id!=line.ordered_coffee.pk)
            for lot in candidates:
                amount=min(need,free[lot.pk]);group['stock']+=amount;free[lot.pk]-=amount;need-=amount
                if need<=0:break
    machines=sorted([r for r in Roaster.objects.filter(active=True) if r.capacity and r.capacity>=Decimal('.1')],key=lambda r:(r.capacity,r.pk))
    result=[]
    for group in groups.values():
        target=sum((entry['line'].finished_oz for entry in group['entries']),Decimal(0))
        production=(target*(1+spillage/100)).quantize(Decimal('.1'),rounding=ROUND_CEILING)
        green=(max(Decimal(0),production-group['stock']-group['started'])/(1-group['loss']/100)).quantize(Decimal('.1'),rounding=ROUND_CEILING)
        machine=next((r for r in machines if r.capacity>=green),machines[-1] if machines else None)
        result.append({'coffee':group['coffee'].name,'roast':group['roast'],'temperature':str(group['temp']) if group['temp'] else None,'ordered_oz':str(target),'target_oz':str(production),'stock_oz':str(group['stock']),'recorded_oz':str(group['started'].quantize(Decimal('.1'))),'green_oz':str(green),'machine':machine.name if machine and green else None,'loads':[str(w) for w in split_weights(green,machine.capacity)] if machine and green else [],'needs_roaster':bool(green and not machine)})
    result.sort(key=lambda g:(g['coffee'],g['roast']))
    return {'orders':len(orders),'includes_existing_plan':bool(plan),'plan_version':plan.version if plan else None,'spillage_pct':str(spillage),'groups':result,'stock_is_estimate':True}


@staff_member_required
@require_POST
def preview_selection(request):
    try:
        plan=get_object_or_404(RoastPlan,pk=request.POST['plan']) if request.POST.get('plan') not in [None,'','new'] else None
        return JsonResponse(selection_estimate(request.POST.getlist('orders'),plan))
    except ValidationError as error:return JsonResponse({'error':'; '.join(error.messages)},status=400)


@transaction.atomic
def create_selected_plan(ids,day,key,actor):
    from django.contrib.auth import get_user_model
    from .order_import import add_selected
    try:day=parse_date(day);key=uuid.UUID(str(key));identities=sorted({int(value) for value in ids})
    except (ValueError,TypeError):raise ValidationError('Reload the order selection and choose a valid plan date.')
    if day is None:raise ValidationError('Choose a valid plan date.')
    get_user_model().objects.select_for_update().get(pk=actor.pk)
    existing=RoastPlan.all_objects.filter(creation_key=key).first()
    if existing:
        event=existing.events.filter(action='selected_create').first()
        if existing.created_by_id!=actor.pk or existing.date!=day or not event or event.details.get('orders')!=identities:raise ValidationError('This selection was already used for a different plan. Reload before continuing.')
        return existing
    selected_orders(identities)
    plan=RoastPlan.objects.create(date=day,created_by=actor,creation_key=key)
    add_selected(plan,identities,actor)
    PlanEvent.objects.create(plan=plan,actor=actor,action='selected_create',details={'orders':identities})
    return plan


@staff_member_required
@require_POST
def save_drafts(request,pk):
    try:
        with transaction.atomic():
            plan=get_object_or_404(RoastPlan.objects.select_for_update(),pk=pk)
            if request.POST.get('version')!=str(plan.version):raise ValidationError('The plan changed. Reload before saving these loads.')
            try:changes=json.loads(request.POST.get('changes','[]'))
            except (ValueError,TypeError):raise ValidationError('Choose valid draft loads.')
            if not isinstance(changes,list) or not 1<=len(changes)<=1000:raise ValidationError('Change between 1 and 1,000 draft loads.')
            seen=set();updates=[]
            for change in changes:
                try:row_id=int(change['id']);machine_id=int(change['roaster']);weight=Decimal(str(change['green_oz']))
                except (KeyError,ValueError,TypeError,ArithmeticError):raise ValidationError('Enter positive weights to one decimal place.')
                if row_id in seen:raise ValidationError('A draft load appears twice.')
                seen.add(row_id)
                row=get_object_or_404(PlannedBatch.objects.select_for_update(),pk=row_id,group__plan=plan,batch__isnull=True)
                machine=get_object_or_404(Roaster,pk=machine_id,active=True)
                if not weight.is_finite() or weight!=weight.quantize(Decimal('.1')):raise ValidationError('Use tenths of an ounce for draft loads.')
                before={'roaster':row.roaster_id,'green_oz':str(row.green_oz)}
                row.roaster=machine;row.green_oz=weight;row.full_clean();updates.append((row,before))
            for row,before in updates:
                if before=={'roaster':row.roaster_id,'green_oz':str(row.green_oz)}:continue
                row.save();RoastGroup.objects.filter(pk=row.group_id).update(auto_batches=False)
            from .plan_actions import mark_revised
            mark_revised(plan,request.user);plan.version+=1;plan.save(update_fields=['version'])
            PlanEvent.objects.create(plan=plan,actor=request.user,action='drafts_saved',details={'changes':[{'row':row.pk,'before':before,'after':{'roaster':row.roaster_id,'green_oz':str(row.green_oz)}} for row,before in updates]})
        messages.success(request,'Batch changes saved together. Review coverage, then accept the updated plan.')
    except ValidationError as error:messages.error(request,'; '.join(error.messages))
    return redirect('/planning/?plan='+str(pk)+'#roast-plan')
