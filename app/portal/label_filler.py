"""Upcoming-subscription labels are forecasts, never production demand."""
from datetime import timedelta
from decimal import Decimal,InvalidOperation
import hashlib,json
from django.utils import timezone
from .models import SubscriptionContract,Coffee,LabelVariant,LabelPrintRun,LabelQueueLock,GRIND_CHOICES
from .order_import import infer_grind,expand_frac_line

LOOKAHEAD_DAYS=14

def forecast_revision(include_queue=True):
    from .label_bestsellers import sales_revision
    contracts=list(SubscriptionContract.objects.order_by('pk').values('pk','status','next_billing_at','lines','refreshed_at'))
    version=(LabelQueueLock.objects.filter(pk=1).values_list('version',flat=True).first() or 0) if include_queue else None
    return hashlib.sha256(json.dumps([version,contracts,sales_revision()],sort_keys=True,default=str).encode()).hexdigest()

def upcoming_labels(now=None):
    from .label_sheets import find_art
    now=now or timezone.now();until=now+timedelta(days=LOOKAHEAD_DAYS)
    reserved={}
    for extras in LabelPrintRun.objects.filter(status__in=['queued','printed']).exclude(subscription_labels=[]).values_list('subscription_labels',flat=True):
        for row in extras:reserved[row['cycle_key']]=reserved.get(row['cycle_key'],0)+row['bags']
    pool={};issues=[]
    contracts=SubscriptionContract.objects.filter(status='ACTIVE',next_billing_at__gte=now,next_billing_at__lte=until).order_by('next_billing_at','pk')
    for contract in contracts:
        if contract.refreshed_at<now-timedelta(days=14):
            issues.append('Subscription '+contract.external_id+': export is over 14 days old; refresh it first.');continue
        items=[]
        for index,item in enumerate(contract.lines):
            items.extend(expand_frac_line({**item,'source_line':str(index+1),'line_key':str(index+1)}))
        for index,item in enumerate(items):
            if item.get('skip'):continue
            prefix='Subscription '+contract.external_id+': '
            if item.get('needs_cycle_assignment') or item.get('cycle_choice'):
                issues.append(prefix+'choose this cycle\'s coffees before preparing advance labels.');continue
            coffee=Coffee.objects.filter(pk=item.get('coffee'),active=True).first() if item.get('coffee') else None
            if not coffee:issues.append(prefix+'coffee mapping is missing.');continue
            label=LabelVariant.objects.filter(pk=item['label_variant'],coffee=coffee,active=True).first() if item.get('label_variant') else None
            if item.get('label_variant') and not label:issues.append(prefix+'special label needs review.');continue
            try:
                size=Decimal(str(item['size_oz']));number=Decimal(str(item['quantity']));bags=int(number)
                if not size.is_finite() or size<=0 or bags<=0 or number!=bags:raise ValueError()
            except (KeyError,TypeError,ValueError,InvalidOperation,OverflowError):
                issues.append(prefix+'bag size or count needs confirmation.');continue
            grind=item.get('grind') or infer_grind(item.get('title',''))
            if grind not in ['whole','regular','fine','coarse']:issues.append(prefix+'grind size needs confirmation.');continue
            roast=item.get('roast_level') or coffee.standard_roast
            if item.get('roast_review') or (coffee.roast_locked or size*bags<80) and roast!=coffee.standard_roast:
                issues.append(prefix+'roast needs review.');continue
            art,issue=find_art(coffee.name,label.name if label else '',size,roast,item.get('target_finish_temp_f'),grind=grind)
            if issue:issues.append(prefix+coffee.name+': '+issue);continue
            layout=4 if size in (12,16,80) else int(item.get('per_sheet') or 0)
            if layout not in (4,8):issues.append(prefix+'sheet layout needs confirmation.');continue
            if art.get('per_sheet',layout)!=layout:issues.append(prefix+'artwork sheet layout needs confirmation.');continue
            identity=[contract.pk,contract.next_billing_at.isoformat(),item.get('variant_id') or str(index),coffee.pk,label.pk if label else None,str(size.normalize()),grind,roast]
            key=hashlib.sha256(json.dumps(identity).encode()).hexdigest()
            if key in pool:pool[key]['bags']+=bags;continue
            pool[key]={'cycle_key':key,'contract_id':contract.pk,'contract':contract.external_id,'due_at':contract.next_billing_at.isoformat(),
               'due_display':timezone.localtime(contract.next_billing_at).strftime('%b %d, %Y'),'coffee':coffee.name,'label':label.name if label else '',
               'size':format(size.normalize(),'f'),'grind':dict(GRIND_CHOICES)[grind],
               'bags':bags,'layout':layout,'art':art,'reference':'Advance label - '+contract.external_id,'issue':''}
    result=[]
    for key,row in pool.items():
        row['bags']=max(0,row['bags']-reserved.get(key,0))
        if row['bags']:result.append(row)
    return result,sorted(set(issues))

def fill_last_sheet(chosen,data,pool,bestsellers=None):
    count=sum(row['bags'] for row in chosen)
    if not count:return []
    remaining=(-(count+data['start_slot']-1))%data['layout']
    added=[]
    for row in pool if data.get('fill_subscriptions') else []:
        if not remaining:break
        if row['layout']!=data['layout']:continue
        number=min(remaining,row['bags'])
        if number:added.append({**row,'bags':number});remaining-=number
    if remaining and data.get('fill_bestsellers'):
        sizes={Decimal(str(row['size'])) for row in chosen if row.get('size')}
        for row in bestsellers or []:
            if row['layout']==data['layout'] and Decimal(row['size']) in sizes:
                added.append({**row,'bags':remaining});break
    return added
