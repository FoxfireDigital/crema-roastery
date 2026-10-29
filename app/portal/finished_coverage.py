"""Read-only finished-coffee totals. A reservation is never recorded output."""
from decimal import Decimal
from django.utils import timezone
from .models import IncomingOrderLine,PlannedBatch,RoastedStockAllocation

ZERO=Decimal(0)
NUMBERS=('ordered','new_roasted','bulk_used','bulk_reserved','recorded_total','remaining_to_record','uncovered')

def empty_totals():return {key:ZERO for key in NUMBERS}

def plan_coverage(plan):
    if plan is None:return {'plan_id':None,'rows':[],'totals':empty_totals(),'as_of':timezone.now().isoformat()}
    groups=list(plan.groups.select_related('coffee').order_by('coffee__name','roast_level','pk'))
    rows={g.pk:{'group_id':g.pk,'coffee':g.coffee.name,'roast':g.roast_level,'sources':[],'missing_weights':0,**empty_totals()} for g in groups}
    for line in IncomingOrderLine.objects.filter(group__plan=plan):rows[line.group_id]['ordered']+=line.finished_oz
    actual=PlannedBatch.objects.filter(group__plan=plan,batch__isnull=False,batch__removed_at__isnull=True,batch__merged_into__isnull=True).select_related('batch')
    for row in actual:
        item=rows[row.group_id]
        if row.batch.roasted_oz is not None:item['new_roasted']+=row.batch.roasted_oz
        elif row.batch.measured_at or row.batch.roasted_at:item['missing_weights']+=1
    allocations=RoastedStockAllocation.objects.filter(line__group__plan=plan,line__removed_at__isnull=True,status__in=['reserved','used']).select_related('stock__coffee','line')
    for allocation in allocations:
        item=rows[allocation.line.group_id];key='bulk_used' if allocation.status=='used' else 'bulk_reserved'
        item[key]+=allocation.amount_oz
        item['sources'].append({'coffee':allocation.stock.coffee.name,'amount':allocation.amount_oz,'state':allocation.status,'line_id':allocation.line_id,'reference':allocation.line.reference,'needs_recount':allocation.stock.needs_recount})
    totals=empty_totals();result=[];sources={}
    for item in rows.values():
        item['recorded_total']=item['new_roasted']+item['bulk_used']
        item['remaining_to_record']=max(ZERO,item['ordered']-item['recorded_total'])
        item['uncovered']=max(ZERO,item['ordered']-item['recorded_total']-item['bulk_reserved'])
        if not any(item[key] for key in NUMBERS) and not item['missing_weights']:continue
        for key in NUMBERS:totals[key]+=item[key]
        for source in item['sources']:
            key=(source['coffee'],source['state']);sources[key]=sources.get(key,ZERO)+source['amount']
        result.append(item)
    return {'plan_id':plan.pk,'rows':result,'totals':totals,'bulk_sources':[{'coffee':key[0],'state':key[1],'amount':amount} for key,amount in sorted(sources.items())],'as_of':timezone.now().isoformat()}

def snapshot_coverage(snapshot,plan_id=None):
    """Old closures keep their exact saved data; never substitute today's data."""
    if isinstance(snapshot.get('finished_coverage'),dict):return snapshot['finished_coverage']
    def number(value):return Decimal(str(value)) if value is not None else ZERO
    totals=empty_totals()
    totals['ordered']=sum((number(line.get('finished_oz')) for line in snapshot.get('orders',[])),ZERO)
    totals['new_roasted']=sum((number(batch.get('roasted_oz')) for batch in snapshot.get('batches',[]) if not batch.get('merged_into')),ZERO)
    totals['bulk_used']=sum((number(entry.get('amount_oz')) for entry in snapshot.get('stock',[])),ZERO)
    totals['recorded_total']=totals['new_roasted']+totals['bulk_used']
    # Legacy snapshots lack the physical group mapping needed to distribute
    # roasts to finished flavors. Do not invent per-coffee or deficit figures.
    totals['remaining_to_record']=None;totals['uncovered']=None
    return {'plan_id':plan_id,'rows':[],'totals':totals,'legacy_snapshot':True,'as_of':''}
