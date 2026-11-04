"""Fictional live-load corrections and early subscription demand, rolled back."""
def run_roast_day_checks(client,user):
    import copy,json
    from datetime import timedelta
    from decimal import Decimal
    from django.db import transaction
    from django.utils import timezone
    from django.test import Client
    from django.core.exceptions import ValidationError
    from portal.models import Coffee,Roaster,RoastPlan,RoastGroup,IncomingOrderLine,PlannedBatch,Batch,GreenBeanItem,GreenRecipe,GreenMovement,SubscriptionContract,SubscriptionCycle,ImportOrder,PlanEvent
    from portal.load_override import override_stamp
    from portal.order_import import infer_item,source_signature,readiness,add_selected
    from portal.subscription_planning import schedule_token,forecast_hold,renewal_review_needed
    with transaction.atomic():
        coffee=Coffee.objects.get(name='Demo Hearth')
        machine=Roaster.objects.create(name='Fixture override roaster',max_green_oz=140,min_green_oz=41)
        plan=RoastPlan.objects.create(created_by=user,accepted_at=timezone.now(),accepted_by=user)
        group=RoastGroup.objects.create(plan=plan,coffee=coffee,roast_level='Medium',key='fixture-override')
        IncomingOrderLine.objects.create(group=group,product_coffee=coffee,finished_oz=64,grind='whole',packaging=[{'size_oz':'16','bags':4}])
        origin=GreenBeanItem.objects.create(name='Fixture correction origin',remaining_oz=1000,recorded_by=user)
        GreenRecipe.objects.create(coffee=coffee,components=[{'item':str(origin.pk),'percent':'100'}],updated_by=user)
        batch=Batch.objects.create(date=plan.date,operator=user,roaster=machine,coffee=coffee,planned_group=group,roast_level='Medium',green_oz=80,measured_at=timezone.now())
        row=PlannedBatch.objects.create(group=group,roaster=machine,green_oz=80,batch=batch)
        origin.refresh_from_db();assert origin.remaining_oz==920
        row=PlannedBatch.objects.select_related('group__plan','roaster','batch').get(pk=row.pk)
        token=override_stamp(row);url=f'/planned-loads/{row.pk}/override/'
        assert client.get(url).status_code==200
        response=client.post(url,{'revision':token,'green_oz':'144.0','reason':'Correct the actual weighed input','confirmed':'on'})
        assert response.status_code==302,response.content
        row.refresh_from_db();batch.refresh_from_db();plan.refresh_from_db();group.refresh_from_db();origin.refresh_from_db()
        assert batch.green_oz==row.green_oz==Decimal('144.0') and batch.has_green_override and plan.accepted_at and not group.auto_batches
        assert batch.measured_at and not batch.roasted_at and batch.roasted_oz is None and origin.remaining_oz==856
        movements=GreenMovement.objects.filter(batch=batch).count();assert movements==2
        assert client.post(url,{'revision':token,'green_oz':'144.0','reason':'Replay stale correction','confirmed':'on'}).status_code==409
        assert GreenMovement.objects.filter(batch=batch).count()==movements
        batch.roasted_oz=120;batch.roasted_at=timezone.now();batch.cooled_at=timezone.now();batch.save()
        row=PlannedBatch.objects.select_related('group__plan','roaster','batch').get(pk=row.pk)
        assert client.post(url,{'revision':override_stamp(row),'green_oz':'119.0','reason':'Invalid below actual finished weight','confirmed':'on'}).status_code==409
        batch.refresh_from_db();assert batch.green_oz==144 and batch.roasted_oz==120 and batch.cooled_at
        row.green_oz=145
        try:row.full_clean()
        except ValidationError:pass
        else:raise AssertionError('An exact-weight override authorized another quantity')
        assert Client().post(url,{}).status_code==302
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(user);assert csrf.post(url,{}).status_code==403
        assert PlanEvent.objects.filter(plan=plan,action='load_override').count()==1
        transaction.set_rollback(True)
    with transaction.atomic():
        plan=RoastPlan.objects.create(created_by=user)
        fixed=infer_item('Demo Hearth - 16 oz / Whole bean',2);fixed.update(finished_oz='32',needs_cycle_assignment=False)
        assortment=infer_item('Monthly Coffee Subscription - Whole Bean / Light to Medium / 2 lbs',1);assortment.update(finished_oz='32',needs_cycle_assignment=True)
        due=timezone.now()+timedelta(days=2)
        contract=SubscriptionContract.objects.create(external_id='fixture-four-day',customer='Fictional customer',status='ACTIVE',next_billing_at=due,lines=[assortment])
        far=SubscriptionContract.objects.create(external_id='fixture-later',status='ACTIVE',next_billing_at=due+timedelta(days=4),lines=[fixed])
        url=f'/plans/{plan.pk}/subscriptions/'
        response=client.get(url);assert response.status_code==200 and b'fixture-four-day' in response.content and b'fixture-later' not in response.content
        post={'version':plan.version,'contract':contract.pk,'schedule':schedule_token(contract,plan),'confirmed':'on'}
        assert client.post(url,post).status_code==302
        cycle=SubscriptionCycle.objects.get(contract=contract);order=cycle.forecast_order
        assert order.financial_status=='scheduled' and not order.imported_at and not order.lines[0]['coffee']
        assert not readiness(order)[0] and not IncomingOrderLine.objects.exists()
        assert client.post(url,post).status_code==302 and SubscriptionCycle.objects.count()==1
        assert client.get(f'/imports/{order.pk}/review/').status_code==200
        # Choose each assortment for this delivery using the ordinary saved allocation form.
        from portal.allocations import review_token,save_allocations
        coffee=Coffee.objects.get(name='Demo Hearth')
        save_allocations(order,[{'source':'1','coffee':coffee.pk,'finished_oz':'32','bag_size_oz':'16','roast':'Medium','grind':'whole'}],review_token(order),user)
        assert readiness(order)[0],readiness(order)
        other=RoastPlan.objects.create(created_by=user)
        try:add_selected(other,[order.pk],user)
        except ValidationError:pass
        else:raise AssertionError('Early delivery moved silently to a different plan')
        add_selected(plan,[order.pk],user);order.refresh_from_db();plan.refresh_from_db()
        demand=list(IncomingOrderLine.objects.values('pk','group_id','finished_oz','packaging'))
        assert sum(x['finished_oz'] for x in demand)==32
        actual=ImportOrder.objects.create(external_id='fixture-real-renewal',reference='#FIXTURE-RENEWAL',customer=contract.customer,received_at=due,financial_status='paid',fulfillment_status='unfulfilled',subscription='recurring',lines=copy.deepcopy(order.lines),source_signature=order.source_signature)
        assert renewal_review_needed(actual) and not readiness(actual)[0]
        review=f'/subscriptions/renewals/{actual.pk}/';response=client.get(review);assert response.status_code==200
        token=response.context['revision']
        assert client.post(review,{'revision':token,'cycle':cycle.pk,'confirmed':'on'}).status_code==302
        cycle.refresh_from_db();assert cycle.renewal_order_id==actual.pk and 'Already covered' in readiness(actual)[1]
        assert list(IncomingOrderLine.objects.values('pk','group_id','finished_oz','packaging'))==demand and not forecast_hold(order)
        # An ordinary shipping update is not another production order.
        actual.fulfillment_status='fulfilled';actual.lines[0]['fulfilled']=True;actual.save()
        assert not forecast_hold(order) and not readiness(actual)[0]
        actual.financial_status='refunded';actual.save();assert 'unpaid' in forecast_hold(order)
        assert Client(enforce_csrf_checks=True).post(url,post).status_code==403
        assert not Batch.objects.exists()
        transaction.set_rollback(True)
    with transaction.atomic():
        from portal.models import WholesaleCustomer,WholesaleOrder
        from portal.wholesale import ItemForm,HeaderForm
        from portal.planning import IncomingForm
        first=WholesaleCustomer.objects.create(name='Fixture Cafe',name_key='fixture cafe',updated_by=user)
        other=WholesaleCustomer.objects.create(name='Fixture Gym',name_key='fixture gym',updated_by=user)
        exclusive=Coffee.objects.create(name='Fixture exclusive blend',kind='blend',standard_roast='Medium/Dark',wholesale_only_customer=first)
        data={'coffee':exclusive.pk,'size':'12','count':'2','grind':'whole'}
        assert ItemForm(data,wholesale_customer=first).is_valid()
        assert not ItemForm(data,wholesale_customer=other).is_valid() and not ItemForm(data).is_valid()
        assert not IncomingForm({'coffee':exclusive.pk,'extra_oz':'24','roast_level':'Medium/Dark'}).is_valid()
        assert not HeaderForm({'account':first.pk,'customer':other.name,'plan':'new','plan_date':timezone.localdate()},plans=[]).is_valid()
        response=client.get('/wholesale/',{'customer':first.pk});assert response.status_code==200 and response.context['header'].initial['account']==first.pk
        response=client.post('/wholesale/accounts/',{'name':'Fixture Bookshop','default_grind':'whole','active':'on','notes':'Use the side entrance'})
        assert response.status_code==302
        account=WholesaleCustomer.objects.get(name_key='fixture bookshop');assert account.notes=='Use the side entrance'
        assert not WholesaleOrder.objects.exists() and not RoastPlan.objects.exists()
        assert client.post('/wholesale/accounts/',{'name':' fixture BOOKSHOP ','default_grind':'whole','active':'on'}).status_code==409
        assert WholesaleCustomer.objects.count()==3
        first.active=False;first.save()
        assert not ItemForm(data,wholesale_customer=first).is_valid()
        transaction.set_rollback(True)
    print('PASS: exact active-load override, inventory delta/replay/stale/CSRF guards, preserved results, four-day subscription choices/renewal deduplication, saved wholesale accounts and enforced exclusive products.')
