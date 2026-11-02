"""Selected-draft replacement, preview integrity and production boundaries."""
def run_batch_combine_checks(client,user):
    import hashlib,json,time
    from unittest.mock import patch
    from decimal import Decimal as D
    from django.db import transaction
    from django.utils import timezone
    from django.test import Client
    from django.contrib.auth import get_user_model
    from portal.models import Coffee,LabelVariant,Roaster,RoastPlan,RoastGroup,IncomingOrderLine,PlannedBatch,PlanEvent,Batch,GreenRecipe,PackingProgress,RoastedStock,RoastedStockAllocation
    from portal.planning import profile_key
    def snapshot():
        return {m.__name__:list(getattr(m,'all_objects',m.objects).order_by('pk').values()) for m in (RoastPlan,RoastGroup,IncomingOrderLine,PlannedBatch,PlanEvent,Batch,PackingProgress,RoastedStock,RoastedStockAllocation)}
    with transaction.atomic():
        coffee=Coffee.objects.get(name='Demo Hearth')
        label=LabelVariant.objects.create(coffee=coffee,name='Fictional combine label')
        large=Roaster.objects.create(name='Combine large',max_green_oz=140)
        small=Roaster.objects.create(name='Combine small',max_green_oz=40)
        plan=RoastPlan.objects.create(created_by=user,accepted_by=user,accepted_at=timezone.now(),use_roasted_stock=False)
        a=RoastGroup.objects.create(plan=plan,key='old-combine-labeled',coffee=coffee,roast_level='Medium',label_variant=label)
        b=RoastGroup.objects.create(plan=plan,key=profile_key(coffee.pk,'Medium',None,None),coffee=coffee,roast_level='Medium')
        wholesale=IncomingOrderLine.objects.create(group=a,finished_oz=180,packaging=[{'size_oz':'12','bags':15}],grind='regular')
        retail=IncomingOrderLine.objects.create(group=b,product_coffee=coffee,finished_oz=D('18.5'),packaging=[{'size_oz':'16','bags':1},{'size_oz':'2.5','bags':1}],grind='whole')
        selected=[PlannedBatch.objects.create(group=a,roaster=large,green_oz=D('112.5')) for _ in range(2)]
        selected.append(PlannedBatch.objects.create(group=b,roaster=small,green_oz=D('23.3')))
        kept=PlannedBatch.objects.create(group=a,roaster=small,green_oz=20)
        kept_fields=PlannedBatch.objects.filter(pk=kept.pk).values().get()
        original_orders={line.pk:(line.finished_oz,line.packaging,line.grind,line.ordered_label.pk if line.ordered_label else None) for line in (wholesale,retail)}
        url=f'/plans/{plan.pk}/combine/'
        post={'version':plan.version,'rows':[str(r.pk) for r in selected],'roaster':large.pk,'action':'preview'}
        before=snapshot();response=client.get(url);assert response.status_code==200 and b'Preview combined loads' in response.content
        response=client.post(url,post);assert response.status_code==200,response.content
        data=response.context['preview'];assert data['weights']==[D('124.2'),D('124.1')] and data['total']==D('248.3')
        assert data['retained_count']==1 and data['retained_total']==20
        assert snapshot()==before,'A preview changed production data'
        confirmation={**post,'action':'confirm','preview_token':data['token']}
        def denied(values):
            before=snapshot();r=client.post(url,values);assert r.status_code==400,r.content
            assert snapshot()==before,'Rejected confirmation wrote data'
        denied({**confirmation,'preview_token':data['token']+'x'})
        with patch('django.core.signing.time.time',return_value=time.time()+601):denied(confirmation)
        denied({**confirmation,'rows':post['rows']+[str(kept.pk)]})
        large.max_green_oz=130;large.save();denied(confirmation);large.max_green_oz=140;large.save()
        retail.grind='regular';retail.save(update_fields=['grind']);denied(confirmation);retail.grind='whole';retail.save(update_fields=['grind'])
        recipe=GreenRecipe.objects.create(coffee=coffee,components=[],updated_by=user);denied(confirmation);recipe.delete()
        progress=PackingProgress.objects.create(line=retail);denied(confirmation);progress.delete()
        other=get_user_model().objects.create_user('combine-other-staff',password='Synthetic-only-168!',is_staff=True)
        other_client=Client(HTTP_HOST='localhost');other_client.force_login(other)
        before=snapshot();assert other_client.post(url,confirmation).status_code==400 and snapshot()==before
        public=Client(HTTP_HOST='localhost');assert public.get(url).status_code==302
        plain=get_user_model().objects.create_user('combine-nonstaff',password='Synthetic-only-426!')
        public.force_login(plain);assert public.post(url,post).status_code==302
        csrf=Client(HTTP_HOST='localhost',enforce_csrf_checks=True);csrf.force_login(user);assert csrf.post(url,post).status_code==403
        csrf.get(url)
        assert csrf.post(url,{**post,'csrfmiddlewaretoken':csrf.cookies['csrftoken'].value}).status_code==200
        outside=RoastPlan.objects.create(created_by=user)
        outside_group=RoastGroup.objects.create(plan=outside,key='outside-plan',coffee=coffee,roast_level='Medium')
        outside_row=PlannedBatch.objects.create(group=outside_group,roaster=small,green_oz=20)
        denied({**post,'rows':[post['rows'][0],str(outside_row.pk)]})
        # Confirm exactly once, preserving the unselected load and each sold product.
        result=client.post(url,confirmation);assert result.status_code==302,result.content
        plan.refresh_from_db();assert plan.version==1 and plan.accepted_at is None
        actual=list(PlannedBatch.objects.filter(group__plan=plan).exclude(pk=kept.pk).order_by('pk'))
        assert [(r.roaster_id,r.green_oz) for r in actual]==[(large.pk,D('124.2')),(large.pk,D('124.1'))]
        kept.refresh_from_db();after=PlannedBatch.objects.filter(pk=kept.pk).values().get()
        assert {k:v for k,v in after.items() if k!='group_id'}=={k:v for k,v in kept_fields.items() if k!='group_id'}
        assert kept.group_id==b.pk and not RoastGroup.objects.get(pk=b.pk).auto_batches
        for pk,expected in original_orders.items():
            line=IncomingOrderLine.objects.get(pk=pk)
            assert (line.finished_oz,line.packaging,line.grind,line.ordered_label.pk if line.ordered_label else None)==expected
            assert line.group_id==b.pk
        assert PlannedBatch.all_objects.filter(pk__in=[r.pk for r in selected],removed_at__isnull=False).count()==3
        event=plan.events.get(action='drafts_combined');assert event.details['retained_rows']==[kept.pk] and len(event.details['orders'])==2
        denied(confirmation)
        # Already balanced selections are a true no-op, not a duplicate history entry.
        balanced={'version':plan.version,'rows':[str(r.pk) for r in actual],'roaster':large.pk,'action':'preview'}
        r=client.post(url,balanced);assert r.status_code==200 and r.context['preview']['unchanged']
        before=snapshot();r=client.post(url,{**balanced,'action':'confirm','preview_token':r.context['preview']['token']})
        assert r.status_code==302 and snapshot()==before
        # Distinct physical profiles and protected work never reach a valid preview.
        def reject_pair(group,second):
            values={'version':plan.version,'rows':[str(actual[0].pk),str(second.pk)],'roaster':large.pk,'action':'preview'}
            before=snapshot();r=client.post(url,values);assert r.status_code==400,r.content;assert snapshot()==before
        different=Coffee.objects.create(name='Fictional distinct medium',kind='blend',standard_roast='Medium')
        g=RoastGroup.objects.create(plan=plan,key='different-coffee',coffee=different,roast_level='Medium')
        IncomingOrderLine.objects.create(group=g,product_coffee=different,finished_oz=16)
        extra=PlannedBatch.objects.create(group=g,roaster=small,green_oz=20);reject_pair(g,extra)
        g=RoastGroup.objects.create(plan=plan,key='different-loss',coffee=coffee,roast_level='Medium',loss_override=15)
        IncomingOrderLine.objects.create(group=g,product_coffee=coffee,finished_oz=16)
        extra=PlannedBatch.objects.create(group=g,roaster=small,green_oz=20);reject_pair(g,extra)
        # A different temperature/roast is rejected even if the coffee matches.
        g.target_finish_temp_f=410;g.loss_override=None;g.save();reject_pair(g,extra)
        g.target_finish_temp_f=None;g.roast_level='French';g.save();reject_pair(g,extra)
        # A green-origin decision, used bulk stock, packing or any physical record protects its group.
        def base_preview():return {'version':plan.version,'rows':[str(actual[0].pk),str(actual[1].pk)],'roaster':large.pk,'action':'preview'}
        for action in ('green_request','green_approve'):
            approval=PlanEvent.objects.create(plan=plan,actor=user,action=action,details={'group':b.pk,'parts':{'1':'100'}})
            denied(base_preview());approval.delete()
        stock=RoastedStock.objects.create(coffee=coffee,roast_level='Medium',remaining_oz=0,recorded_by=user)
        used=RoastedStockAllocation.objects.create(stock=stock,line=retail,amount_oz=1,status='used');denied(base_preview());used.delete()
        progress=PackingProgress.objects.create(line=retail,bagged_at=timezone.now());denied(base_preview());progress.delete()
        physical=Batch.objects.create(date=plan.date,operator=user,roaster=small,coffee=coffee,roast_level='Medium',green_oz=20,measured_at=timezone.now())
        kept.batch=physical;kept.save();denied(base_preview())
        plan.closed_at=timezone.now();plan.save();assert client.get(url).status_code==404
        transaction.set_rollback(True)
    print('PASS: read-only merge previews, selected totals/capacity, inherited labels, retained loads, manual sizing/audit, no-op/replay/stale/CSRF/role protection and recipe/stock/packing/started boundaries.')
