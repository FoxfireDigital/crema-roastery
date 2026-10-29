"""Opt-in estimates for a coffee/roast/temperature, machine and green-load band."""
from decimal import Decimal,ROUND_CEILING
import hashlib,json
from django.utils import timezone
from .models import Batch,HistoricalRoast

def band(roaster,green):
    capacity=roaster.capacity
    if not capacity or not 0<green<=capacity:return None
    middle=capacity/2
    return {'key':'small' if green<=middle else 'large','lower':Decimal(0) if green<=middle else middle,'upper':middle if green<=middle else capacity}

def row_loss(row,default):
    cohort=band(row.roaster,row.green_oz)
    basis=row.yield_basis
    if row.estimated_loss_pct is not None and cohort and basis.get('roaster')==row.roaster_id and basis.get('band')==cohort['key']:
        return row.estimated_loss_pct
    return Decimal(default)

def suggestion(group,roaster=None,green_oz=None,current_loss=None):
    if group.coffee.experimental:return None
    if roaster is None or green_oz is None:
        contexts=list(group.planned_batches.select_related('roaster'))
        if not contexts:return None
        keys={(row.roaster_id,(band(row.roaster,row.green_oz) or {}).get('key')) for row in contexts}
        if len(keys)!=1:return None
        roaster=contexts[0].roaster;green_oz=contexts[0].green_oz
    cohort=band(roaster,Decimal(green_oz))
    if not cohort:return None
    samples=[];live_dates=set()
    recent=Batch.objects.filter(coffee=group.coffee,roast_level=group.roast_level,roaster=roaster,date__lte=timezone.localdate(),roasted_at__isnull=False,roasted_oz__isnull=False,merged_into__isnull=True,green_oz__gt=cohort['lower'],green_oz__lte=cohort['upper']).select_related('planned_group','order').order_by('-date','-pk')[:200]
    for batch in recent:
        requested=batch.planned_group.target_finish_temp_f if batch.planned_group_id else batch.order.target_finish_temp_f if batch.order_id else None
        if requested!=group.target_finish_temp_f:continue
        live_dates.add(batch.date)
        if batch.date and Decimal(0)<batch.green_oz and batch.green_oz/2<batch.roasted_oz<=batch.green_oz:
            samples.append({'id':'batch:'+str(batch.pk),'date':batch.date,'green':batch.green_oz,'finished':batch.roasted_oz})
    if group.target_finish_temp_f is None:
        rows=HistoricalRoast.objects.filter(coffee=group.coffee,roast_level=group.roast_level,roaster_name__iexact=roaster.name,date__isnull=False,date__lte=timezone.localdate(),green_oz__gt=cohort['lower'],green_oz__lte=cohort['upper'],roasted_oz__gt=0).order_by('-date','-pk')[:300]
        for row in rows:
            if row.date in live_dates or any(not str(flag).endswith('carried forward from preceding row') for flag in row.flags):continue
            if row.green_oz/2<row.roasted_oz<=row.green_oz:samples.append({'id':'workbook:'+str(row.pk),'date':row.date,'green':row.green_oz,'finished':row.roasted_oz})
    samples=sorted(samples,key=lambda row:(row['date'],row['id']),reverse=True)[:20]
    if len(samples)<3:return None
    loss=((1-sum(row['finished'] for row in samples)/sum(row['green'] for row in samples))*100).quantize(Decimal('.1'))
    if not 0<=loss<50:return None
    fingerprint=hashlib.sha256(json.dumps([group.pk,str(group.target_finish_temp_f),roaster.pk,cohort['key'],str(green_oz),str(current_loss),samples],default=str,sort_keys=True).encode()).hexdigest()
    default=Decimal(current_loss) if current_loss is not None else group.loss_override if group.loss_override is not None else group.plan.estimated_loss_pct
    expected=Decimal(green_oz)*(1-default/100)
    recommended=(expected/(1-loss/100)).quantize(Decimal('.1'),rounding=ROUND_CEILING)
    return {'loss':loss,'samples':len(samples),'from':min(row['date'] for row in samples),'to':max(row['date'] for row in samples),'roaster':roaster.pk,'machine':roaster.name,
            'band':cohort['key'],'lower':cohort['lower'],'upper':cohort['upper'],'revision':fingerprint,'records':[row['id'] for row in samples],
            'recommended_green':recommended,'fits':recommended<=roaster.capacity,'same_band':(band(roaster,recommended) or {}).get('key')==cohort['key']}
