"""Pool unstarted automatic roast demand while retaining each packing label.

Call inside the same locked-plan transaction as automatic batch synchronization.
No physical batches, manual sizing, used stock or historical plans are rewritten.
"""
from collections import defaultdict
from django.utils import timezone
from .models import RoastGroup,PlanEvent


def consolidate_labels(plan,actor=None,group_ids=None):
    if plan.removed_at or plan.closed_at or plan.historical:return False
    from .planning import profile_key
    from .roasted_stock import used_for
    profiles=defaultdict(list)
    eligible=plan.groups.filter(legacy_order__isnull=True)
    if group_ids is not None:eligible=eligible.filter(pk__in=group_ids)
    for group in eligible.order_by('pk'):
        if group.orders.exists():
            profiles[(group.coffee_id,group.roast_level,group.target_finish_temp_f,group.loss_override)].append(group)
    changed=False
    for groups in profiles.values():
        if any(not g.auto_batches or g.planned_batches.filter(batch__isnull=False).exists() or used_for(g) for g in groups):continue
        first=groups[0]
        key=profile_key(first.coffee_id,first.roast_level,first.target_finish_temp_f,None)
        occupied=RoastGroup.objects.filter(plan=plan,key=key).first()
        if occupied and occupied.pk not in {g.pk for g in groups}:continue
        target=occupied or first
        if len(groups)==1 and target.key==key and target.label_variant_id is None:continue
        before=[{'group':g.pk,'label':g.label_variant_id,'rows':list(g.planned_batches.values_list('pk',flat=True))} for g in groups]
        moved=[]
        for group in groups:
            for line in group.orders.select_related('product_coffee','product_label','group__coffee','group__label_variant'):
                # Old rows can inherit their product/label from the group.
                # Freeze those identities before changing that relationship.
                coffee_id=line.ordered_coffee.pk
                label=line.ordered_label
                line.product_coffee_id=coffee_id;line.product_label=label
                line.group=target
                line.save(update_fields=['product_coffee','product_label','group'])
                moved.append(line.pk)
            if group.pk!=target.pk:
                group.planned_batches.filter(batch__isnull=True).update(removed_at=timezone.now())
        target.label_variant=None;target.key=key
        target.save(update_fields=['label_variant','key'])
        from .plan_actions import mark_revised
        mark_revised(plan,actor or plan.created_by)
        PlanEvent.objects.create(plan=plan,actor=actor or plan.created_by,action='label_groups_pooled',details={'before':before,'target':target.pk,'lines':moved,'reason':'Identical roast requirements share loads; packaging labels remain on each order.'})
        changed=True
    return changed
