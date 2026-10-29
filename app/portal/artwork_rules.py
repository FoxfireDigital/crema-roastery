"""Rules for roast-neutral masters; production roast profiles stay explicit."""
import math
from decimal import Decimal
from django.core.exceptions import ValidationError

NEUTRAL_ROAST='Unmarked'
NEUTRAL_CHOICE=(NEUTRAL_ROAST,'No fixed roast — 5 lb single origins')


def neutral_allowed(coffee,size,per_sheet=4):
    return coffee.kind=='single_origin' and size==Decimal(80) and per_sheet==4


def validate_masks(masks):
    if not isinstance(masks,list) or len(masks)>5:raise ValidationError('Invalid print-only cover regions.')
    for mask in masks:
        if not isinstance(mask,dict) or set(mask)!=set(('x','y','w','h')):raise ValidationError('Invalid print-only cover region.')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in mask.values()):raise ValidationError('Invalid print-only cover coordinates.')
        x,y,w,h=(mask[k] for k in ('x','y','w','h'))
        if not (0<=x<1 and 0<=y<1 and 0<w<=1 and 0<h<=.1 and x+w<=1 and y+h<=1):raise ValidationError('Print-only cover region exceeds the artwork.')
