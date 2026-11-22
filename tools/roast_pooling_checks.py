"""Synthetic regression for shared roasts and independent packing identities."""
def run_roast_pooling_checks(client,user):
    import hashlib,json
    from decimal import Decimal as D
    from django.db import transaction
    from django.utils import timezone
    from portal.models import Coffee,LabelVariant,Roaster,RoastPlan,RoastGroup,IncomingOrderLine,PlannedBatch,Batch,PlanEvent
    from portal.planning import group_for,profile_key
    from portal.autobatches import sync_plan
    from portal.roast_pooling import consolidate_labels
    with transaction.atomic():
        Roaster.objects.update(active=False)
        large=Roaster.objects.create(name='Pooling large',max_green_oz=140)
        Roaster.objects.create(name='Pooling small',max_green_oz=40)
        coffee=Coffee.objects.get(name='Demo Hearth')
        label=LabelVariant.objects.create(coffee=coffee,name='Fictional wholesale label')
        def plan():return RoastPlan.objects.create(created_by=user,estimated_loss_pct=16,spillage_pct=5,use_roasted_stock=False)
        def order(group,qty,label=None,grind='whole',explicit=True):
            kwargs={'product_coffee':coffee,'product_label':label} if explicit else {}
            return IncomingOrderLine.objects.create(group=group,finished_oz=qty,grind=grind,packaging=[{'size_oz':str(qty),'bags':1}],**kwargs)
        data={'coffee':coffee,'roast_level':'Medium','target_finish_temp_f':None,'label_variant':label}
        fresh=plan();wholesale=group_for(fresh,data);retail=group_for(fresh,{**data,'label_variant':None})
        assert wholesale.pk==retail.pk and wholesale.label_variant_id is None
        lines=[order(wholesale,D(180),label,'regular'),order(retail,D('18.5'))]
        sync_plan(fresh,user)
        assert list(wholesale.planned_batches.values_list('roaster_id','green_oz'))==[(large.pk,D('124.2')),(large.pk,D('124.1'))]
        assert [line.ordered_label for line in lines]==[label,None]
        assert [line.grind for line in lines]==['regular','whole']
        from portal.label_sheets import order_labels
        assert [row['label'] for row in order_labels(fresh)]==[label.name,'']
        # Reproduce the pre-fix accepted two-label layout, including an old
        # allocation whose label is inherited from its group.
        old=plan();old.accepted_at=timezone.now();old.accepted_by=user;old.save()
        old_key=hashlib.sha256(json.dumps([coffee.pk,'Medium',None,label.pk,None]).encode()).hexdigest()
        a=RoastGroup.objects.create(plan=old,key=old_key,coffee=coffee,roast_level='Medium',label_variant=label)
        b=group_for(old,{**data,'label_variant':None})
        x=order(a,D(180),explicit=False);y=order(b,D('18.5'))
        original={line.pk:(line.finished_oz,line.grind,line.packaging,line.ordered_label.pk if line.ordered_label else None) for line in (x,y)}
        old_rows=[PlannedBatch.objects.create(group=a,roaster=large,green_oz=D('112.5')) for _ in range(2)]
        old_rows.append(PlannedBatch.objects.create(group=b,roaster=large,green_oz=D('23.3')))
        assert not consolidate_labels(old,user,group_ids=[])
        sync_plan(old,user);old.refresh_from_db()
        assert old.accepted_at is None and old.events.filter(action='label_groups_pooled').count()==1
        assert list(PlannedBatch.objects.filter(group__plan=old).values_list('roaster_id','green_oz'))==[(large.pk,D('124.2')),(large.pk,D('124.1'))]
        for line in (x,y):
            line.refresh_from_db();assert line.group_id==b.pk
            assert (line.finished_oz,line.grind,line.packaging,line.ordered_label.pk if line.ordered_label else None)==original[line.pk]
        assert PlannedBatch.all_objects.filter(pk__in=[r.pk for r in old_rows],removed_at__isnull=False).count()==3
        before=list(PlannedBatch.objects.filter(group__plan=old).values_list('pk','green_oz'))
        sync_plan(old,user);assert before==list(PlannedBatch.objects.filter(group__plan=old).values_list('pk','green_oz'))
        assert old.events.filter(action='label_groups_pooled').count()==1
        # The physical-profile key still separates roast levels, custom finish
        # temperatures and legacy custom-order identities.
        keys={profile_key(coffee.pk,level,temp,None,legacy) for level,temp,legacy in [('Medium',None,None),('Dark',None,None),('Medium',D(410),None),('Medium',D(411),None),('Medium',None,123)]}
        assert len(keys)==5
        # Manual drafts and physical work cannot be silently consolidated.
        protected=plan()
        a=RoastGroup.objects.create(plan=protected,key=old_key,coffee=coffee,roast_level='Medium',label_variant=label,auto_batches=False)
        b=group_for(protected,{**data,'label_variant':None});order(a,D(16),label);order(b,D(16))
        assert not consolidate_labels(protected,user)
        a.auto_batches=True;a.save(update_fields=['auto_batches'])
        physical=Batch.objects.create(date=protected.date,operator=user,roaster=large,coffee=coffee,roast_level='Medium',green_oz=20,measured_at=timezone.now())
        PlannedBatch.objects.create(group=a,roaster=large,green_oz=20,batch=physical)
        assert not consolidate_labels(protected,user)
        assert a.orders.count()==1 and b.orders.count()==1
        green=plan()
        a=RoastGroup.objects.create(plan=green,key=old_key,coffee=coffee,roast_level='Medium',label_variant=label)
        b=group_for(green,{**data,'label_variant':None});order(a,D(16),label);order(b,D(16))
        PlanEvent.objects.create(plan=green,actor=user,action='green_approve',details={'group':a.pk,'parts':{'1':'100'}})
        assert not consolidate_labels(green,user)
        assert a.orders.count()==1 and b.orders.count()==1
        transaction.set_rollback(True)
    print('PASS: packaging labels share compatible loads; legacy allocation labels, grind/pack sizes, history, capacity, custom profiles and started/manual guards preserved.')


def run_order_roast_edit_checks(client, user):
    from django.db import transaction
    from django.utils import timezone
    from portal.autobatches import sync_plan
    from portal.models import Batch, Coffee, ImportOrder, IncomingOrderLine, LabelVariant, PackingProgress, RoastPlan
    from portal.planning import group_for
    from portal.roast_sheet import row_token

    with transaction.atomic():
        coffee = Coffee.objects.create(name='Fictional Edit Origin', standard_roast='Light')
        label = LabelVariant.objects.create(coffee=coffee, name='Fictional Edit Label')
        plan = RoastPlan.objects.create(created_by=user)
        group = group_for(plan, {'coffee': coffee, 'roast_level': 'Light'})
        original_items = [{'title': 'Fictional Edit Origin', 'coffee': coffee.pk, 'quantity': 6,
                           'size_oz': '16', 'roast_level': 'Light', 'line_key': '1'}]
        source = ImportOrder.objects.create(external_id='fictional-roast-edit', reference='TEST-ROAST',
            received_at=timezone.now(), imported_at=timezone.now(), imported_plan=plan,
            financial_status='paid', fulfillment_status='unfulfilled', lines=original_items)
        custom = IncomingOrderLine.objects.create(group=group, import_order=source, source='shopify',
            external_id='fictional-roast-edit:1', reference=source.reference, product_coffee=coffee,
            product_label=label, finished_oz=96, grind='regular', packaging=[{'size_oz': '16', 'bags': 6}])
        standard = IncomingOrderLine.objects.create(group=group, finished_oz=16, grind='whole')
        sizes = (12, 16)
        smaller = [IncomingOrderLine.objects.create(group=group, finished_oz=size, grind='whole',
                   packaging=[{'size_oz':str(size), 'bags':1}]) for size in sizes]
        blend = Coffee.objects.create(name='Fictional Fixed Blend', kind='blend', standard_roast='Medium')
        blend_group = group_for(plan, {'coffee':blend, 'roast_level':'Medium'})
        fixed = IncomingOrderLine.objects.create(group=blend_group, finished_oz=80, grind='whole')
        sync_plan(plan, user)
        plan.accepted_at = timezone.now()
        plan.save(update_fields=['accepted_at'])
        url = f'/planning/?plan={plan.pk}'

        def change(line, roast, version=None):
            return client.post(url, {'action': 'change_order_roast', 'line': line.pk, 'roast_level': roast,
                                    'version': plan.version if version is None else version})

        assert client.get(url).content.count(b'value="change_order_roast"') == 4
        assert change(fixed, 'French').status_code == 400
        assert change(custom, 'French', version=plan.version + 1).status_code == 400
        assert change(custom, 'French').status_code == 302
        custom.refresh_from_db()
        standard.refresh_from_db()
        source.refresh_from_db()
        plan.refresh_from_db()
        assert plan.accepted_at is None and plan.version == 1
        assert source.lines == original_items and source.imported_plan_id == plan.pk
        assert custom.group.roast_level == 'French' and custom.group.planned_batches.exists()
        assert standard.group_id == group.pk and standard.group.planned_batches.exists()
        assert (custom.product_label_id, custom.finished_oz, custom.grind, custom.packaging) == (
            label.pk, 96, 'regular', [{'size_oz': '16', 'bags': 6}])
        event = plan.events.get(action='order_roast_changed')
        assert event.details['line'] == custom.pk and event.details['after']['roast'] == 'French'
        assert change(custom, 'French').status_code == 302
        plan.refresh_from_db()
        assert plan.version == 1
        for line, roast in zip(smaller, ('Dark','Medium/Dark')):
            assert change(line, roast).status_code == 302
            plan.refresh_from_db()
            line.refresh_from_db()
            assert line.group.roast_level == roast
        standard.refresh_from_db()
        assert standard.group.roast_level == 'Light'
        assert client.post(f'/plans/{plan.pk}/accept/', {'version':plan.version}).url == '/'
        plan.refresh_from_db()
        assert plan.accepted_at
        for line, size in zip(smaller, sizes):
            row = line.group.planned_batches.get()
            response = client.post(f'/roasts/{row.pk}/', {'revision':row_token(row), 'measured_at':'on',
                                   'roasted_oz':f'{size}.0', 'cooled_at':'on', 'roasted_at':'on'})
            assert response.status_code == 200, response.content
            row.refresh_from_db()
            assert row.batch.roast_level == line.group.roast_level and row.batch.roasted_oz == size
            assert change(line, 'Light').status_code == 400
        packing = PackingProgress.objects.create(line=custom, ground_at=timezone.now())
        assert change(custom, 'Light').status_code == 400
        packing.delete()
        draft = custom.group.planned_batches.first()
        draft.batch = Batch.objects.create(operator=user, coffee=coffee, roaster=draft.roaster,
            planned_group=custom.group, roast_level='French', green_oz=draft.green_oz, measured_at=timezone.now())
        draft.save(update_fields=['batch'])
        assert change(custom, 'Light').status_code == 400
        transaction.set_rollback(True)
    print('PASS: Plans edits one eligible order roast, separates standard demand, preserves packing and source, and protects started work.')
