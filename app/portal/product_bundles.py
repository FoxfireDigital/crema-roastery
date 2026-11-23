"""Expand explicitly configured boxes into individually packed coffee demand."""
import copy
from decimal import Decimal
from django.core.exceptions import ValidationError
from .models import ProductBundle


def match_bundle(line):
    title=line.get('title','').strip().casefold();sku=line.get('sku','').strip().casefold()
    matches=[]
    for bundle in ProductBundle.objects.filter(active=True).prefetch_related('items__coffee','items__label_variant'):
        base=bundle.source_title.casefold()
        if bundle.sku and bundle.sku.casefold()!=sku:continue
        if title==base or title.startswith(base+' - ') or title.startswith(base+' / '):matches.append(bundle)
    if not matches:return None
    priority=max((len(b.source_title),bool(b.sku)) for b in matches)
    matches=[b for b in matches if (len(b.source_title),bool(b.sku))==priority]
    if len(matches)!=1:raise ValidationError('Several configured coffee boxes match this product. Review the box definitions.')
    return matches[0]


def expand_bundle_line(line):
    if line.get('bundle_key') or line.get('skip') or line.get('cycle_choice'):return None
    bundle=match_bundle(line)
    if bundle is None:return None
    items=list(bundle.items.all())
    if not 1<=len(items)<=20:raise ValidationError('The coffee box needs between one and twenty component rows.')
    quantity=line.get('quantity')
    if type(quantity) is not int or not 1<=quantity<=100000:raise ValidationError('Confirm the coffee-box quantity.')
    for item in items:item.full_clean()
    total=sum((item.size_oz*item.bags for item in items),Decimal(0))*quantity
    # Preserve unknown/fine/coarse decisions when explicit; only an unspecified
    # source uses the configured default. Generic Ground still requires its grind.
    grind=line.get('grind') or 'unknown'
    if grind=='unknown' and not line.get('bundle_grind_explicit'):grind=bundle.default_grind
    result=[]
    for part in items:
        item=copy.deepcopy(line)
        item.update(bundle_key=str(line['source_line']),line_key=str(line['source_line'])+'.b'+str(part.pk),
                    bundle_id=bundle.pk,bundle_name=bundle.name,bundle_component=part.pk,
                    bundle_pack_count=quantity,source_total=str(total),quantity=quantity*part.bags,
                    size_oz=str(part.size_oz),coffee=part.coffee_id,label_variant=part.label_variant_id,
                    roast_level=part.coffee.standard_roast,target_finish_temp_f=None,
                    cycle_choice=False,needs_cycle_assignment=False,skip=False,grind=grind)
        result.append(item)
    return result


def bundle_source_grind(line,attributes):
    """Use explicit grind properties without guessing from unrelated gift notes."""
    if match_bundle(line) is None:return
    from .order_import import infer_grind
    values={line.get('grind','unknown')}-{'unknown'}
    explicit=False
    for attr in attributes or []:
        key=str(attr.get('key','')).casefold()
        if not any(word in key for word in ['grind','beans','bean style']):continue
        explicit=True
        value=infer_grind(str(attr.get('value','')))
        if value!='unknown':values.add(value)
    conflict='whole' in values and len(values)>1 or len(values-{'ground'})>1
    chosen=(values-{'ground'}) or values
    if not conflict and len(chosen)==1:line['grind']=next(iter(chosen))
    elif values or explicit:line['grind']='unknown'
    if explicit or conflict:line['bundle_grind_explicit']=True
