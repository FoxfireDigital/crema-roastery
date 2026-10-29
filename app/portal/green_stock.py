"""Green-origin counts and repeat-safe deductions from measured roaster loads."""
from decimal import Decimal,ROUND_FLOOR,ROUND_HALF_UP
import hashlib,json,uuid
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction,IntegrityError
from django.db.models import F
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import Coffee,Batch,PlannedBatch,GreenBeanItem,GreenRecipe,GreenBatchUsage,GreenMovement,GreenRecipeEvent
from .inventory_actor import current_actor

TENTH=Decimal('.1')
SALT='coffee-green-stock'


def inventory_context(request):
    count=GreenBeanItem.objects.filter(active=True,remaining_oz__lte=F('reorder_oz')).count() if request.user.is_authenticated and request.user.is_staff and request.path=='/' else 0
    return {'green_reorder_count':count}


def split(total,percentages):
    total=Decimal(total).quantize(TENTH);parts={str(k):total*Decimal(str(v))/100 for k,v in percentages.items()}
    result={k:v.quantize(TENTH,rounding=ROUND_FLOOR) for k,v in parts.items()}
    extra=int((total-sum(result.values(),Decimal(0)))/TENTH)
    for k in sorted(parts,key=lambda k:(-(parts[k]-result[k]),int(k)))[:extra]:result[k]+=TENTH
    return result


def recipe_percentages(coffee_id):
    recipe=GreenRecipe.objects.filter(coffee_id=coffee_id).first()
    if not recipe:return {}
    try:
        result={str(c['item']):str(Decimal(c['percent'])) for c in recipe.components}
        if len(result)!=len(recipe.components) or not 1<=len(result)<=12 or any(not Decimal(v).is_finite() or not 0<Decimal(v)<=100 for v in result.values()) or sum(map(Decimal,result.values()))!=100:return {}
        if GreenBeanItem.objects.filter(pk__in=result,active=True).count()!=len(result):return {}
        return result
    except (KeyError,ValueError,TypeError,ArithmeticError):return {}


def sync_batch(batch,previous):
    """Caller holds the batch lock/transaction. Existing old loads are not backfilled."""
    usage=GreenBatchUsage.objects.select_for_update().filter(batch=batch).first()
    used=lambda b:bool(b and not b.removed_at and (b.measured_at or b.roasted_at or b.roasted_oz is not None or b.bagged_at or b.sealed_at) and not b.merged_into_id)
    if not usage and (not used(batch) or used(previous)):return
    if usage:
        percentages=usage.percentages
        if previous and (previous.green_item_id!=batch.green_item_id or previous.coffee_id!=batch.coffee_id and not batch.green_item_id):
            percentages={str(batch.green_item_id):'100'} if batch.green_item_id else recipe_percentages(batch.coffee_id)
            if not percentages:raise ValidationError('Set a green recipe or direct origin before changing this already-accounted load’s green source.')
    else:percentages={str(batch.green_item_id):'100'} if batch.green_item_id else recipe_percentages(batch.coffee_id)
    if not percentages:return
    desired=split(batch.green_oz,percentages) if used(batch) else {}
    old={k:Decimal(v) for k,v in (usage.amounts if usage else {}).items()}
    ids=sorted({int(k) for k in old}|{int(k) for k in desired})
    items={str(s.pk):s for s in GreenBeanItem.objects.select_for_update().filter(pk__in=ids).order_by('pk')}
    if len(items)!=len(ids):raise ValidationError('A linked green origin is missing. Review green inventory.')
    for key in map(str,ids):
        delta=old.get(key,Decimal(0))-desired.get(key,Decimal(0))
        if not delta:continue
        item=items[key];before=item.remaining_oz;item.remaining_oz+=delta;item.version+=1
        item.save(update_fields=['remaining_oz','version','updated_at'])
        GreenMovement.objects.create(item=item,batch=batch,actor_id=current_actor.get() or batch.operator_id,action='batch_usage' if delta<0 else 'batch_return',delta_oz=delta,before_oz=before,after_oz=item.remaining_oz,note='Measured load / correction; original recipe retained.')
    if not usage:usage=GreenBatchUsage(batch=batch)
    usage.percentages=percentages;usage.amounts={k:str(v) for k,v in desired.items()};usage.save()


def amount(value,unit):
    try:
        v=Decimal(str(value));assert v.is_finite() and 0<=v<=99999999 and unit in ['lb','oz']
        return (v*(16 if unit=='lb' else 1)).quantize(TENTH,rounding=ROUND_HALF_UP)
    except (ValueError,TypeError,ArithmeticError,AssertionError):raise ValidationError('Enter a nonnegative weight in pounds or ounces.')


def token(actor):return signing.dumps({'user':actor.pk,'nonce':str(uuid.uuid4())},salt=SALT)


def request_identity(post,actor):
    try:
        data=signing.loads(post.get('request_token',''),salt=SALT,max_age=4*3600);assert data['user']==actor.pk
        nonce=uuid.UUID(data['nonce'])
    except (signing.BadSignature,KeyError,ValueError,TypeError,AssertionError):raise ValidationError('This stock form expired. Reload before saving.')
    body={k:post.getlist(k) for k in post if k not in ['csrfmiddlewaretoken','request_token']}
    return nonce,hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()


class NewItemForm(forms.Form):
    name=forms.CharField(max_length=120,label='Green origin / lot name')
    quantity=forms.DecimalField(min_value=0,max_digits=11,decimal_places=3,label='Starting available weight')
    unit=forms.ChoiceField(choices=[('lb','Pounds'),('oz','Ounces')])
    reorder=forms.DecimalField(min_value=0,max_digits=11,decimal_places=3,label='Reorder at or below',initial=0)
    notes=forms.CharField(required=False,widget=forms.Textarea(attrs={'rows':2}),label='Supplier / lot notes')


def save_recipe(post,actor):
    coffee=get_object_or_404(Coffee,pk=post.get('coffee'),active=True,experimental=False)
    if coffee.kind=='flavored':raise ValidationError('Set the recipe for the physical roast base, such as the configured Medium base.')
    pairs=list(zip(post.getlist('ingredient'),post.getlist('percent')))
    if len(post.getlist('ingredient'))!=len(post.getlist('percent')) or len(pairs)>12:raise ValidationError('Use at most 12 recipe ingredients.')
    components=[];seen=set()
    for item,value in pairs:
        if not item and not value:continue
        try:
            pk=int(item);percent=Decimal(value);assert percent.is_finite() and 0<percent<=100 and pk not in seen
        except (ValueError,TypeError,ArithmeticError,AssertionError):raise ValidationError('Choose each origin once with a positive percentage.')
        if not GreenBeanItem.objects.filter(pk=pk,active=True).exists():raise ValidationError('Choose active green origins.')
        components.append({'item':pk,'percent':str(percent)});seen.add(pk)
    if not components or sum(Decimal(c['percent']) for c in components)!=100:raise ValidationError('The recipe percentages must total exactly 100%.')
    with transaction.atomic():
        Coffee.objects.select_for_update().get(pk=coffee.pk)
        recipe=GreenRecipe.objects.select_for_update().filter(coffee=coffee).first()
        if str(recipe.version if recipe else 0)!=post.get('version','0'):raise ValidationError('This recipe changed. Reload before saving.')
        before=recipe.components if recipe else []
        if not recipe:recipe=GreenRecipe(coffee=coffee,updated_by=actor)
        recipe.components=components;recipe.updated_by=actor;recipe.version+=1;recipe.save()
        GreenRecipeEvent.objects.create(recipe=recipe,actor=actor,before=before,after=components)
    return recipe


def change_stock(post,actor):
    nonce,fingerprint=request_identity(post,actor)
    def prior():
        saved=GreenMovement.objects.filter(request_key=nonce).first()
        if saved and saved.request_hash!=fingerprint:raise ValidationError('This saved form has different values. Reload before another change.')
        return saved
    if prior():return False
    action=post.get('action')
    with transaction.atomic():
        if action=='create':
            form=NewItemForm(post)
            if not form.is_valid():raise ValidationError([str(e) for errors in form.errors.values() for e in errors])
            data=form.cleaned_data
            if GreenBeanItem.objects.filter(name__iexact=data['name'].strip()).exists():raise ValidationError('That green origin already exists. Use its receipt or count controls.')
            value=amount(data['quantity'],data['unit']);reorder=amount(data['reorder'],data['unit'])
            item=GreenBeanItem.objects.create(name=data['name'].strip(),remaining_oz=value,reorder_oz=reorder,notes=data['notes'],recorded_by=actor)
            before=Decimal(0);delta=value
        else:
            item=get_object_or_404(GreenBeanItem.objects.select_for_update(),pk=post.get('item'))
            if prior():return False
            if str(item.version)!=post.get('version'):raise ValidationError('This balance changed, possibly from a measured batch. Reload before saving.')
            before=item.remaining_oz
            if action in ['receipt','count','use']:
                value=amount(post.get('quantity'),post.get('unit'))
                if action!='count' and not value:raise ValidationError('Enter a weight greater than zero.')
                delta=value if action=='receipt' else -value if action=='use' else value-before
                item.remaining_oz+=delta
            elif action=='settings':
                item.reorder_oz=amount(post.get('reorder'),post.get('unit'));item.notes=post.get('note','')[:2000];delta=Decimal(0)
            else:raise ValidationError('Choose a receipt, usage, fresh count, or reorder setting.')
            item.version+=1;item.save()
        GreenMovement.objects.create(item=item,actor=actor,action=action,delta_oz=delta,before_oz=before,after_oz=item.remaining_oz,note=post.get('note','')[:300],request_key=nonce,request_hash=fingerprint)
    return True


@staff_member_required
@require_http_methods(['GET','POST'])
def green_stock_page(request):
    error='';status=200
    if request.method=='POST':
        try:
            if request.POST.get('action')=='recipe':save_recipe(request.POST,request.user);messages.success(request,'Green recipe saved. It applies to newly measured loads; existing deductions keep their original recipe.')
            else:changed=change_stock(request.POST,request.user);messages.success(request,'Green stock saved.' if changed else 'That stock change was already saved.')
            return redirect('/green-beans/')
        except (ValidationError,IntegrityError) as exc:error='; '.join(exc.messages) if isinstance(exc,ValidationError) else 'That change was already saved or its name exists. Reload to review the current stock.';status=400
    from .green_forecast import accepted_loads
    items=list(GreenBeanItem.objects.filter(active=True));by_id={s.pk:s for s in items}
    planned,_,pending_gaps=accepted_loads(items)
    unmapped={gap['coffee'] for gap in pending_gaps}
    for item in items:
        item.pounds=(item.remaining_oz/16).quantize(Decimal('.1'));item.planned_oz=planned[item.pk];item.after_planned=item.remaining_oz-item.planned_oz
        item.reorder_lb=(item.reorder_oz/16).quantize(Decimal('.001'));item.reorder_due=item.after_planned<=item.reorder_oz
        item.form_token=token(request.user);item.settings_token=token(request.user)
    recipes=list(GreenRecipe.objects.select_related('coffee').order_by('coffee__name'))
    for recipe in recipes:recipe.description=', '.join(f"{by_id[c['item']].name if c['item'] in by_id else 'Inactive origin'} {c['percent']}%" for c in recipe.components)
    selected=GreenRecipe.objects.filter(coffee_id=request.GET.get('recipe')).first() if request.GET.get('recipe','').isdigit() else None
    ingredients=selected.components if selected else [{'item':'','percent':'100'}]
    recent=Batch.objects.filter(measured_at__isnull=False,green_usage__isnull=True,merged_into__isnull=True).select_related('coffee').order_by('-measured_at')[:12]
    return render(request,'portal/green_stock.html',{'items':items,'low_count':sum(s.reorder_due for s in items),'error':error,'new_form':NewItemForm(request.POST if request.method=='POST' and request.POST.get('action')=='create' else None),'new_token':token(request.user),'recipes':recipes,'recipe':selected,'ingredients':ingredients,'coffees':Coffee.objects.filter(active=True,experimental=False).exclude(kind='flavored'),'unmapped':sorted(unmapped),'untracked':recent,'movements':GreenMovement.objects.select_related('item','actor','batch')[:40]},status=status)
