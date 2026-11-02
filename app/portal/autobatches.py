"""Default drafts follow demand until the operator takes over their sizing.

Call with the roast plan locked inside a transaction. Reads never create drafts.
"""
from .models import Roaster,PlannedBatch
from django.utils import timezone
from decimal import Decimal


def sync_group(group,plan,actor=None):
    if not group.auto_batches:return False
    from .batch_state import committed
    from .roasted_stock import used_for
    rows=list(group.planned_batches.select_related('batch'))
    # Actual yield updates and edits elsewhere must never add surprise loads
    # once this physical profile has begun. Replanning stays an explicit action.
    if used_for(group) or any(committed(row.batch) for row in rows if row.batch_id):return False
    from .planning import summary,split_weights
    needed=summary(group,plan.estimated_loss_pct,spillage=plan.spillage_pct)['green_needed']
    machines=sorted([r for r in Roaster.objects.filter(active=True) if r.capacity and r.capacity>=Decimal('.1')],key=lambda r:(r.capacity,r.pk))
    if needed and not machines:return False
    roaster=next((r for r in machines if r.capacity>=needed),machines[-1]) if machines else None
    weights=split_weights(needed,roaster.capacity) if needed else []
    drafts=group.planned_batches.filter(pk__in=[row.pk for row in rows])
    desired=[(roaster.pk,weight) for weight in weights]
    if list(drafts.values_list('roaster_id','green_oz'))==desired:return False
    placeholders=[{'row':row.pk,'batch':row.batch_id} for row in rows if row.batch_id]
    removed_at=timezone.now();drafts.update(removed_at=removed_at)
    for row in rows:
        if not row.batch_id:continue
        # A cleared placeholder must also leave active-batch/history totals;
        # retain its original values under Deleted batches, with an audit reason.
        row.batch.removed_at=removed_at;row.batch.removed_by=actor or plan.created_by
        row.batch.removal_reason='Unstarted placeholder replaced after stock / demand recalculation; no physical measurement, result or completion remained.'
        row.batch.save(update_fields=['removed_at','removed_by','removal_reason'])
    if placeholders:
        from .models import PlanEvent
        PlanEvent.objects.create(plan=plan,actor=actor or plan.created_by,action='unstarted_replaced',details={'group':group.pk,'placeholders':placeholders,'reason':'No measurements, results or status remained; preserve the original record and replace only its unstarted plan row.'})
    for weight in weights:PlannedBatch.objects.create(group=group,roaster=roaster,green_oz=weight)
    return True


def sync_plan(plan,actor=None):
    if plan.removed_at is not None or plan.closed_at is not None:return False
    from .roast_pooling import consolidate_labels
    changed=consolidate_labels(plan,actor)
    from .flavoring import route_flavors
    changed=route_flavors(plan) or changed
    from .roasted_stock import sync_plan as reserve_stock
    changed=reserve_stock(plan,actor) or changed
    for group in plan.groups.filter(auto_batches=True):changed=sync_group(group,plan,actor) or changed
    return changed
