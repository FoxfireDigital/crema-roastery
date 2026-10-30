"""Optional availability review and explicitly approved, plan-scoped green recipes."""
from collections import defaultdict
from decimal import Decimal
import hashlib,json
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect
from django.views.decorators.http import require_POST
from .models import RoastPlan,PlanEvent,PlannedBatch,GreenBeanItem,GreenRecipe,ROAST_LEVELS

ACTIONS=['green_review','green_request','green_approve','green_decline','green_cancel']
LEVELS=[key for key,_ in ROAST_LEVELS]

def approved_event(group):
    return group.plan.events.filter(action__in=['green_approve','green_cancel'],details__group=group.pk).first()

def parts_for_group(group):
    from .green_stock import recipe_percentages
    event=approved_event(group)
    if not event or event.action=='green_cancel':return recipe_percentages(group.coffee_id)
    parts=event.details.get('parts',{})
    try:
        valid=isinstance(parts,dict) and 1<=len(parts)<=12 and all(str(int(k))==k and Decimal(v).is_finite() and 0<Decimal(v)<=100 for k,v in parts.items()) and sum(map(Decimal,parts.values()))==100
        valid=valid and GreenBeanItem.objects.filter(pk__in=parts,active=True).count()==len(parts)
    except (TypeError,ValueError,ArithmeticError):valid=False
    if not valid:raise ValidationError('An approved green substitution has an unavailable origin. Review or cancel that plan’s substitution before measuring.')
    return parts.copy()

def pending_rows(group):
    from .batch_state import committed
    return [row for row in group.planned_batches.select_related('batch') if not row.batch_id or not (row.batch.removed_at or row.batch.merged_into_id or committed(row.batch))]

def quantities(group,parts):
    from .green_stock import split
    total=defaultdict(Decimal)
    for row in pending_rows(group):
        for key,value in split(row.batch.green_oz if row.batch_id else row.green_oz,parts).items():total[key]+=value
    return dict(total)

def tags(item):
    details=getattr(item,'details',None)
    return {t.strip().casefold() for t in (details.flavor_tags if details else '').replace(';',',').split(',') if t.strip()}

def candidates(group,source,need,items,totals,parts):
    result=[];original=tags(source);source_details=getattr(source,'details',None)
    source_caffeine=source_details.caffeine if source_details else ''
    current=quantities(group,parts)
    for item in items:
        if item.pk==source.pk or item.remaining_oz<=0:continue
        details=getattr(item,'details',None)
        caffeine=details.caffeine if details else ''
        if source_caffeine and caffeine and source_caffeine!=caffeine:continue
        after=parts.copy();amount=Decimal(after.pop(str(source.pk)));after[str(item.pk)]=str(Decimal(after.get(str(item.pk),'0'))+amount)
        proposed=quantities(group,after)
        required=totals.get(str(item.pk),Decimal(0))-current.get(str(item.pk),Decimal(0))+proposed.get(str(item.pk),Decimal(0))
        if item.remaining_oz<required:continue
        levels=[level for level in (details.roast_levels if details and isinstance(details.roast_levels,list) else []) if level in LEVELS]
        distance=min((abs(LEVELS.index(group.roast_level)-LEVELS.index(level)) for level in levels),default=100)
        shared=original&tags(item);union=original|tags(item)
        similarity=Decimal(len(shared))/Decimal(len(union)) if original and tags(item) else Decimal(-1)
        note=('Matches '+group.roast_level) if distance==0 else 'Nearby roast needs review' if levels else 'Roast suitability not recorded'
        result.append({'item':item,'required':required,'parts':after,'roast_note':note,'shared':', '.join(sorted(shared)),'flavor_known':bool(original and tags(item)),'caffeine_known':bool(source_caffeine and caffeine),'rank':(not bool(levels),distance,-similarity,item.name.casefold(),item.pk)})
    return sorted(result,key=lambda row:row['rank'])

def review_context(plan):
    items=list(GreenBeanItem.objects.filter(active=True).select_related('details').order_by('pk'))
    by_id={str(item.pk):item for item in items};totals=defaultdict(Decimal);groups=[];gaps=[]
    for group in plan.groups.select_related('coffee'):
        if not group.orders.exists() or not pending_rows(group):continue
        try:parts=parts_for_group(group)
        except ValidationError:parts={}
        if not parts:gaps.append(group.coffee.name)
        amounts=quantities(group,parts) if parts else {}
        for key,amount in amounts.items():totals[key]+=amount
        groups.append({'group':group,'parts':parts,'amounts':amounts,'approved':approved_event(group)})
    for row in groups:
        row['shortages']=[]
        for key,need in row['amounts'].items():
            item=by_id.get(key)
            if item and totals[key]>item.remaining_oz:
                row['shortages'].append({'source':item,'needed':need,'plan_needed':totals[key],'candidates':candidates(row['group'],item,need,items,totals,row['parts'])})
    last=plan.events.filter(action__in=ACTIONS).first()
    state_event=plan.events.filter(action='green_review').first()
    facts={'plan':plan.pk,'version':plan.version,'items':[(i.pk,str(i.remaining_oz),i.version,getattr(getattr(i,'details',None),'version',0)) for i in items],
           'recipes':list(GreenRecipe.objects.filter(coffee_id__in=[g['group'].coffee_id for g in groups]).order_by('coffee_id').values('coffee_id','version','components')),
           'loads':[(r.pk,str(r.batch.green_oz if r.batch_id else r.green_oz),r.batch_id) for g in groups for r in pending_rows(g['group'])],
           'approvals':[(g['group'].pk,g['approved'].pk if g['approved'] else None,g['parts']) for g in groups]}
    signature=hashlib.sha256(json.dumps(facts,sort_keys=True,default=str).encode()).hexdigest()
    token=hashlib.sha256((signature+':'+str(last.pk if last else 0)).encode()).hexdigest()
    state=state_event.details.get('state','not_checked') if state_event and state_event.details.get('signature')==signature else 'not_checked'
    requests=list(plan.events.filter(action='green_request'))
    resolved=set(plan.events.filter(action__in=['green_approve','green_decline']).values_list('details__request',flat=True))
    pending=[r for r in requests if r.pk not in resolved]
    return {'plan':plan,'groups':groups,'gaps':sorted(set(gaps)),'items':items,'totals':dict(totals),'state':state,'token':token,'signature':signature,'shortages':any(g['shortages'] for g in groups),'pending':pending}

def save_action(plan_id,post,actor):
    with transaction.atomic():
        plan=get_object_or_404(RoastPlan.objects.select_for_update(),pk=plan_id,historical=False,closed_at__isnull=True)
        action=post.get('action')
        if action=='approve':
            # Serialize with measured deductions and manual counts before checking availability.
            list(GreenBeanItem.objects.select_for_update().order_by('pk'))
        context=review_context(plan)
        if post.get('review_token')!=context['token']:raise ValidationError('Stock, this plan or its requests changed. Reload and review the current choices.')
        if action in ['check','skip']:
            state='skipped' if action=='skip' else 'needs_review' if context['gaps'] or context['shortages'] else 'checked'
            PlanEvent.objects.create(plan=plan,actor=actor,action='green_review',details={'state':state,'signature':context['signature']})
            return 'Green-stock check skipped; availability is not confirmed.' if action=='skip' else 'Recorded balances checked. Review any missing recipes or shortages below; production remains available.'
        if action=='request':
            group_row=next((g for g in context['groups'] if str(g['group'].pk)==post.get('group')),None)
            source=next((s for s in group_row['shortages'] if str(s['source'].pk)==post.get('source')),None) if group_row else None
            replacement=next((c for c in source['candidates'] if str(c['item'].pk)==post.get('replacement')),None) if source else None
            if not replacement:raise ValidationError('Choose a currently available suggested origin for this shortage.')
            PlanEvent.objects.create(plan=plan,actor=actor,action='green_request',details={'group':group_row['group'].pk,'coffee':group_row['group'].coffee.name,'roast':group_row['group'].roast_level,'source':source['source'].pk,'source_name':source['source'].name,'replacement':replacement['item'].pk,'replacement_name':replacement['item'].name,'signature':context['signature'],'roast_note':replacement['roast_note'],'shared_flavors':replacement['shared']})
            return 'Substitution requested. No recipe or stock changed; review and approve it below.'
        if action in ['approve','decline']:
            request=next((r for r in context['pending'] if str(r.pk)==post.get('request')),None)
            if not request:raise ValidationError('That substitution request has already been resolved or belongs to another plan.')
            if action=='decline':
                PlanEvent.objects.create(plan=plan,actor=actor,action='green_decline',details={'request':request.pk});return 'Substitution declined. Recipes and stock are unchanged.'
            if request.details['signature']!=context['signature']:raise ValidationError('The plan or stock changed after this request. Decline it and request a fresh choice.')
            if not post.get('confirmed'):raise ValidationError('Confirm roast suitability, caffeine type and product/label suitability before approving.')
            row=next((g for g in context['groups'] if g['group'].pk==request.details['group']),None)
            source=next((s for s in row['shortages'] if s['source'].pk==request.details['source']),None) if row else None
            candidate=next((c for c in source['candidates'] if c['item'].pk==request.details['replacement']),None) if source else None
            if not candidate:raise ValidationError('This replacement no longer covers the shortage. Update counts or request a different origin.')
            PlanEvent.objects.create(plan=plan,actor=actor,action='green_approve',details={'request':request.pk,'group':row['group'].pk,'parts':candidate['parts'],'before_parts':row['parts'],'source_name':source['source'].name,'replacement_name':candidate['item'].name,'roast':row['group'].roast_level,'confirmed_product_and_caffeine':True})
            plan.version+=1;plan.save(update_fields=['version'])
            return 'Green-origin substitution approved for this plan group’s unmeasured loads. Stock changes when measured; global recipes and recorded batches stay unchanged.'
        if action=='cancel':
            row=next((g for g in context['groups'] if str(g['group'].pk)==post.get('group') and g['approved'] and g['approved'].action=='green_approve'),None)
            if not row:raise ValidationError('There is no active substitution for this group’s remaining loads.')
            PlanEvent.objects.create(plan=plan,actor=actor,action='green_cancel',details={'group':row['group'].pk,'approval':row['approved'].pk})
            plan.version+=1;plan.save(update_fields=['version'])
            return 'Substitution cancelled for remaining loads. Already measured ingredient records stay unchanged.'
        raise ValidationError('Choose Check, Skip or a substitution action.')

@staff_member_required
@require_POST
def green_review_action(request,pk):
    try:messages.success(request,save_action(pk,request.POST,request.user))
    except ValidationError as exc:
        from django.http import HttpResponse
        return HttpResponse('; '.join(exc.messages)+' Return to the plan and reload before retrying.',status=409)
    return redirect('/planning/?plan='+str(pk))
