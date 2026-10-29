"""Read-only green forecasts from physical green weights, never sales guesses."""
from collections import defaultdict
from datetime import datetime,time,timedelta
from decimal import Decimal,ROUND_CEILING
import csv
from django import forms
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET
from .models import Batch,PlannedBatch,GreenBeanItem,GreenRecipe,GreenBatchUsage,GreenMovement
from .batch_state import committed
from .green_stock import split

ZERO=Decimal(0)
TENTH=Decimal('.1')


class ForecastForm(forms.Form):
    window=forms.TypedChoiceField(coerce=int,choices=[(21,'Last 21 complete days'),(28,'Last 28 complete days'),(56,'Last 56 complete days')],initial=28,label='Recent-use window')
    horizon=forms.IntegerField(min_value=1,max_value=90,initial=14,label='Planning horizon (days)',widget=forms.NumberInput(attrs={'min':1,'max':90}))


def recipe_maps(items):
    """One query; invalid/inactive recipes remain visible as coverage gaps."""
    result={};active={str(item.pk) for item in items}
    for recipe in GreenRecipe.objects.all():
        try:
            parts={str(c['item']):Decimal(str(c['percent'])) for c in recipe.components}
            if not 1<=len(parts)<=12 or len(parts)!=len(recipe.components) or not set(parts)<=active:continue
            if any(not value.is_finite() or not 0<value<=100 for value in parts.values()) or sum(parts.values())!=100:continue
            result[recipe.coffee_id]=parts
        except (KeyError,TypeError,ValueError,ArithmeticError):continue
    return result


def current_parts(coffee,direct_id,maps,active):
    if direct_id:return {str(direct_id):Decimal(100)} if str(direct_id) in active else {}
    if coffee.experimental:return {}  # A catch-all name does not identify a bean.
    key=coffee.roast_base_id if coffee.kind=='flavored' else coffee.pk
    return maps.get(key,{})


def accepted_loads(items=None,maps=None):
    """Only unmeasured, accepted, open physical loads; measured stock is already net."""
    items=list(GreenBeanItem.objects.filter(active=True)) if items is None else items
    maps=recipe_maps(items) if maps is None else maps;active={str(item.pk) for item in items}
    totals={item.pk:ZERO for item in items};rows=[];gaps=[]
    drafts=PlannedBatch.objects.filter(group__plan__accepted_at__isnull=False,group__plan__removed_at__isnull=True,group__plan__closed_at__isnull=True,group__plan__historical=False).select_related('group__coffee','group__plan','batch__coffee')
    for row in drafts:
        batch=row.batch if row.batch_id else None
        if batch and (batch.removed_at or batch.merged_into_id or committed(batch)):continue
        coffee=batch.coffee if batch else row.group.coffee
        parts=current_parts(coffee,batch.green_item_id if batch else None,maps,active)
        if not parts:
            gaps.append({'batch':batch.pk if batch else None,'row':row.pk,'plan':row.group.plan_id,'coffee':coffee.name,'oz':row.green_oz,'date':row.group.plan.date});continue
        amounts=split(row.green_oz,parts)
        for pk,value in amounts.items():totals[int(pk)]+=value
        rows.append({'batch':batch.pk if batch else None,'row':row.pk,'plan':row.group.plan_id,'date':row.group.plan.date,'coffee':coffee.name,'amounts':amounts,'oz':row.green_oz})
    return totals,rows,gaps


def forecast(window=28,horizon=14,today=None):
    assert window in (21,28,56) and 1<=horizon<=90
    today=today or timezone.localdate();since=today-timedelta(days=window);until=today+timedelta(days=horizon)
    start=timezone.make_aware(datetime.combine(since,time.min));end=timezone.make_aware(datetime.combine(today,time.min))
    items=list(GreenBeanItem.objects.filter(active=True));active={str(item.pk) for item in items};maps=recipe_maps(items)
    used={item.pk:ZERO for item in items};estimated={item.pk:ZERO for item in items};days=defaultdict(set);sources=[];gaps=[]
    batches=list(Batch.objects.filter(date__gte=since,date__lt=today,merged_into__isnull=True).select_related('coffee'))
    tracked={u.batch_id:u for u in GreenBatchUsage.objects.filter(batch_id__in=[batch.pk for batch in batches])}
    for batch in batches:
        if not committed(batch):continue
        usage=tracked.get(batch.pk);kind='Recorded green deduction'
        if usage:
            try:
                amounts={str(k):Decimal(str(v)) for k,v in usage.amounts.items()}
                if not amounts or any(not value.is_finite() or value<0 for value in amounts.values()) or sum(amounts.values())!=batch.green_oz.quantize(TENTH):raise ValueError()
            except (AttributeError,TypeError,ValueError,ArithmeticError):amounts={}
            # A broken frozen usage cannot silently fall back to a newer recipe.
        else:
            parts=current_parts(batch.coffee,batch.green_item_id,maps,active)
            amounts=split(batch.green_oz,parts) if parts else {}
            kind='Direct origin estimate' if batch.green_item_id else 'Current recipe estimate'
        if not amounts or not set(amounts)<=active:
            gaps.append({'batch':batch.pk,'coffee':batch.coffee.name,'oz':batch.green_oz,'date':batch.date});continue
        for pk,value in amounts.items():
            used[int(pk)]+=value;days[int(pk)].add(batch.date)
            if not usage:estimated[int(pk)]+=value
        sources.append({'batch':batch.pk,'date':batch.date,'coffee':batch.coffee.name,'kind':kind,'oz':batch.green_oz,'amounts':amounts})
    # Explicit Other green usage counts; receipts, returns and count adjustments
    # do not represent consumption. Batch movements are already counted above.
    other=GreenMovement.objects.filter(action='use',batch__isnull=True,item_id__in=[item.pk for item in items],at__gte=start,at__lt=end,delta_oz__lt=0)
    other_count=0
    for movement in other:
        used[movement.item_id]-=movement.delta_oz;days[movement.item_id].add(timezone.localdate(movement.at));other_count+=1
    pending,loads,pending_gaps=accepted_loads(items,maps)
    count_dates={}
    for movement in GreenMovement.objects.filter(item_id__in=[item.pk for item in items],action__in=['create','count'],at__lte=timezone.now()).order_by('at','pk'):
        count_dates[movement.item_id]=movement.at
    rows=[]
    for item in items:
        average=used[item.pk]/window;balance=item.remaining_oz
        known=defaultdict(lambda:ZERO)
        for load in loads:
            if str(item.pk) in load['amounts']:known[max(today,load['date'])]+=load['amounts'][str(item.pk)]
        def crossing(reserve):
            if balance<=reserve:return today
            dates=[]
            if average:
                n=int(((balance-reserve)/average).to_integral_value(rounding=ROUND_CEILING))
                if n<=3650:dates.append(today+timedelta(days=n))
            cumulative=ZERO
            for day,value in sorted(known.items()):
                cumulative+=value
                if balance-cumulative<=reserve:dates.append(day);break
            return min(dates) if dates else None
        known_horizon=sum((value for day,value in known.items() if day<=until),ZERO)
        typical=(average*horizon).quantize(TENTH,rounding=ROUND_CEILING)
        # Accepted work overlaps the usual pace: use the larger requirement,
        # rather than counting the same forthcoming demand twice.
        need=max(typical,known_horizon);topup=max(ZERO,need+item.reorder_oz-balance).quantize(TENTH,rounding=ROUND_CEILING)
        reorder=crossing(item.reorder_oz);empty=crossing(ZERO);count_at=count_dates.get(item.pk)
        count_age=(today-timezone.localdate(count_at)).days if count_at else None
        flags=[]
        if count_age is None:flags.append('Starting count needed')
        elif count_age>14:flags.append(f'Last physical count {count_age} days ago')
        if len(days[item.pk])<3:flags.append('Limited recent usage: fewer than 3 recorded-use days')
        if estimated[item.pk]:flags.append('Includes older loads estimated with direct origins / current recipes')
        if gaps or pending_gaps:flags.append('Some loads have no usable green mapping; forecast is partial')
        due=bool(reorder and reorder<=until)
        if count_age is None:status='Count needed';rank=0
        elif count_age>14:status='Recount recommended';rank=1
        elif due:status='Review reorder';rank=2
        elif not average and not known:status='No recent usage';rank=4
        else:status='No crossing in selected horizon';rank=3
        rows.append({'item':item,'used':used[item.pk],'estimated':estimated[item.pk],'average':average,'weekly_lb':average*7/16,
                     'use_days':len(days[item.pk]),'pending':pending[item.pk],'after_pending':balance-pending[item.pk],
                     'known_horizon':known_horizon,'typical':typical,'need':need,'topup_oz':topup,'topup_lb':topup/16,
                     'reorder_date':reorder,'empty_date':empty,'count_at':count_at,'count_age':count_age,'flags':flags,
                     'status':status,'rank':rank,'due':due,'provisional':bool(flags),'balance_lb':balance/16})
    rows.sort(key=lambda row:(row['rank'],row['reorder_date'] or today+timedelta(days=36500),row['item'].name.casefold()))
    earliest=Batch.objects.filter(Q(measured_at__isnull=False)|Q(roasted_at__isnull=False)|Q(roasted_oz__isnull=False)|Q(bagged_at__isnull=False)|Q(sealed_at__isnull=False),date__lt=today,merged_into__isnull=True).order_by('date').first()
    return {'rows':rows,'window':window,'horizon':horizon,'today':today,'since':since,'through':today-timedelta(days=1),'until':until,
            'history_gaps':gaps,'pending_gaps':pending_gaps,'sources':sources,'loads':loads,'other_count':other_count,
            'short_history':not earliest or earliest.date>since,'review_count':sum(row['due'] for row in rows)}


@staff_member_required
@require_GET
def green_forecast_page(request):
    form=ForecastForm(request.GET if request.GET else None,initial={'window':28,'horizon':14})
    data=None
    if not form.is_bound:data=forecast()
    elif form.is_valid():data=forecast(**form.cleaned_data)
    if data and request.GET.get('download')=='csv':
        from .recovery import csv_cell
        response=HttpResponse(content_type='text/csv; charset=utf-8');response['Content-Disposition']='attachment; filename="green-forecast-'+str(data['today'])+'.csv"';response.write('\ufeff');writer=csv.writer(response)
        writer.writerow(['Green-bean estimate — not a purchase order',str(data['today'])]);writer.writerow(['Usage window',str(data['since']),str(data['through']),'Planning horizon',data['horizon']])
        writer.writerow(['Method','Larger of accepted loads due by the horizon and average recorded daily green use × horizon; plus reorder reserve. Current balances are not changed.'])
        writer.writerow(['Unmapped recent loads',len(data['history_gaps']),'Unmapped accepted loads',len(data['pending_gaps'])])
        writer.writerow(['Origin','Recorded balance (oz)','Last count','Recent use (oz)','Average use (oz/day)','Accepted unmeasured (oz)','After all accepted (oz)','Horizon need (oz)','Top-up incl reserve (oz)','Estimated reorder point date','Estimated empty date','Review status','Cautions'])
        for row in data['rows']:
            writer.writerow([csv_cell(row['item'].name),f"{row['item'].remaining_oz:.1f}",timezone.localdate(row['count_at']) if row['count_at'] else 'Count needed',f"{row['used']:.1f}",f"{row['average']:.4f}",f"{row['pending']:.1f}",f"{row['after_pending']:.1f}",f"{row['need']:.1f}",f"{row['topup_oz']:.1f}",row['reorder_date'] or '',row['empty_date'] or '',row['status'],'; '.join(row['flags'])])
        for kind,key in [('Unmapped recent load','history_gaps'),('Unmapped accepted load','pending_gaps')]:
            for gap in data[key]:writer.writerow([kind,csv_cell(gap['coffee']),gap['date'],gap['oz'],'Batch '+str(gap['batch']) if gap['batch'] else 'Draft '+str(gap['row'])])
        response['Cache-Control']='private, no-store';return response
    response=render(request,'portal/green_forecast.html',{'form':form,'forecast':data},status=400 if form.is_bound and not data else 200)
    response['Cache-Control']='private, no-store';return response
