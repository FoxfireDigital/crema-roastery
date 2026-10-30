"""Synthetic optional checks and plan-scoped ingredient substitution regressions."""
def run_green_checks(client,user):
    from decimal import Decimal
    from django.db import transaction
    from django.utils import timezone
    from django.test import Client
    from portal.models import Coffee,GreenBeanItem,GreenBeanDetails,GreenRecipe,GreenMovement,GreenBatchUsage,RoastPlan,ImportOrder,IncomingOrderLine,PlannedBatch,PlanEvent,Batch
    from portal.order_import import infer_item,source_signature,add_selected
    from portal.green_review import review_context,parts_for_group
    from portal.roast_sheet import row_token
    from portal.green_forecast import accepted_loads
    with transaction.atomic():
        coffee=Coffee.objects.get(name='Demo Hearth')
        order_item=infer_item('Demo Hearth - 16 oz / Whole bean',1,use_saved=False)
        order_item.update(line_key='1',source_line='1',source_total='16',fulfilled=False)
        order=ImportOrder.objects.create(external_id='green-fixture-1',reference='#GREEN-FIXTURE',received_at=timezone.now(),financial_status='paid',fulfillment_status='unfulfilled',lines=[order_item],source_signature=source_signature([order_item],''))
        plan=RoastPlan.objects.create(created_by=user);add_selected(plan,[order.pk],user)
        plan.accepted_at=timezone.now();plan.accepted_by=user;plan.save()
        row=PlannedBatch.objects.select_related('group__plan','group__coffee','batch','roaster').get(group__plan=plan)
        url=f'/plans/{plan.pk}/green-review/'
        initial=review_context(plan);assert initial['gaps'] and initial['state']=='not_checked'
        assert client.post(url,{'action':'skip','review_token':initial['token']}).status_code==302
        assert review_context(plan)['state']=='skipped' and not GreenMovement.objects.exists() and not Batch.objects.exists()
        plan.refresh_from_db();assert plan.accepted_at
        assert b'Skipped' in client.get('/planning/',{'plan':plan.pk}).content
        origins={}
        for name,balance,roasts,flavors,caffeine in [
            ('Fixture source',0,['Medium'],'cocoa, almond','regular'),
            ('Fixture supporting origin',100,['Medium'],'nuts','regular'),
            ('Fixture best replacement',100,['Medium'],'cocoa, almond','regular'),
            ('Fixture exact roast different flavor',100,['Medium'],'floral','regular'),
            ('Fixture nearby roast exact flavor',100,['Dark'],'cocoa, almond','regular'),
            ('Fixture incompatible decaf',100,['Medium'],'cocoa, almond','decaf'),
            ('Fixture insufficient lot',1,['Medium'],'cocoa, almond','regular'),
        ]:
            item=GreenBeanItem.objects.create(name=name,remaining_oz=balance,recorded_by=user)
            GreenBeanDetails.objects.create(item=item,roast_levels=roasts,flavor_tags=flavors,caffeine=caffeine,updated_by=user)
            origins[name]=item
        source=origins['Fixture source'];support=origins['Fixture supporting origin'];best=origins['Fixture best replacement']
        recipe=GreenRecipe.objects.create(coffee=coffee,components=[{'item':source.pk,'percent':'70'},{'item':support.pk,'percent':'30'}],updated_by=user)
        context=review_context(plan);assert context['state']=='not_checked' and context['shortages']
        group=context['groups'][0];short=next(s for s in group['shortages'] if s['source'].pk==source.pk)
        choices=[c['item'].pk for c in short['candidates']]
        assert choices.index(best.pk)<choices.index(origins['Fixture exact roast different flavor'].pk)<choices.index(origins['Fixture nearby roast exact flavor'].pk)
        assert origins['Fixture incompatible decaf'].pk not in choices and origins['Fixture insufficient lot'].pk not in choices
        assert client.post(url,{'action':'check','review_token':context['token']}).status_code==302
        assert review_context(plan)['state']=='needs_review'  # A warning never becomes a fabricated pass.
        def request():
            c=review_context(plan)
            response=client.post(url,{'action':'request','review_token':c['token'],'group':row.group_id,'source':source.pk,'replacement':best.pk})
            assert response.status_code==302,response.content
            return PlanEvent.objects.filter(plan=plan,action='green_request').first()
        pending=request();assert parts_for_group(row.group)=={str(source.pk):'70',str(support.pk):'30'}
        unchanged=list(GreenBeanItem.objects.order_by('pk').values_list('remaining_oz',flat=True))
        c=review_context(plan)
        assert client.post(url,{'action':'approve','request':pending.pk,'review_token':c['token']}).status_code==409
        # A fresh count after requesting invalidates approval, even if enough stock remains.
        best.remaining_oz=99;best.version+=1;best.save()
        assert client.post(url,{'action':'approve','request':pending.pk,'review_token':c['token'],'confirmed':'on'}).status_code==409
        c=review_context(plan)
        assert client.post(url,{'action':'approve','request':pending.pk,'review_token':c['token'],'confirmed':'on'}).status_code==409
        assert client.post(url,{'action':'decline','request':pending.pk,'review_token':c['token']}).status_code==302
        pending=request();c=review_context(plan);old_token=c['token'];old_version=plan.version
        response=client.post(url,{'action':'approve','request':pending.pk,'review_token':old_token,'confirmed':'on'});assert response.status_code==302,response.content
        plan.refresh_from_db();assert plan.accepted_at and plan.version==old_version+1
        assert client.post(url,{'action':'approve','request':pending.pk,'review_token':old_token,'confirmed':'on'}).status_code==409
        assert parts_for_group(row.group)=={str(support.pk):'30',str(best.pk):'70'}
        recipe.refresh_from_db();assert recipe.components==[{'item':source.pk,'percent':'70'},{'item':support.pk,'percent':'30'}]
        assert not GreenMovement.objects.exists()  # Approval neither reserves nor deducts green beans.
        totals,_,_=accepted_loads();assert totals[source.pk]==0 and totals[best.pk]==Decimal('14.0')
        row=PlannedBatch.objects.select_related('group__plan','group__coffee','batch','roaster').get(pk=row.pk)
        response=client.post(f'/roasts/{row.pk}/',{'revision':row_token(row),'measured_at':'on'});assert response.status_code==200,response.content
        row.refresh_from_db();usage=GreenBatchUsage.objects.get(batch=row.batch)
        assert usage.percentages=={str(support.pk):'30',str(best.pk):'70'}
        source.refresh_from_db();best.refresh_from_db();support.refresh_from_db()
        assert source.remaining_oz==0 and best.remaining_oz==85 and support.remaining_oz==94
        before=list(GreenMovement.objects.values())
        # Add an unstarted load so cancelling affects only future work in this group.
        extra=PlannedBatch.objects.create(group=row.group,roaster=row.roaster,green_oz=10)
        c=review_context(plan)
        assert client.post(url,{'action':'cancel','review_token':c['token'],'group':row.group_id}).status_code==302
        usage.refresh_from_db();assert usage.percentages[str(best.pk)]=='70' and before==list(GreenMovement.objects.values())
        assert parts_for_group(row.group)=={str(source.pk):'70',str(support.pk):'30'}
        line=IncomingOrderLine.objects.get(group=row.group);assert line.product_coffee_id==coffee.pk and row.group.coffee_id==coffee.pk
        assert Client(HTTP_HOST='localhost').post(url,{}).status_code==302
        secure=Client(HTTP_HOST='localhost',enforce_csrf_checks=True);secure.force_login(user);assert secure.post(url,{}).status_code==403
        plan.closed_at=timezone.now();plan.save(update_fields=['closed_at'])
        assert client.post(url,{'action':'skip','review_token':review_context(plan)['token']}).status_code==404
        transaction.set_rollback(True)
    print('PASS: optional green checks/skip, explicit requests/approval, roast-first/flavor-second ranking, caffeine/quantity guards, stale protection, plan-only recipes, exact measured deductions and frozen history.')
