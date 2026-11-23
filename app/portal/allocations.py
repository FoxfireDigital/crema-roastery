"""Compact per-delivery allocation editing, bounded by the original Shopify items."""
import copy,hashlib,json
from decimal import Decimal,InvalidOperation
from django.core.exceptions import ValidationError
from .models import Coffee,LabelVariant,GRIND_CHOICES,OrderReviewEvent,ProductMapping


def review_token(order):
    return hashlib.sha256(json.dumps([order.lines,order.instructions,order.instructions_confirmed,order.source_signature,order.latest_lines,order.latest_api_signature,str(order.imported_at),str(order.dismissed_at)],sort_keys=True).encode()).hexdigest()


def source_groups(order):
    groups={}
    for index,item in enumerate(order.lines):
        key=str(item.get('line_key',index+1)) if item.get('frac_bag') or item.get('bundle_id') else str(item.get('source_line',item.get('line_key',index+1)))
        group=groups.setdefault(key,{'key':key,'title':item['title'],'items':[],'expected_oz':item.get('source_total'),'frac':bool(item.get('frac_bag')),'bundle':bool(item.get('bundle_id')),'fulfilled':bool(item.get('fulfilled')),'cycle':bool(item.get('cycle_choice'))})
        group['items'].append(item)
        if group['frac'] or group['bundle']:
            group['expected_oz']=str(Decimal(str(item.get('size_oz') or '2.5'))*int(item['quantity']))
    for group in groups.values():
        group['allocations']=[]
        for item in group['items']:
            try:weight=Decimal(str(item.get('size_oz')))*int(item['quantity'])
            except (InvalidOperation,TypeError,ValueError):weight=None
            size=item.get('size_oz')
            if group['cycle'] and weight and weight>=16 and weight%16==0:size='16'
            group['allocations'].append({'source':group['key'],'coffee':item.get('coffee') or '','label':item.get('label_variant') or '','finished_oz':str(weight) if weight is not None else '', 'bag_size_oz':str(size or ''),'roast':item.get('roast_level') or '', 'temperature':item.get('target_finish_temp_f') or '', 'grind':item.get('grind') or 'unknown','skip':bool(item.get('skip'))})
    return list(groups.values())


def save_allocations(order,payload,revision,actor,instructions_confirmed=False):
    """Caller locks the source order; reject all rows together on any mismatch."""
    from .planning import IncomingForm
    if revision!=review_token(order):raise ValidationError('This order changed in another tab. Reload before saving your assortment.')
    if order.imported_at or order.dismissed_at or order.source_changed:raise ValidationError('Review the order’s current import status before editing its coffees.')
    if not isinstance(payload,list) or not 1<=len(payload)<=200:raise ValidationError('Use between 1 and 200 allocations.')
    groups={g['key']:g for g in source_groups(order)};actual={key:Decimal(0) for key in groups};seen=set();lines=[]
    for index,entry in enumerate(payload,1):
        if not isinstance(entry,dict):raise ValidationError('Choose valid coffee allocations.')
        key=str(entry.get('source',''));group=groups.get(key)
        if not group:raise ValidationError('An allocation no longer matches an original Shopify item.')
        item=copy.deepcopy(group['items'][0]);seen.add(key)
        if group['fulfilled']:
            if key in [str(line.get('allocation_source')) for line in lines]:raise ValidationError('Fulfilled items cannot be split.')
            item['allocation_source']=key;lines.append(item);actual[key]=Decimal(str(group['expected_oz'] or 0));continue
        skip=entry.get('skip') is True
        try:
            total=Decimal(str(entry.get('finished_oz') or 0));bag=Decimal(str(entry.get('bag_size_oz') or 0))
            if not total.is_finite() or not bag.is_finite() or total<0 or total>160000 or total!=total.quantize(Decimal('.1')):raise ValueError()
            if not skip and (total<=0 or bag<Decimal('.1') or bag!=bag.quantize(Decimal('.1')) or total%bag!=0 or total/bag>100000):raise ValueError()
        except (InvalidOperation,ValueError,TypeError):raise ValidationError('Use positive finished ounces in tenths. Bag size × bag count must equal the allocation.')
        actual[key]+=total
        if not skip:
            c=Coffee.objects.filter(pk=str(entry.get('coffee','')) if str(entry.get('coffee','')).isdigit() else None,active=True).first()
            if not c:raise ValidationError('Choose an active coffee for every included allocation.')
            label=LabelVariant.objects.filter(pk=str(entry.get('label','')) if str(entry.get('label','')).isdigit() else None,active=True,coffee=c).first() if entry.get('label') else None
            if entry.get('label') and not label:raise ValidationError('Choose a label belonging to this coffee.')
            roast=entry.get('roast') or c.standard_roast
            if c.roast_locked or total<80:roast=c.standard_roast
            temp=entry.get('temperature') or None
            if temp and (c.roast_locked or total<80):raise ValidationError('Only single-origin allocations of at least 5 lb can request a temperature.')
            form=IncomingForm({'coffee':c.pk,'label_variant':label.pk if label else '', 'extra_oz':str(total),'roast_level':roast,'target_finish_temp_f':temp or ''})
            if not form.is_valid():raise ValidationError([str(error) for values in form.errors.values() for error in values])
            grind=entry.get('grind','unknown')
            if grind not in dict(GRIND_CHOICES):raise ValidationError('Choose a valid grind.')
            item.update(coffee=c.pk,label_variant=label.pk if label else None,roast_level=roast,target_finish_temp_f=str(temp) if temp else None,grind=grind,quantity=int(total/bag),size_oz=str(bag),skip=False)
        else:item.update(skip=True,quantity=1,size_oz=str(total) if total else None)
        if group['bundle']:
            original=group['items'][0]
            if skip or any(str(line.get('allocation_source'))==key for line in lines) or item.get('coffee')!=original.get('coffee') or item.get('label_variant')!=original.get('label_variant') or bag!=Decimal(str(original['size_oz'])) or total!=Decimal(group['expected_oz']):raise ValidationError('Box components keep their coffee, packaging label, bag count and bag size. You can change their grind.')
            item['line_key']=original['line_key']
        elif group['frac']:
            if len([line for line in lines if str(line.get('allocation_source'))==key]) or item.get('coffee')!=group['items'][0].get('coffee') or (not skip and (bag!=Decimal('2.5') or total!=Decimal(group['expected_oz']))):raise ValidationError('Frac components keep their coffee, bag count and 2.5 oz bag size.')
            item['line_key']=group['items'][0]['line_key']
        else:item['line_key']=key+'.a'+str(index)
        item['source_line']=group['items'][0].get('source_line',key)
        item['source_quantity']=group['items'][0].get('source_quantity',group['items'][0].get('quantity',1))
        item['source_total']=group['items'][0].get('source_total')
        item['allocation_source']=key
        lines.append(item)
    if seen!=set(groups):raise ValidationError('Keep every original item represented. Use Exclude for merchandise.')
    for key,group in groups.items():
        if group['expected_oz'] is not None and actual[key]!=Decimal(str(group['expected_oz'])):raise ValidationError(f"Allocations for {group['title']} must total {group['expected_oz']} oz, including excluded portions.")
    before={'lines':copy.deepcopy(order.lines),'instructions_confirmed':order.instructions_confirmed}
    from .order_import import mapping_key
    for key,group in groups.items():
        portions=[(entry,line) for entry,line in zip(payload,lines) if str(entry.get('source'))==key]
        if group['cycle'] or group['frac'] or group['bundle'] or len(portions)!=1 or not portions[0][0].get('remember'):continue
        entry,line=portions[0];original=group['items'][0]
        original_quantity=int(original.get('source_quantity',original.get('quantity')) or 1)
        size=Decimal(str(group['expected_oz']))/original_quantity if group['expected_oz'] is not None else Decimal(str(line.get('size_oz') or 0))*int(line.get('quantity',1))/original_quantity
        from .stores import remember_mapping
        if remember_mapping(order,line,actor):continue
        ProductMapping.objects.update_or_create(fingerprint=mapping_key(original['title'],original.get('sku','')),defaults={'title':original['title'][:500],'sku':original.get('sku','')[:150],'coffee_id':line.get('coffee') if not line.get('skip') else None,'label_variant_id':line.get('label_variant') if not line.get('skip') else None,'size_oz':size if size>0 else None,'skip':line.get('skip',False),'updated_by':actor})
    order.lines=lines;order.instructions_confirmed=instructions_confirmed
    order.save(update_fields=['lines','instructions_confirmed'])
    after={'lines':copy.deepcopy(lines),'instructions_confirmed':instructions_confirmed}
    if before!=after:OrderReviewEvent.objects.create(order=order,actor=actor,before=before,after=after)
