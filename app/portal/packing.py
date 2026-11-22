from decimal import Decimal,InvalidOperation
import hashlib,json,math
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404,render,redirect
from django.views.decorators.http import require_POST
from .models import IncomingOrderLine,RoastPlan,PackingEvent,GRIND_CHOICES,PackingProgress,PackingProgressEvent

PROGRESS_STEPS=(('labeled_at','Labeled'),('flavored_at','Flavored'),('ground_at','Ground'),
                ('bagged_at','Bagged'),('sealed_at','Sealed'))

def progress_state(progress):return {key:getattr(progress,key).isoformat() if progress and getattr(progress,key) else None for key,_ in PROGRESS_STEPS}

def progress_token(line,progress):
    return hashlib.sha256(json.dumps([packing_token(line),progress.version if progress else None,progress_state(progress),PROGRESS_STEPS],sort_keys=True).encode()).hexdigest()

def applicable_steps(line):
    return [step for step in PROGRESS_STEPS
            if (step[0]!='flavored_at' or line.ordered_coffee.kind=='flavored')
            and (step[0]!='ground_at' or line.grind!='whole')]

def progress_result(line,progress):
    event=progress.events.order_by('-pk').first() if progress else None
    undo=event.pk if event and not event.undoes_id and not PackingProgressEvent.objects.filter(undoes=event).exists() and event.after==progress_state(progress) else None
    return {'revision':progress_token(line,progress),'steps':{k:bool(v) for k,v in progress_state(progress).items()},'undo_event':undo}


def packing_token(line):
    return hashlib.sha256(json.dumps([line.pk,str(line.finished_oz),line.group_id,line.group.plan.version,line.product_coffee_id,line.product_label_id,line.grind,line.packaging],sort_keys=True).encode()).hexdigest()


class PackingForm(forms.Form):
    revision=forms.CharField(widget=forms.HiddenInput)
    grind=forms.ChoiceField(choices=GRIND_CHOICES,label='Grind')
    size_oz=forms.DecimalField(max_digits=10,decimal_places=2,min_value=Decimal('.01'),required=False,label='Bag size (oz)')
    bags=forms.IntegerField(min_value=1,max_value=10000,required=False,label='Number of bags')
    per_sheet=forms.ChoiceField(choices=[('','Choose layout'),('4','4 labels / sheet'),('8','8 labels / sheet — fracs')],required=False,label='Label layout')
    def __init__(self,*args,line,**kwargs):
        kwargs.setdefault('auto_id',f'packing-{line.pk}-%s')
        super().__init__(*args,**kwargs);self.line=line
    def clean(self):
        data=super().clean();size=data.get('size_oz');bags=data.get('bags')
        if size is not None or bags is not None:
            if size is None or bags is None:raise forms.ValidationError('Enter both the bag size and bag count.')
            if size*bags!=self.line.finished_oz:raise forms.ValidationError('Bag size × bag count must equal the ordered finished ounces. This changes packaging, not the amount ordered.')
        return data


@login_required
def packing_list(request):
    archived=request.GET.get('archived')=='1'
    from django.db.models import Q
    archive_plans=RoastPlan.all_objects.filter(Q(removed_at__isnull=False)|Q(closed_at__isnull=False),historical=False)
    plans=archive_plans[:100] if archived else RoastPlan.objects.all()[:100]
    plan=get_object_or_404(RoastPlan.all_objects,pk=request.GET['plan']) if request.GET.get('plan') else (plans.first() if archived else RoastPlan.objects.filter(accepted_at__isnull=False).first() or RoastPlan.objects.first())
    if plan and plan.removed_at and not archived:archived=True;plans=RoastPlan.all_objects.filter(removed_at__isnull=False)[:100]
    if plan and plan.closed_at:archived=True;plans=[plan]+list(archive_plans.exclude(pk=plan.pk)[:99])
    from .finished_coverage import plan_coverage
    return render(request,'portal/packing.html',{**packing_context(plan,request.GET.get('group','order')),'coverage':plan_coverage(plan) if plan else None,'plans':plans,'archived':archived})


def packing_context(plan,group_by='order'):
    """One checklist model for Today and Bagging; no copied progress records."""
    lines=IncomingOrderLine.objects.filter(group__plan=plan).select_related('group__plan','group__coffee','group__label_variant','product_coffee','product_label') if plan else []
    rows=[];totals={};needs_review=0
    progresses={p.line_id:p for p in PackingProgress.objects.filter(line__group__plan=plan)} if plan else {}
    for line in lines:
        packages=[];accounted=Decimal(0);bags_total=0
        for item in line.packaging:
            try:size=Decimal(str(item['size_oz']));bags=int(item['bags'])
            except (KeyError,ValueError,TypeError,InvalidOperation):continue
            if not size.is_finite() or size<=0 or bags<=0:continue
            layout=item.get('per_sheet') or (4 if size in [12,16,80] else None)
            packages.append({'size':size,'bags':bags,'layout':layout});accounted+=size*bags;bags_total+=bags
        confirmed=accounted==line.finished_oz and bool(packages)
        if confirmed:
            for pack in packages:
                key=(line.ordered_coffee.name,line.ordered_label.name if line.ordered_label else 'Standard label',format(pack['size'].normalize(),'f'),line.get_grind_display(),pack['layout'])
                totals[key]=totals.get(key,0)+pack['bags']
        if not confirmed or line.grind in ['unknown','ground']:needs_review+=1
        initial={'revision':packing_token(line),'grind':line.grind}
        if len(packages)==1:initial.update(size_oz=packages[0]['size'],bags=packages[0]['bags'],per_sheet=str(packages[0]['layout'] or ''))
        steps=['Apply the finished-product label']
        if line.ordered_coffee.kind=='flavored':steps.append('Flavor as '+line.ordered_coffee.name)
        steps.append('Keep whole bean' if line.grind=='whole' else 'Grind '+line.get_grind_display().replace('Ground — ','') if line.grind in ['regular','fine','coarse'] else 'Confirm grind before bagging')
        steps.extend(['Weigh and bag','Seal'])
        progress=progresses.get(line.pk);result=progress_result(line,progress)
        bulk_sources=[{'coffee':a.stock.coffee.name,'amount':a.amount_oz,'status':a.status} for a in line.stock_allocations.filter(status__in=['reserved','used']).select_related('stock__coffee')]
        rows.append({'line':line,'bulk_sources':bulk_sources,'packages':packages,'confirmed':confirmed,'bags':bags_total,'steps':steps,'form':PackingForm(line=line,initial=initial),'progress':progress,'progress_revision':result['revision'],'undo_event':result['undo_event'],'progress_steps':[{'key':key,'label':label,'done':bool(progress and getattr(progress,key))} for key,label in applicable_steps(line)]})
    labels=[{'coffee':key[0],'label':key[1],'size':key[2],'grind':key[3],'layout':key[4],'bags':count,'sheets':math.ceil(count/key[4]) if key[4] else None} for key,count in sorted(totals.items(),key=lambda item:tuple(str(x) for x in item[0]))]
    if group_by not in ['order','coffee']:group_by='order'
    rows.sort(key=lambda item:((item['line'].ordered_coffee.name,item['line'].reference,item['line'].pk) if group_by=='coffee' else (item['line'].customer,item['line'].reference,item['line'].ordered_coffee.name,item['line'].pk)))
    sections=[]
    for item in rows:
        name=item['line'].ordered_coffee.name if group_by=='coffee' else (item['line'].customer+' · ' if item['line'].customer else '')+(item['line'].reference or 'Stock / unnumbered')
        if not sections or sections[-1]['name']!=name:sections.append({'name':name,'rows':[]})
        sections[-1]['rows'].append(item)
    return {'plan':plan,'rows':rows,'sections':sections,'group_by':group_by,'labels':labels,'needs_review':needs_review,'completed':sum(bool(row['progress'] and row['progress'].sealed_at) for row in rows)}



@login_required
@require_POST
def save_progress(request,pk):
    from django.http import JsonResponse
    from django.core.exceptions import ValidationError
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime
    initial=get_object_or_404(IncomingOrderLine.objects.select_related('group'),pk=pk)
    try:
        with transaction.atomic():
            plan=get_object_or_404(RoastPlan.objects.select_for_update(),pk=initial.group.plan_id)
            line=get_object_or_404(IncomingOrderLine.objects.select_for_update(of=('self',)).select_related('group__plan','group__coffee','product_coffee'),pk=pk)
            progress=PackingProgress.objects.select_for_update().filter(line=line).first()
            if request.POST.get('revision')!=progress_token(line,progress):return JsonResponse({'error':'This packing list changed. Reload before saving.'},status=409)
            before=progress_state(progress)
            if request.POST.get('action')=='undo':
                last=progress_result(line,progress)['undo_event']
                if not last or str(last)!=request.POST.get('event'):raise ValidationError('This packing change can no longer be undone. Review the current list.')
                old=PackingProgressEvent.objects.get(pk=last)
                if not request.user.is_staff and old.actor_id!=request.user.pk:raise ValidationError('Only the person who made this change or an administrator can undo it.')
                for key,value in old.before.items():setattr(progress,key,parse_datetime(value) if value else None)
                progress.version+=1;progress.save();PackingProgressEvent.objects.create(progress=progress,actor=request.user,before=before,after=progress_state(progress),undoes=old)
            else:
                if not plan.accepted_at:raise ValidationError('Accept this plan before recording its bagging checklist.')
                accounted=Decimal(0)
                try:
                    for item in line.packaging:
                        size=Decimal(str(item['size_oz']));bags=int(item['bags'])
                        if not size.is_finite() or size<=0 or bags<=0:raise ValueError()
                        accounted+=size*bags
                except (KeyError,TypeError,ValueError,InvalidOperation):raise ValidationError('Confirm the package sizes before bagging.')
                if not line.packaging or accounted!=line.finished_oz or line.grind in ['unknown','ground']:raise ValidationError('Confirm the bag sizes and grind before recording bagging steps.')
                keys=[key for key,_ in applicable_steps(line)];checked={key:request.POST.get(key)=='on' for key in keys}
                if not checked['labeled_at'] and any(checked[key] for key in keys[1:]):
                    raise ValidationError('Mark the bags Labeled before recording the next packing step.')
                for previous,current in zip(keys,keys[1:]):
                    if checked[current] and not checked[previous]:raise ValidationError('Complete the preceding bagging steps first.')
                if not progress and not any(checked.values()):return JsonResponse(progress_result(line,None))
                progress=progress or PackingProgress(line=line);now=timezone.now()
                for key,_ in PROGRESS_STEPS:setattr(progress,key,(getattr(progress,key) or now) if checked.get(key) else None)
                after=progress_state(progress)
                if before!=after:
                    progress.version+=1;progress.save();PackingProgressEvent.objects.create(progress=progress,actor=request.user,before=before,after=after)
            return JsonResponse(progress_result(line,progress))
    except ValidationError as error:return JsonResponse({'error':'; '.join(error.messages)},status=400)


@staff_member_required
@require_POST
def save_packing(request,pk):
    return_today=request.POST.get('return_to')=='today'
    initial=get_object_or_404(IncomingOrderLine.objects,pk=pk,group__plan__removed_at__isnull=True,group__plan__historical=False,group__plan__closed_at__isnull=True)
    with transaction.atomic():
        plan=RoastPlan.objects.select_for_update().get(pk=initial.group.plan_id)
        line=get_object_or_404(IncomingOrderLine.objects.select_for_update(of=('self',)).select_related('group__plan','group__coffee','product_coffee','product_label'),pk=pk)
        form=PackingForm(request.POST,line=line)
        if request.POST.get('revision')!=packing_token(line):messages.error(request,'This bagging row changed. Review the latest details before saving.')
        elif not form.is_valid():messages.error(request,'; '.join(str(error) for errors in form.errors.values() for error in errors))
        else:
            before={'grind':line.grind,'packaging':line.packaging};data=form.cleaned_data
            line.grind=data['grind']
            if data.get('size_oz') is not None:
                line.packaging=[{'size_oz':str(data['size_oz']),'bags':data['bags'],'per_sheet':int(data['per_sheet']) if data.get('per_sheet') else None}]
            progress=PackingProgress.objects.filter(line=line).first()
            if progress and any(progress_state(progress).values()) and before!={'grind':line.grind,'packaging':line.packaging}:
                messages.error(request,'Clear the packing checklist before changing its grind or bag sizes. The existing instructions were preserved.')
                return redirect('/#packing-plan-'+str(plan.pk) if return_today else '/packing/?plan='+str(plan.pk))
            line.save(update_fields=['grind','packaging'])
            after={'grind':line.grind,'packaging':line.packaging}
            if before!=after:PackingEvent.objects.create(line=line,actor=request.user,before=before,after=after)
            messages.success(request,'Bagging details saved. The roast amount and ordered flavor are unchanged.')
    return redirect('/#packing-plan-'+str(plan.pk) if return_today else '/packing/?plan='+str(plan.pk))
