"""Spare labels ranked from actual orders; never creates roasting demand."""
from datetime import timedelta
from decimal import Decimal
import hashlib,json
from django.utils import timezone
from django.db.models import Q
from .models import ImportOrder,IncomingOrderLine,CustomOrder,Coffee,LabelVariant,GRIND_CHOICES


def sales_snapshot(now=None):
    now=now or timezone.now();since=now-timedelta(days=21)
    imports=list(ImportOrder.objects.filter(received_at__gte=since,received_at__lte=now).order_by('pk').values('id','received_at','financial_status','cancelled','source_changed','lines'))
    manual=list(IncomingOrderLine.objects.filter(Q(wholesale_order__isnull=False)|Q(group__legacy_order__isnull=False,group__legacy_order__cancelled_at__isnull=True),received_at__gte=since,received_at__lte=now,group__plan__removed_at__isnull=True).order_by('pk').values('id','product_coffee_id','product_label_id','packaging','grind','group__roast_level','group__target_finish_temp_f'))
    return imports,manual


def sales_revision():return hashlib.sha256(json.dumps(sales_snapshot(),sort_keys=True,default=str).encode()).hexdigest()


def bestseller_labels(now=None):
    from .label_sheets import find_art
    from .flavoring import import_packaging
    from .order_import import infer_grind
    coffees={c.pk:c for c in Coffee.objects.filter(active=True,experimental=False)}
    labels={l.pk:l for l in LabelVariant.objects.filter(active=True,coffee__active=True)}
    counts={};details={}
    def add(coffee_id,label_id,packs,roast,grind,temp=None):
        coffee=coffees.get(coffee_id);label=labels.get(label_id) if label_id else None
        if not coffee or label_id and (not label or label.coffee_id!=coffee.pk) or grind not in ['whole','regular','fine','coarse']:return
        for pack in packs:
            try:
                size=Decimal(str(pack['size_oz']));number=Decimal(str(pack['bags']));bags=int(number)
                assert size.is_finite() and size>0 and 0<bags<=1000000 and number==bags
                layout=int(pack.get('per_sheet') or (4 if size in [12,16,80] else 8 if size==Decimal('2.5') else 0))
                assert layout in [4,8]
            except (KeyError,ValueError,TypeError,ArithmeticError,AssertionError):continue
            roast=roast or coffee.standard_roast
            if roast not in ['Light','Light/Medium','Medium','Medium/Dark','Dark','French']:continue
            key=(coffee.pk,label_id or None,str(size.normalize()),roast,grind,str(temp) if temp is not None else None,layout)
            counts[key]=counts.get(key,0)+bags;details[key]=(coffee,label,size,roast,grind,temp,layout)
    imports,manual=sales_snapshot(now)
    for order in imports:
        if order['financial_status']!='paid' or order['cancelled'] or order['source_changed']:continue
        for item in order['lines']:
            if item.get('skip') or item.get('cycle_choice') or item.get('needs_cycle_assignment') or item.get('roast_review'):continue
            try:packs=import_packaging(item)
            except (ValueError,TypeError,ArithmeticError):continue
            add(item.get('coffee'),item.get('label_variant'),packs,item.get('roast_level'),item.get('grind') or infer_grind(item.get('title','')),item.get('target_finish_temp_f'))
    for line in manual:add(line['product_coffee_id'],line['product_label_id'],line['packaging'],line['group__roast_level'],line['grind'],line['group__target_finish_temp_f'])
    # Earlier custom orders lack confirmed grind, so they cannot safely select a
    # printed grind label until allocated through a current confirmed workflow.
    pool=[]
    for key in sorted(counts,key=lambda k:(-counts[k],coffees[k[0]].name,str(k))):
        coffee,label,size,roast,grind,temp,layout=details[key]
        art,issue=find_art(coffee.name,label.name if label else '',size,roast,temp,grind=grind)
        if issue or art.get('per_sheet',layout)!=layout:continue
        digest=hashlib.sha256(json.dumps(key).encode()).hexdigest()
        pool.append({'kind':'bestseller','cycle_key':'bestseller:'+digest,'contract_id':None,'contract':'Stock labels',
                     'due_display':'Most ordered in the last 21 days · '+str(counts[key])+' bags','coffee':coffee.name,'label':label.name if label else '',
                     'size':format(size.normalize(),'f'),'grind':dict(GRIND_CHOICES)[grind],'roast':roast,'ordered_bags':counts[key],
                     'bags':8,'layout':layout,'art':art,'reference':'Spare labels — recent bestseller','issue':''})
    return pool
