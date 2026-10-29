"""Keep sold flavors separate from the coffee that physically goes in the roaster."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from django.db import transaction
from .models import RoastGroup,IncomingOrderLine,PlannedBatch


def production_profile(plan,data,legacy=None):
    coffee=data['coffee'];label=data.get('label_variant')
    if coffee.kind!='flavored' or not coffee.roast_base_id:return coffee,label
    existing=RoastGroup.objects.filter(plan=plan,roast_level='Medium',target_finish_temp_f__isnull=True,label_variant__isnull=True,legacy_order__isnull=True,coffee__active=True).exclude(coffee__kind='flavored').filter(coffee__flavor_base_allowed=True)
    # Prefer a real Medium order, not a leftover draft or another flavor's routing.
    choices=[]
    for group in existing.select_related('coffee'):
        if group.coffee.flavor_base_eligible and group.orders.filter(Q(product_coffee__kind__in=['single_origin','blend'])|Q(product_coffee__isnull=True)).exists():choices.append(group)
    from .instance import default_base
    preferred=default_base()
    choices.sort(key=lambda group:(group.coffee_id!=getattr(preferred,'pk',None),group.pk))
    if choices:return choices[0].coffee,None
    base=coffee.roast_base
    if not base.flavor_base_eligible or base.standard_roast!='Medium':
        from .models import Coffee
        base=default_base()
        if not base or not base.flavor_base_eligible:raise ValidationError('Choose a suitable Medium flavor base. Excluded coffees cannot be used for flavors.')
    return base,None


def route_flavors(plan):
    """Reroute only unstarted allocations; callers hold the plan lock."""
    from .planning import group_for
    changed=False
    lines=IncomingOrderLine.objects.filter(group__plan=plan,product_coffee__kind='flavored',product_coffee__roast_base__isnull=False).select_related('group','product_coffee','product_label')
    for line in lines:
        if line.group.planned_batches.filter(batch__isnull=False).exists():continue
        target=group_for(plan,{'coffee':line.product_coffee,'label_variant':line.product_label,'roast_level':'Medium','target_finish_temp_f':None},line.group.legacy_order)
        if target.pk==line.group_id:continue
        old=line.group;line.group=target;line.save(update_fields=['group']);changed=True
        if not old.orders.exists():old.planned_batches.filter(batch__isnull=True).update(removed_at=timezone.now())
    return changed



def manual_packaging(data):
    result=[]
    for key,size in [('bags_1lb','16'),('bags_5lb','80')]:
        if data.get(key):result.append({'size_oz':size,'bags':data[key]})
    return result


def import_packaging(line):
    # A multi-pound subscription allocation describes demand, not necessarily
    # a single large bag. Leave those pack counts unconfirmed until selected.
    size=Decimal(str(line.get('size_oz') or 0));bags=int(line.get('quantity') or 0)
    if line.get('frac_bag') and size==Decimal('2.5') and bags>0:return [{'size_oz':'2.5','bags':bags,'per_sheet':8}]
    if line.get('cycle_choice') and size not in [Decimal(12),Decimal(16),Decimal(80)]:return []
    return [{'size_oz':str(size),'bags':bags}] if size>0 and bags>0 else []


def measured_snapshot(batch):
    return {'batch':batch.pk,'coffee':batch.coffee.name,'coffee_id':batch.coffee_id,'green_oz':str(batch.green_oz),'group_id':batch.planned_group_id,'measured_at':batch.measured_at.isoformat() if batch.measured_at else None}


@transaction.atomic
def consolidate_existing_flavors(plan_id,actor):
    """Upgrade old, unroasted flavored work without deleting its measured records."""
    from .models import RoastPlan,Batch,BatchMergeEvent,PlanEvent
    from .planning import group_for
    from .plan_actions import mark_revised
    plan=RoastPlan.objects.select_for_update().get(pk=plan_id);changed=False;combined=[];targets=set()
    def inputs():
        result={}
        for row in PlannedBatch.objects.filter(group__plan=plan).select_related('group'):
            key=(row.roaster_id,row.group.roast_level,str(row.group.target_finish_temp_f));result[key]=result.get(key,Decimal(0))+row.green_oz
        return result
    before_inputs=inputs()
    groups=list(plan.groups.filter(coffee__kind='flavored',coffee__roast_base__isnull=False).select_related('coffee','label_variant'))
    for source in groups:
        if source.legacy_order_id:continue # Existing legacy custom orders retain their original workflow.
        lines=list(source.orders.select_related('product_coffee','product_label'))
        if not lines:continue
        source_rows=list(source.planned_batches.select_related('batch','roaster'))
        if any(row.batch_id and (row.batch.roasted_at or row.batch.roasted_oz is not None or row.batch.bagged_at or row.batch.sealed_at) for row in source_rows):continue
        target=group_for(plan,{'coffee':source.coffee,'label_variant':source.label_variant,'roast_level':'Medium','target_finish_temp_f':None},source.legacy_order)
        if target.pk==source.pk:continue
        targets.add(target.pk)
        for row in source_rows:
            if not row.batch_id:
                row.group=target;row.save(update_fields=['group']);continue
            batch=Batch.objects.select_for_update().get(pk=row.batch_id)
            if batch.merged_into_id:continue
            candidates=list(target.planned_batches.filter(roaster=row.roaster,batch__isnull=False,batch__roasted_at__isnull=True,batch__roasted_oz__isnull=True,batch__bagged_at__isnull=True,batch__sealed_at__isnull=True,batch__merged_into__isnull=True).select_related('batch'))
            partner=next((candidate for candidate in candidates if candidate.batch.measured_at and batch.measured_at and candidate.green_oz+row.green_oz<=row.roaster.capacity),None)
            before={'source':measured_snapshot(batch)}
            if partner:
                physical=Batch.objects.select_for_update().get(pk=partner.batch_id);before['target']=measured_snapshot(physical)
                physical.green_oz+=batch.green_oz;physical.save(update_fields=['green_oz'])
                partner.green_oz+=row.green_oz;partner.save(update_fields=['green_oz'])
                batch.merged_into=physical;batch.save(update_fields=['merged_into'])
                row.removed_at=timezone.now();row.save(update_fields=['removed_at'])
                note='Combined measured Medium inputs for flavored and unflavored demand. No roasted result was changed.'
            else:
                physical=batch
                batch.coffee=target.coffee;batch.label_variant=target.label_variant;batch.planned_group=target
                batch.save(update_fields=['coffee','label_variant','planned_group'])
                row.group=target;row.save(update_fields=['group'])
                note='Corrected the base coffee on an unroasted measured input; original product retained on its order.'
            BatchMergeEvent.objects.create(source=batch,target=physical,actor=actor,before=before,after={'target':measured_snapshot(physical),'source_merged_into':batch.merged_into_id},note=note)
            combined.append({'source_batch':batch.pk,'target_batch':physical.pk,'green_oz':str(physical.green_oz)})
        for line in lines:
            line.group=target;line.save(update_fields=['group'])
        changed=True
    if changed:
        from .autobatches import sync_group
        for target in RoastGroup.objects.filter(pk__in=targets):sync_group(target,plan)
        # The owner explicitly approved pooling the same Medium inputs. Keep
        # acceptance when machine loads, roast levels and temperatures total the
        # same; changed sizing or machine assignments still require review.
        if before_inputs!=inputs():mark_revised(plan,actor)
        plan.version+=1;plan.save(update_fields=['version'])
        PlanEvent.objects.create(plan=plan,actor=actor,action='flavor_base_fix')
    return {'plan':plan.pk,'changed':changed,'combined':combined}
