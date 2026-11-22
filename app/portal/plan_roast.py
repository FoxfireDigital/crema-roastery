"""Change one order's production roast without editing its source order."""
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import IncomingOrderLine, PackingProgress, PlanEvent, PlannedBatch, ROAST_LEVELS, RoastedStockAllocation


def eligible(line):
    coffee = line.ordered_coffee
    return (
        coffee.active and not coffee.experimental and coffee.kind == 'single_origin'
        and not line.group.legacy_order_id
    )


def blocked_groups(group_ids):
    batches = PlannedBatch.objects.filter(group_id__in=group_ids, batch__isnull=False)
    stock = RoastedStockAllocation.objects.filter(line__group_id__in=group_ids, status='used')
    return set(batches.values_list('group_id', flat=True)) | set(stock.values_list('line__group_id', flat=True))


def started_packing(lines):
    progress = PackingProgress.objects.filter(line_id__in=lines).filter(
        Q(flavored_at__isnull=False) | Q(ground_at__isnull=False) | Q(bagged_at__isnull=False)
        | Q(labeled_at__isnull=False) | Q(sealed_at__isnull=False)
    )
    return set(progress.values_list('line_id', flat=True))


def change_roast(plan, line_id, roast, actor):
    """Call with the current, open plan locked in a transaction."""
    from .planning import group_for

    if roast not in dict(ROAST_LEVELS):
        raise ValidationError('Choose a valid roast level.')
    line = IncomingOrderLine.objects.select_for_update(of=('self',)).select_related(
        'group__coffee', 'group__label_variant', 'product_coffee', 'product_label',
    ).filter(pk=line_id, group__plan=plan).first()
    if line is None:
        raise ValidationError('This order line is no longer on the plan.')
    if not eligible(line):
        raise ValidationError('Choose an active single-origin order line to change its roast.')
    original = line.group
    if roast == original.roast_level:
        return False
    if blocked_groups([original.pk]) or started_packing([line.pk]):
        raise ValidationError('This roast has batch, bulk stock or packing progress. Review the recorded work before changing its roast.')

    coffee, label = line.ordered_coffee, line.ordered_label
    target = group_for(plan, {
        'coffee': coffee, 'label_variant': label, 'roast_level': roast,
        'target_finish_temp_f': original.target_finish_temp_f,
    })
    if blocked_groups([target.pk]):
        raise ValidationError('The requested roast already has batch or bulk stock progress on this plan.')
    line.product_coffee = coffee
    line.product_label = label
    line.group = target
    line.save(update_fields=['product_coffee', 'product_label', 'group'])

    # Manual sizing is preserved for remaining orders. An empty profile has
    # no work to roast, so archive its drafts and use defaults if reused.
    if not original.orders.exists():
        original.planned_batches.filter(batch__isnull=True).update(removed_at=timezone.now())
        if not original.auto_batches:
            original.auto_batches = True
            original.save(update_fields=['auto_batches'])
    PlanEvent.objects.create(plan=plan, actor=actor, action='order_roast_changed', details={
        'line': line.pk, 'reference': line.reference,
        'before': {'group': original.pk, 'roast': original.roast_level},
        'after': {'group': target.pk, 'roast': target.roast_level},
    })
    return True
