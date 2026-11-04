"""Configured green minima across automatic, manual and production entry paths."""
def run_minimum_load_checks(client,user):
    from decimal import Decimal as D
    from django.db import transaction
    from django.core.exceptions import ValidationError
    from django.utils import timezone
    from portal.models import Roaster,Coffee,RoastPlan,RoastGroup,IncomingOrderLine,PlannedBatch,Batch,PlanEvent
    from portal.planning import split_weights,summary
    from portal.autobatches import sync_group
    from portal.artisan_profiles import usable_row,row_fingerprint
    from portal.roast_sheet import row_token
    from portal.views import BatchForm
    def rejected(fn):
        try:fn()
        except ValidationError:return
        raise AssertionError('Invalid minimum load accepted')
    with transaction.atomic():
        small=Roaster.objects.create(name='Minimum small',max_green_oz=40,min_green_oz=8)
        large=Roaster.objects.create(name='Minimum large',max_green_oz=140,min_green_oz=41)
        # Isolate machine selection from the demo or private installation's machines.
        Roaster.objects.exclude(pk__in=[small.pk,large.pk]).update(active=False)
        coffee=Coffee.objects.get(name='Demo Hearth')
        rejected(lambda:Roaster(name='Bad minimum',max_green_oz=40,min_green_oz=41).full_clean())
        rejected(lambda:Roaster(name='Negative minimum',max_green_oz=40,min_green_oz=-1).full_clean())
        rejected(lambda:Roaster(name='Fraction minimum',max_green_oz=40,min_green_oz=D('8.01')).full_clean())
        assert split_weights(D('248.3'),140,41)==[D('124.2'),D('124.1')]
        assert split_weights(0,40,8,allow_extra=True)==[]
        rejected(lambda:split_weights(4,40,8));assert split_weights(4,40,8,allow_extra=True)==[8]
        rejected(lambda:split_weights(D('15.9'),8,8));assert split_weights(D('15.9'),8,8,allow_extra=True)==[8,8]
        def group(finished=4,accepted=False):
            p=RoastPlan.objects.create(created_by=user,use_roasted_stock=False,accepted_at=timezone.now() if accepted else None)
            g=RoastGroup.objects.create(plan=p,key='minimum-fixture',coffee=coffee,roast_level='Medium')
            IncomingOrderLine.objects.create(group=g,finished_oz=finished,product_coffee=coffee)
            return p,g
        p,g=group();assert sync_group(g,p,user)
        row=g.planned_batches.get();assert row.green_oz==8 and row.roaster_id==small.pk
        s=summary(g,p.estimated_loss_pct);assert s['minimum_sizing'] and s['minimum_extra_green']>0 and s['expected']>s['production_target']
        original=row.pk;assert not sync_group(g,p,user) and g.planned_batches.get().pk==original
        g.orders.all().delete();sync_group(g,p,user);assert not g.planned_batches.exists(),'Zero demand created a minimum batch'
        for machine,valid,invalid in [(small,[8,40],[D('7.9'),D('40.1')]),(large,[41,140],[D('40.9'),D('140.1')])]:
            for amount in valid:PlannedBatch(group=g,roaster=machine,green_oz=amount).full_clean()
            for amount in invalid:rejected(lambda amount=amount,machine=machine:PlannedBatch(group=g,roaster=machine,green_oz=amount).full_clean())
        rejected(lambda:Batch(date=timezone.localdate(),operator=user,coffee=coffee,roaster=small,green_oz=7,roast_level='Medium').full_clean())
        small.min_green_oz=0;small.save()
        old=Batch.objects.create(date=timezone.localdate(),operator=user,coffee=coffee,roaster=small,green_oz=1,roasted_oz=D('.8'),roasted_at=timezone.now(),roast_level='Medium')
        small.min_green_oz=8;small.save()
        old.full_clean();assert old.green_oz==1,'Recorded history was rewritten'
        form=BatchForm({'date':str(timezone.localdate()),'coffee':coffee.pk,'roaster':small.pk,'green_oz':'7.9','roast_level':'Medium','note':''})
        assert not form.is_valid() and 'green_oz' in form.errors
        from portal.roasted_stock import StockForm,stock_coffees
        from portal.models import RoastedStock
        import uuid
        origin=Coffee.objects.create(name='Fictional occasional origin',kind='single_origin',standard_roast='Medium',bulk_stock_enabled=False)
        assert not stock_coffees().filter(pk=origin.pk).exists()
        measured={'action':'measure','request_key':str(uuid.uuid4()),'coffee':origin.pk,'roast_level':'Medium','remaining_oz':'1.5','roasted_on':str(timezone.localdate()),'note':'Weighed whole-bean leftovers after packing'}
        assert StockForm(measured).is_valid(),'Occasional standard-roast origin could not enter measured stock'
        assert client.post('/stock/',measured).status_code==302
        assert client.post('/stock/',measured).status_code==302
        assert RoastedStock.objects.filter(request_key=measured['request_key'],remaining_oz=D('1.5')).count()==1,'Repeated leftover measurement credited twice'
        def snapshot():
            return {m.__name__:list(getattr(m,'all_objects',m.objects).order_by('pk').values()) for m in [RoastPlan,RoastGroup,IncomingOrderLine,PlannedBatch,Batch,PlanEvent]}
        def post_plan(p,row,action,weight,machine,ok):
            p.refresh_from_db();before=snapshot()
            r=client.post('/planning/',{'plan':p.pk,'version':p.version,'row':row.pk,'roaster':machine.pk,'green_oz':str(weight),'action':action})
            assert r.status_code==(302 if ok else 400),(action,r.status_code,r.content)
            if not ok:assert snapshot()==before,'Rejected minimum change wrote data'
        p,g=group(80);row=PlannedBatch.objects.create(group=g,roaster=small,green_oz=16)
        post_plan(p,row,'save_batch',40,large,False)
        post_plan(p,row,'split_batch',D('15.9'),small,False)
        post_plan(p,row,'split_batch',16,small,True)
        assert list(g.planned_batches.values_list('green_oz',flat=True))==[8,8]
        p,g=group(80);row=PlannedBatch.objects.create(group=g,roaster=large,green_oz=82)
        post_plan(p,row,'split_batch',80,large,False);post_plan(p,row,'split_batch',82,large,True)
        assert list(g.planned_batches.values_list('green_oz',flat=True))==[41,41]
        # A changed minimum invalidates an otherwise valid signed merge preview.
        p,g=group(30);rows=[PlannedBatch.objects.create(group=g,roaster=large,green_oz=50) for _ in range(2)]
        values={'version':p.version,'rows':[str(r.pk) for r in rows],'roaster':large.pk,'action':'preview'}
        r=client.post(f'/plans/{p.pk}/combine/',values);assert r.status_code==200,r.content
        token=r.context['preview']['token'];large.min_green_oz=42;large.save();before=snapshot()
        r=client.post(f'/plans/{p.pk}/combine/',{**values,'action':'confirm','preview_token':token});assert r.status_code==400 and snapshot()==before
        large.min_green_oz=41;large.save()
        # Exact-total combination refuses an undersized target instead of silently adding coffee.
        p,g=group();rows=[PlannedBatch.objects.create(group=g,roaster=small,green_oz=8) for _ in range(2)]
        values={'version':p.version,'rows':[str(r.pk) for r in rows],'roaster':large.pk,'action':'preview'}
        before=snapshot();assert client.post(f'/plans/{p.pk}/combine/',values).status_code==400 and snapshot()==before
        # Simulate an older unstarted row. Acceptance, preparation and first measurement must reject it.
        p,g=group();row=PlannedBatch.objects.create(group=g,roaster=small,green_oz=8)
        PlannedBatch.objects.filter(pk=row.pk).update(green_oz=D('7.9'));row.refresh_from_db()
        client.post(f'/plans/{p.pk}/accept/',{'version':p.version});p.refresh_from_db();assert not p.accepted_at
        p.accepted_at=timezone.now();p.save(update_fields=['accepted_at'])
        rejected(lambda:usable_row(row))
        before=snapshot();r=client.post(f'/roasts/{row.pk}/',{'revision':row_token(row),'measured_at':'on'})
        assert r.status_code==400 and snapshot()==before and not PlannedBatch.objects.get(pk=row.pk).batch_id
        first_token=row_token(row);first_preparation=row_fingerprint(row)
        small.min_green_oz=9;small.save();row=PlannedBatch.objects.select_related('roaster','group__plan','group__coffee').get(pk=row.pk)
        assert row_token(row)!=first_token and row_fingerprint(row)!=first_preparation
        # Removing an invalid older draft is still possible; restoring it requires correction.
        post_plan(p,row,'remove_batch',D('7.9'),small,True)
        assert PlannedBatch.all_objects.get(pk=row.pk).removed_at
        transaction.set_rollback(True)
    print('PASS: configured green minima, bounded balanced loads, visible minimum overage, zero-demand stability, manual/split/combine/stale/accept/first-measurement/preparation checks and unchanged recorded history.')
