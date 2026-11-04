"""Explicit, previewed replacements for compatible unstarted draft loads."""
from decimal import Decimal
import hashlib,json
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import Coffee,RoastPlan,Roaster,RoastGroup,PlannedBatch,IncomingOrderLine,PlanEvent,GreenRecipe,PackingProgress

SALT='crema-draft-combine-v1'
TENTH=Decimal('.1')
PACK_STEPS=('flavored_at','ground_at','bagged_at','labeled_at','sealed_at')


class MachineField(forms.ModelChoiceField):
    def label_from_instance(self,machine):return f'{machine.name} — {machine.minimum:g}–{machine.capacity:g} oz green'


class CombineForm(forms.Form):
    version=forms.IntegerField(min_value=0,widget=forms.HiddenInput)
    rows=forms.MultipleChoiceField(label='Drafts to combine',error_messages={'required':'Select at least two unstarted drafts.'})
    roaster=MachineField(queryset=Roaster.objects.none(),label='Use this roaster',empty_label=None)
    def __init__(self,*args,plan,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['rows'].choices=[(str(r.pk),str(r.pk)) for r in PlannedBatch.objects.filter(group__plan=plan)]
        machines=list(Roaster.objects.filter(active=True).order_by('pk'))
        safe=[r.pk for r in machines if r.capacity and r.capacity>=TENTH]
        self.fields['roaster'].queryset=Roaster.objects.filter(pk__in=safe)
        if safe:self.fields['roaster'].initial=max((r for r in machines if r.pk in safe),key=lambda r:(r.capacity,-r.pk)).pk
    def clean_rows(self):
        ids=self.cleaned_data['rows']
        if len(ids)!=len(set(ids)) or not 2<=len(ids)<=1000:raise ValidationError('Select between two and 1,000 different drafts.')
        return sorted(map(int,ids))


def group_block(group):
    if group.legacy_order_id:return 'This legacy custom order keeps its separate production workflow.'
    if group.coffee.experimental:return 'Experimental coffee needs its individual origin notes; adjust its drafts separately.'
    if group.planned_batches.filter(batch__isnull=False).exists():return 'This coffee profile has a production record. Keep its recorded work and adjust remaining drafts individually.'
    if group.plan.events.filter(action__in=['green_request','green_approve'],details__group=group.pk).exists():return 'This profile has a green-origin request or approval. Keep that reviewed recipe separate.'
    from .roasted_stock import used_for
    if used_for(group):return 'Bulk stock has already been used for this profile.'
    if any(any(getattr(p,key) for key in PACK_STEPS) for p in PackingProgress.objects.filter(line__group=group)):
        return 'Packing has already started for this profile.'
    if not group.orders.exists():return 'This profile has no active orders.'
    return ''


def preview(plan,row_ids,machine,*,lock=False):
    if plan.removed_at or plan.closed_at or plan.historical:raise ValidationError('Only an open, current plan can have its drafts combined.')
    if lock:machine=Roaster.objects.select_for_update().get(pk=machine.pk)
    if not machine.active or not machine.capacity or machine.capacity<TENTH:raise ValidationError('Choose an active roaster with a configured capacity.')
    rows=list(PlannedBatch.objects.filter(group__plan=plan,pk__in=row_ids).select_related('roaster','group__coffee').order_by('pk'))
    if len(rows)!=len(row_ids) or len(rows)<2:raise ValidationError('These drafts changed or were removed. Reload the plan and select them again.')
    if any(r.batch_id for r in rows):raise ValidationError('A selected draft has started. Recorded production cannot be combined here.')
    ids=sorted({r.group_id for r in rows})
    query=RoastGroup.objects.filter(plan=plan,pk__in=ids).order_by('pk')
    # Only lock groups here: label_variant is nullable, so PostgreSQL cannot
    # lock its outer-joined side. Coffee is explicitly locked below.
    if lock:query=query.select_for_update(of=('self',))
    groups=list(query.select_related('coffee','label_variant'))
    for group in groups:
        reason=group_block(group)
        if reason:raise ValidationError(reason)
    profile={(g.coffee_id,g.roast_level,g.target_finish_temp_f,g.loss_override if g.loss_override is not None else plan.estimated_loss_pct) for g in groups}
    if len(profile)!=1:raise ValidationError('Choose the same coffee, roast level, finish temperature and loss estimate. Different coffees cannot be combined just because their roast levels match.')
    if lock:Coffee.objects.select_for_update().get(pk=groups[0].coffee_id)
    recipe_query=GreenRecipe.objects.filter(coffee_id=groups[0].coffee_id)
    if lock:recipe_query=recipe_query.select_for_update()
    recipe=list(recipe_query.values('coffee_id','components','version'))
    # Approved recipe differences were blocked above. With the same physical
    # coffee the remaining effective recipe is the shared global recipe; a
    # missing stock recipe remains optional, as on the rest of the planner.
    if any(not r.green_oz.is_finite() or r.green_oz<=0 or r.green_oz!=r.green_oz.quantize(TENTH) for r in rows):
        raise ValidationError('Save each selected green weight in tenths of an ounce before combining.')
    total=sum((r.green_oz for r in rows),Decimal(0))
    from .planning import split_weights
    weights=split_weights(total,machine.capacity,machine.minimum)
    assert sum(weights)==total
    all_rows=list(PlannedBatch.objects.filter(group_id__in=ids).order_by('pk').values())
    lines=list(IncomingOrderLine.objects.filter(group_id__in=ids).order_by('pk').values())
    packing=list(PackingProgress.objects.filter(line__group_id__in=ids).order_by('pk').values())
    facts={'plan':[plan.pk,plan.version,plan.date,plan.estimated_loss_pct,plan.spillage_pct,plan.accepted_at],
           'selected':row_ids,'machine':[machine.pk,machine.active,machine.capacity,machine.minimum],
           'groups':list(RoastGroup.objects.filter(pk__in=ids).order_by('pk').values()),
           'rows':all_rows,'orders':lines,'packing':packing,'recipe':recipe,
           'coffee':list(Coffee.objects.filter(pk=groups[0].coffee_id).values('id','active','kind','experimental','standard_roast'))}
    fingerprint=hashlib.sha256(json.dumps(facts,default=str,sort_keys=True).encode()).hexdigest()
    loss=next(iter(profile))[3]
    retained=[r for r in all_rows if r['id'] not in row_ids]
    from .planning import profile_key
    key=profile_key(groups[0].coffee_id,groups[0].roast_level,groups[0].target_finish_temp_f,None)
    target=next((g for g in groups if g.key==key),groups[0])
    unchanged=len(groups)==1 and sorted((r.roaster_id,r.green_oz) for r in rows)==sorted((machine.pk,w) for w in weights)
    return {'plan':plan,'rows':rows,'row_ids':row_ids,'groups':groups,'target':target,'machine':machine,'weights':weights,'total':total,
            'loss':loss,'finished':total*(1-loss/100),'retained_count':len(retained),'retained_total':sum((r['green_oz'] for r in retained),Decimal(0)),
            'fingerprint':fingerprint,'unchanged':unchanged}


def confirm(plan,data,token,actor):
    try:sealed=signing.loads(token,salt=SALT,max_age=600)
    except signing.BadSignature:raise ValidationError('This preview expired or could not be verified. Make a new preview.')
    if sealed!={'plan':plan.pk,'version':plan.version,'actor':actor.pk,'fingerprint':data['fingerprint']}:
        raise ValidationError('The plan, drafts, orders, packing, recipe or capacity changed. Make a new preview before saving.')
    if data['unchanged']:return []
    target=data['target'];now=timezone.now()
    before=[{'id':r.pk,'group':r.group_id,'roaster':r.roaster_id,'green_oz':str(r.green_oz),'estimated_loss_pct':str(r.estimated_loss_pct) if r.estimated_loss_pct is not None else None,'yield_basis':r.yield_basis} for r in data['rows']]
    groups=[g.pk for g in data['groups']]
    lines=list(IncomingOrderLine.objects.filter(group_id__in=groups).select_related('product_coffee','product_label','group__coffee','group__label_variant').order_by('pk'))
    moved_lines=[]
    for line in lines:
        # Capture both inherited identities before setting product_coffee.
        coffee,label=line.ordered_coffee,line.ordered_label
        line.product_coffee=coffee;line.product_label=label;line.group=target
        line.save(update_fields=['product_coffee','product_label','group'])
        moved_lines.append(line.pk)
    retained_query=PlannedBatch.objects.filter(group_id__in=groups).exclude(pk__in=data['row_ids'])
    retained_rows=list(retained_query.order_by('pk').values_list('pk',flat=True))
    retained_query.update(group=target)
    target.label_variant=None;target.auto_batches=False
    target.save(update_fields=['label_variant','auto_batches'])
    PlannedBatch.objects.filter(pk__in=data['row_ids'],group__plan=plan).update(removed_at=now)
    created=[PlannedBatch.objects.create(group=target,roaster=data['machine'],green_oz=w) for w in data['weights']]
    from .plan_actions import mark_revised
    mark_revised(plan,actor)
    plan.version+=1;plan.save(update_fields=['version'])
    PlanEvent.objects.create(plan=plan,actor=actor,action='drafts_combined',details={'before':before,'after':[{'id':r.pk,'group':r.group_id,'roaster':r.roaster_id,'green_oz':str(r.green_oz)} for r in created],
        'selected_green_oz':str(data['total']),'retained_rows':retained_rows,'orders':moved_lines,'fingerprint':data['fingerprint'],'manual_sizing':True})
    return created


@staff_member_required
@require_http_methods(['GET','POST'])
def combine_batches(request,pk):
    plan=get_object_or_404(RoastPlan,pk=pk,historical=False,closed_at__isnull=True)
    form=CombineForm(request.POST or None,plan=plan,initial={'version':plan.version})
    context={'plan':plan,'form':form};status=200
    if request.method=='POST':
        if not form.is_valid():status=400
        else:
            try:
                with transaction.atomic():
                    plan=RoastPlan.objects.select_for_update().get(pk=pk)
                    if form.cleaned_data['version']!=plan.version:raise ValidationError('This plan changed. Reload it before combining drafts.')
                    data=preview(plan,form.cleaned_data['rows'],form.cleaned_data['roaster'],lock=True)
                    action=request.POST.get('action')
                    if action=='confirm':
                        created=confirm(plan,data,request.POST.get('preview_token',''),request.user)
                        messages.success(request,'Selected drafts combined and rebalanced. Review and accept the plan to return it to Today.' if created else 'These drafts are already balanced; nothing was changed.')
                        return redirect('/planning/?plan='+str(pk))
                    if action!='preview':raise ValidationError('Choose Preview before saving replacement loads.')
                    data['token']=signing.dumps({'plan':plan.pk,'version':plan.version,'actor':request.user.pk,'fingerprint':data['fingerprint']},salt=SALT,compress=True)
                    context.update(plan=plan,preview=data)
            except (ValidationError,Roaster.DoesNotExist) as error:
                form.add_error(None,'; '.join(error.messages) if isinstance(error,ValidationError) else 'The selected roaster changed. Reload and make a new preview.')
                status=400
    choices=[];reasons={}
    for row in PlannedBatch.objects.filter(group__plan=plan).select_related('group__coffee','roaster','group__label_variant').order_by('group__coffee__name','pk'):
        if row.group_id not in reasons:reasons[row.group_id]=group_block(row.group)
        choices.append({'row':row,'reason':reasons[row.group_id] or ('This draft already has a production record.' if row.batch_id else ''),'selected':str(row.pk) in request.POST.getlist('rows')})
    context['choices']=choices
    return render(request,'portal/combine_batches.html',context,status=status)
