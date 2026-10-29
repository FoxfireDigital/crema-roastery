"""Owner decisions about supplied label names, separate from product availability."""
from collections import defaultdict
import re
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST
from .models import ArtworkCoffeeDecision,Coffee,ShopifyCatalog,ShopifyConnection
from .label_sheets import bundled_catalog


def original_groups():
    groups=defaultdict(list)
    for art in bundled_catalog():groups[art['coffee']].append(art)
    return groups


def review_rows():
    groups=original_groups();decisions={d.source_name:d for d in ArtworkCoffeeDecision.objects.select_related('coffee','updated_by')}
    active=set(Coffee.objects.filter(active=True).values_list('name',flat=True));pending=[];resolved=[]
    connection=ShopifyConnection.objects.filter(pk=1).first();snapshot=ShopifyCatalog.objects.filter(pk=1).first()
    current=bool(snapshot and snapshot.checked_at and connection and snapshot.shop_domain==connection.shop_domain)
    products=snapshot.products if current else []
    def key(value):return re.sub(r'[^a-z0-9]+',' ',value.casefold()).strip()
    for name,arts in sorted(groups.items()):
        decision=decisions.get(name)
        if name in active and not decision:continue
        normalized=key(name)
        exact=[p for p in products if key(p['title'])==normalized]
        possible=[] if exact else [p for p in products if key(p['title']).startswith(normalized+' ') or key(p['title']).endswith(' '+normalized)]
        state=decision.state if decision else 'review'
        if state=='matched' and not decision.coffee.active:state='review'
        history=[{**event,'at_display':parse_datetime(event['at'])} for event in decision.events] if decision else []
        row={'name':name,'decision':decision,'state':state,'version':decision.version if decision else 0,'coffee_id':decision.coffee_id if decision else None,'shopify':exact or possible,'possible':bool(possible),'has_snapshot':current,'assets':sorted(arts,key=lambda a:(float(a['size_oz']),a['id'])),'history':history}
        (pending if state=='review' else resolved).append(row)
    return pending,resolved,snapshot.checked_at if current else None


def save_decision(source,action,coffee_id,version,user):
    if action not in ('match','unavailable','reset'):raise ValidationError('Choose Save match, Not available, or Undo decision.')
    if source not in original_groups():raise ValidationError('Choose a supplied label from this checklist.')
    try:version=int(version)
    except (ValueError,TypeError):raise ValidationError('Reload this checklist before saving.')
    with transaction.atomic():
        # Existing active standard artwork is managed in the artwork library;
        # this screen handles unmatched originals and previously saved decisions.
        if Coffee.objects.filter(name=source,active=True).exists() and not ArtworkCoffeeDecision.objects.filter(source_name=source).exists():
            raise ValidationError('This label already has an active coffee. Manage its artwork in the artwork library.')
        decision,_=ArtworkCoffeeDecision.objects.get_or_create(source_name=source,defaults={'updated_by':user})
        decision=ArtworkCoffeeDecision.objects.select_for_update().get(pk=decision.pk)
        if version!=decision.version:raise ValidationError('This label decision changed. Reload and review the latest choice before saving.')
        coffee=None
        if action=='match':
            try:coffee=Coffee.objects.select_for_update().get(pk=coffee_id,active=True)
            except (Coffee.DoesNotExist,ValueError,TypeError):raise ValidationError('Choose an active coffee from the dropdown before saving the match.')
        state={'match':'matched','unavailable':'unavailable','reset':'review'}[action]
        before={'state':decision.state,'coffee':decision.coffee_id,'coffee_name':decision.coffee.name if decision.coffee_id else ''}
        after={'state':state,'coffee':coffee.pk if coffee else None,'coffee_name':coffee.name if coffee else ''}
        if before==after:return decision
        decision.state=state;decision.coffee=coffee;decision.version+=1;decision.updated_by=user
        decision.events.append({'actor':user.pk,'username':user.username,'at':timezone.now().isoformat(),'action':action,'before':before,'after':after})
        decision.save();return decision


@staff_member_required
@require_POST
def artwork_decision(request):
    try:
        action=request.POST.get('decision_action');source=request.POST.get('source_name','')
        decision=save_decision(source,action,request.POST.get('coffee'),request.POST.get('version'),request.user)
        if action=='match':message=f'{source} matched to {decision.coffee.name}. New label checks use this match; printed roast and bag-weight checks still apply.'
        elif action=='unavailable':message=f'{source} marked Not available. Its supplied artwork is kept for history and excluded from new label sheets.'
        else:message=f'{source} returned to review. Its original artwork name is restored.'
        messages.success(request,message)
    except ValidationError as error:messages.error(request,'; '.join(error.messages))
    return redirect('/information/#offered-coffees')
