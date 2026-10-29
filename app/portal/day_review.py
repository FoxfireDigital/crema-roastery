"""Read-only close-of-day checks and customer packing summaries."""
from collections import defaultdict
from decimal import Decimal,InvalidOperation
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from .models import RoastPlan,IncomingOrderLine,PlannedBatch,PackingProgress,ImportOrder


def review_day(day):
    from .roasted_stock import credit
    from .label_sheets import order_labels
    from .packing import applicable_steps
    from .finished_coverage import plan_coverage
    plans=list(RoastPlan.objects.filter(date=day).order_by('pk'))
    groups={};issues=[];orders={};total=Decimal(0);missing=0;unstarted=0;coverages=[]
    for plan in plans:
        finished=plan_coverage(plan);coverages.append(finished)
        finished_groups={item['group_id']:item for item in finished['rows']}
        label_issues={row['key'].split('-')[0]:row['issue'] for row in order_labels(plan) if row['issue']}
        lines=list(IncomingOrderLine.objects.filter(group__plan=plan).select_related('group__coffee','product_coffee','product_label'))
        progress={p.line_id:p for p in PackingProgress.objects.filter(line__in=lines)}
        imported={o.external_id:o for o in ImportOrder.objects.filter(imported_plan=plan)}
        for group in plan.groups.select_related('coffee'):
            group_lines=[l for l in lines if l.group_id==group.pk]
            if not group_lines:continue
            ordered=sum((l.finished_oz for l in group_lines),Decimal(0));output=Decimal(0);missing_group=0
            for row in PlannedBatch.objects.filter(group=group).select_related('batch'):
                if not row.batch_id:unstarted+=1;continue
                if row.batch.roasted_oz is None:missing_group+=1
                else:output+=row.batch.roasted_oz
            coverage=finished_groups[group.pk]
            output=coverage['new_roasted'];missing_group=coverage['missing_weights']
            stock=coverage['bulk_used'];short=coverage['remaining_to_record'];missing+=missing_group;total+=output
            groups[group.pk]={'coffee':group.coffee.name,'roast':group.roast_level,'ordered':ordered,'output':output,'stock':stock,'short':short,'plan':plan,'missing':missing_group}
            if short:
                pending=coverage['bulk_reserved']
                issues.append({'text':f'{group.coffee.name}: {short:.1f} oz not yet recorded as roast results or bulk used.'+(f' {pending:.1f} oz bulk is reserved but not yet used.' if pending else ''),'url':f'/stock/?plan={plan.pk}' if pending and not coverage['uncovered'] else f'/planning/?plan={plan.pk}#roast-plan','button':'Confirm bulk usage' if pending and not coverage['uncovered'] else 'Review coffee total'})
            if missing_group:issues.append({'text':f'{group.coffee.name}: {missing_group} started batch(es) need finished weights.','url':f'/?plan={plan.pk}','button':'Record results'})
        for line in lines:
            p=progress.get(line.pk);source=imported.get(line.external_id.split(':')[0]) if line.source in ['shopify','store'] else None
            identity=('wholesale',line.wholesale_order_id) if line.wholesale_order_id else ('shopify',source.pk) if source else ('manual',line.customer,line.reference)
            key=(plan.pk,identity);order=orders.setdefault(key,{'customer':line.customer or 'Customer not recorded','reference':line.reference or 'Stock / unnumbered','plan':plan,'lines':[],'reasons':set(),'ready':False})
            reasons=order['reasons'];packages=[];accounted=Decimal(0)
            for pack in line.packaging:
                try:
                    size=Decimal(str(pack['size_oz']));count=Decimal(str(pack['bags']))
                    if not size.is_finite() or size<=0 or not count.is_finite() or count<=0 or count!=count.to_integral_value():raise ValueError()
                    accounted+=size*count;packages.append(f'{int(count)} × {size:g} oz')
                except (KeyError,ValueError,InvalidOperation,TypeError):continue
            if not packages or accounted!=line.finished_oz:reasons.add('Confirm bag sizes / counts')
            if line.grind not in ('whole','regular','fine','coarse'):reasons.add('Confirm grind')
            if not p or any(not getattr(p,field) for field,label in applicable_steps(line)):reasons.add('Bagging / labeling / sealing unfinished')
            if groups[line.group_id]['short']:reasons.add('Recorded coffee does not yet cover demand')
            if not plan.accepted_at:reasons.add('Plan needs acceptance / review')
            if source and (source.source_flags or source.source_changed or source.cancelled or source.financial_status!='paid' or source.fulfillment_status!='unfulfilled'):reasons.add('Source order changed or needs status review')
            label_issue=label_issues.get(str(line.pk)) if not p or not p.labeled_at else ''
            if label_issue:reasons.add('Label artwork / packaging needs attention')
            order['lines'].append({'coffee':line.ordered_coffee.name,'label':line.ordered_label.name if line.ordered_label else 'Standard label','packaging':', '.join(packages) or 'Unconfirmed packaging','grind':line.get_grind_display(),'finished':line.finished_oz})
    values=list(orders.values())
    for order in values:order['ready']=not order['reasons'];order['reasons']=sorted(order['reasons'])
    values.sort(key=lambda o:(o['ready'],o['customer'].casefold(),o['reference']))
    return {'day':day,'plans':plans,'coverages':coverages,'groups':list(groups.values()),'orders':values,'issues':issues,'missing_weights':missing,'unstarted':unstarted,'output':total,'ready':sum(o['ready'] for o in values),'unfinished':sum(not o['ready'] for o in values)}


@staff_member_required
def finish_day(request):
    try:day=parse_date(request.GET.get('date','')) if request.GET.get('date') else timezone.localdate()
    except ValueError:day=None
    if day is None:day=timezone.localdate()
    return render(request,'portal/day_review.html',review_day(day))
