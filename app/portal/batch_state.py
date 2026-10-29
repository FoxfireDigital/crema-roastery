"""A saved placeholder is not evidence that physical production has begun."""
def committed(batch):
    return bool(batch and not batch.removed_at and (batch.measured_at or batch.roasted_at or batch.roasted_oz is not None or batch.bagged_at or batch.sealed_at))

def group_started(group):
    return any(committed(row.batch) for row in group.planned_batches.select_related('batch') if row.batch_id)
