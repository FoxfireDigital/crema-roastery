"""Synthetic operational invariants, run only in the disposable release database."""
def run_production_checks(root,client,user):
    import io,hashlib
    from decimal import Decimal
    from django.db import transaction
    from django.core.exceptions import ValidationError
    from django.utils import timezone
    from portal.models import Coffee,RoastPlan,ImportOrder,IncomingOrderLine,PlannedBatch,Batch,GreenBeanItem,GreenRecipe,GreenMovement,RoastedStock,RoastedStockAllocation,PackingProgress,LabelArtwork,PlanEvent
    from portal.order_import import infer_item,source_signature,add_selected,readiness
    from portal.roast_sheet import row_token
    from portal.packing import progress_token,applicable_steps
    from portal.roasted_stock import use_stock
    from portal.finished_coverage import plan_coverage
    from portal.plan_completion import completion_checks
    from portal.autobatches import sync_plan
    from portal.label_sheets import order_labels
    def rejected(call):
        try:call()
        except ValidationError:return
        raise AssertionError('Unsafe production operation accepted')
    with transaction.atomic():
        coffee=Coffee.objects.get(name='Demo Hearth')
        green=GreenBeanItem.objects.create(name='Fictional workflow lot',remaining_oz=1000,recorded_by=user)
        GreenRecipe.objects.create(coffee=coffee,components=[{'item':green.pk,'percent':'100'}],updated_by=user)
        stock=RoastedStock.objects.create(coffee=coffee,roast_level='Medium',remaining_oz=16,recorded_by=user,measured_at=timezone.now())
        item=infer_item('Demo Hearth - 16 oz / Whole bean',2,use_saved=False)
        item.update(line_key='1',source_line='1',source_total='32',fulfilled=False)
        order=ImportOrder.objects.create(external_id='900001',reference='#FICTIONAL-1',received_at=timezone.now(),financial_status='paid',fulfillment_status='unfulfilled',lines=[item],source_signature=source_signature([item],''))
        assert readiness(order)[0]
        plan=RoastPlan.objects.create(created_by=user)
        add_selected(plan,[order.pk],user);plan.refresh_from_db()
        rejected(lambda:add_selected(plan,[order.pk],user))
        line=IncomingOrderLine.objects.get(import_order=order);group=line.group
        assert line.finished_oz==32 and line.grind=='whole' and sum(Decimal(p['size_oz'])*p['bags'] for p in line.packaging)==32
        coverage=plan_coverage(plan)['totals'];assert coverage['bulk_reserved']==16 and coverage['bulk_used']==0 and coverage['recorded_total']==0
        rows=list(PlannedBatch.objects.filter(group=group));assert len(rows)==1
        row=rows[0];assert row.green_oz<=row.roaster.capacity and row.green_oz==Decimal('21.0')
        # New source holds cannot be bypassed by simply accepting again.
        order.source_flags=['Fixture source requires review'];order.save(update_fields=['source_flags'])
        client.post(f'/plans/{plan.pk}/accept/',{'version':plan.version});plan.refresh_from_db();assert plan.accepted_at is None
        order.source_flags=[];order.save(update_fields=['source_flags'])
        response=client.post(f'/plans/{plan.pk}/accept/',{'version':plan.version});plan.refresh_from_db()
        assert response.status_code==302 and plan.accepted_at
        use_stock(plan,user);stock.refresh_from_db();assert stock.remaining_oz==0
        rejected(lambda:use_stock(plan,user));assert RoastedStockAllocation.objects.filter(line=line,status='used').count()==1
        # Measured deducts the frozen green recipe once. A replay cannot deduct it again.
        row=PlannedBatch.objects.select_related('group__plan','roaster','batch').get(pk=row.pk)
        revision=row_token(row)
        response=client.post(f'/roasts/{row.pk}/',{'revision':revision,'measured_at':'on'});assert response.status_code==200,response.content
        green.refresh_from_db();assert green.remaining_oz==979
        replay=client.post(f'/roasts/{row.pk}/',{'revision':revision,'measured_at':'on'});assert replay.status_code==409
        green.refresh_from_db();assert green.remaining_oz==979 and GreenMovement.objects.filter(item=green).count()==1
        # The operator may mark roasted before measuring finished output.
        row=PlannedBatch.objects.select_related('group__plan','roaster','batch').get(pk=row.pk)
        response=client.post(f'/roasts/{row.pk}/',{'revision':row_token(row),'measured_at':'on','roasted_at':'on'});assert response.status_code==200
        row.refresh_from_db();assert row.batch.roasted_at and row.batch.roasted_oz is None and row.batch.cooled_at is None
        response=client.post(f'/roasts/{row.pk}/',{'revision':row_token(row),'roasted_oz':'17.6','measured_at':'on','roasted_at':'on','bagged_at':'on','sealed_at':'on'});assert response.status_code==200,response.content
        row.refresh_from_db();assert row.batch.roasted_oz==Decimal('17.6') and not row.batch.cooled_at and not row.batch.bagged_at and not row.batch.sealed_at
        # Cooling is an explicit roasting step, independent of packing. Old clients
        # cannot set bagging/sealing through Today, and corrections preserve them.
        now=timezone.now();Batch.objects.filter(pk=row.batch_id).update(bagged_at=now,sealed_at=now)
        row=PlannedBatch.objects.select_related('group__plan','batch').get(pk=row.pk)
        green_before=GreenMovement.objects.filter(item=green).count()
        response=client.post(f'/roasts/{row.pk}/',{'revision':row_token(row),'roasted_oz':'17.6','cooled_at':'on'})
        assert response.status_code==400,'Cooling without preceding steps was accepted'
        response=client.post(f'/roasts/{row.pk}/',{'revision':row_token(row),'roasted_oz':'17.6','measured_at':'on','roasted_at':'on','cooled_at':'on'})
        assert response.status_code==200,response.content
        row.refresh_from_db();assert row.batch.cooled_at and row.batch.bagged_at==now and row.batch.sealed_at==now
        assert GreenMovement.objects.filter(item=green).count()==green_before
        html=client.get('/').content.decode()
        roasting_html=html.split('<section class="today-packing"')[0]
        assert 'name="cooled_at"' in roasting_html and 'name="bagged_at"' not in roasting_html and 'name="sealed_at"' not in roasting_html
        assert f'/batches/{row.batch_id}/#artisan-logs' in html and 'Review roast / logs' in html
        assert html.index('class="nav-column"')<html.index('Coffee & artwork')<html.index('Connections & orders')<html.index('<section><h2>Other tools')
        result=response.json()
        undone=client.post(f'/roasts/{row.pk}/undo/',{'revision':result['revision'],'event':result['undo_event']})
        assert undone.status_code==200,undone.content
        row.refresh_from_db();assert not row.batch.cooled_at and row.batch.bagged_at==now and row.batch.sealed_at==now
        coverage=plan_coverage(plan)['totals'];assert coverage['recorded_total']==Decimal('33.6') and coverage['bulk_used']==16 and coverage['remaining_to_record']==0
        before=list(PlannedBatch.objects.filter(group=group).values_list('pk','green_oz'))
        sync_plan(plan,user);assert before==list(PlannedBatch.objects.filter(group=group).values_list('pk','green_oz'))
        # Record packing through the same HTTP endpoint used by the checkboxes.
        steps={key:'on' for key,_ in applicable_steps(line)}
        response=client.post(f'/packing/{line.pk}/progress/',{'revision':progress_token(line,None),**steps});assert response.status_code==200,response.content
        progress=PackingProgress.objects.get(line=line);assert progress.sealed_at
        # Generate fictional artwork only in this disposable transaction.
        from PIL import Image
        buffer=io.BytesIO();Image.new('RGB',(200,280),'black').save(buffer,format='PNG');raw=buffer.getvalue()
        LabelArtwork.objects.create(coffee=coffee,size_oz=16,roast_level='Medium',per_sheet=4,image_data=raw,image_format='PNG',source_name='fictional.png',active=True,width=200,height=280,sha256=hashlib.sha256(raw).hexdigest(),uploaded_by=user)
        labels=order_labels(plan);assert len(labels)==1 and labels[0]['bags']==2 and not labels[0]['issue'],labels
        assert any('Cooled' in issue for issue in completion_checks(plan)), 'Missing cooling did not block closure'
        row.batch.refresh_from_db();row.batch.cooled_at=now;row.batch.bagged_at=None;row.batch.sealed_at=None
        row.batch.save(update_fields=['cooled_at','bagged_at','sealed_at'])
        assert not completion_checks(plan),completion_checks(plan)
        response=client.post(f'/plans/{plan.pk}/close/',{'version':plan.version});assert response.status_code==302
        plan.refresh_from_db();assert plan.closed_at and PlanEvent.objects.filter(plan=plan,action='closed').exists()
        assert client.get(f'/plans/{plan.pk}/completed/').status_code==200
        # A completed plan cannot receive more production edits through the sheet.
        assert client.post(f'/roasts/{row.pk}/',{'revision':row_token(row),'roasted_oz':'18.0','measured_at':'on','roasted_at':'on'}).status_code==404
        row.batch.refresh_from_db();assert row.batch.roasted_oz==Decimal('17.6')
        # Custom single-origin 5 lb demand stays separate from standard smaller bags.
        from portal.planning import IncomingForm,group_for
        origin=Coffee.objects.get(name='Demo Single Origin');custom_plan=RoastPlan.objects.create(created_by=user)
        standard=IncomingForm({'coffee':origin.pk,'bags_1lb':1,'roast_level':'Medium'});assert standard.is_valid()
        custom=IncomingForm({'coffee':origin.pk,'bags_5lb':1,'roast_level':'French'});assert custom.is_valid()
        assert group_for(custom_plan,standard.cleaned_data).pk!=group_for(custom_plan,custom.cleaned_data).pk
        small_custom=IncomingForm({'coffee':origin.pk,'bags_1lb':1,'roast_level':'French'});assert not small_custom.is_valid()
        blend_custom=IncomingForm({'coffee':coffee.pk,'bags_5lb':1,'roast_level':'French'});assert not blend_custom.is_valid()
        transaction.set_rollback(True)
    print('PASS: order-to-closure workflow, bulk credit versus usage, frozen green deduction/replay, roast/packing saves, labels, completed-record protection, no surprise loads and separate custom roasts.')


def run_standard_label_checks(client, user):
    import hashlib
    import io
    from django.db import transaction
    from PIL import Image
    from portal.label_sheets import find_art, order_labels
    from portal.models import Coffee, IncomingOrderLine, LabelArtwork, LabelVariant, RoastPlan
    from portal.planning import group_for

    with transaction.atomic():
        coffee = Coffee.objects.create(name='Fictional Label Origin', standard_roast='Light')
        plan = RoastPlan.objects.create(created_by=user)
        french = group_for(plan, {'coffee':coffee,'roast_level':'French'})
        light = group_for(plan, {'coffee':coffee,'roast_level':'Light'})
        label = LabelVariant.objects.create(name='Fictional Account Label',coffee=coffee)
        raw = io.BytesIO()
        Image.new('RGB',(30,40),'black').save(raw,format='PNG')
        artwork = LabelArtwork.objects.create(coffee=coffee,size_oz=16,roast_level='Light',per_sheet=4,
            image_data=raw.getvalue(),image_format='PNG',source_name='fictional.png',active=True,
            width=30,height=40,sha256=hashlib.sha256(raw.getvalue()).hexdigest(),uploaded_by=user)

        def allocation(group, size, reference, **kwargs):
            return IncomingOrderLine.objects.create(group=group, finished_oz=size, reference=reference,
                packaging=[{'size_oz':str(size),'bags':1}], product_coffee=coffee, **kwargs)

        custom = allocation(french, 16, 'TEST-LABEL', grind='regular')
        special = allocation(french, 16, 'TEST-SPECIAL', grind='regular', product_label=label)
        unknown = allocation(french, 16, 'TEST-GRIND', grind='unknown')
        allocation(light, 80, 'TEST-5-LB', grind='regular')
        key = f'{custom.pk}-0'
        url = f'/labels/?plan={plan.pk}'
        page = client.get(url)
        assert page.status_code == 200 and b'8E+1' not in page.content and b'<td>5 lb<' in page.content
        assert page.content.count(b'Use standard label') == 1
        assert b'<td>5 lb<' in client.get(f'/packing/?plan={plan.pk}').content
        blocked = {r['key']:r for r in order_labels(plan, [f'{special.pk}-0',f'{unknown.pk}-0'])}
        assert not blocked[f'{special.pk}-0']['standard_override'] and not blocked[f'{unknown.pk}-0']['standard_override']
        with_override = client.get(url+'&standard_labels='+key)
        assert b'Standard label selected' in with_override.content and b'Artwork says Light.' in with_override.content
        assert with_override.context['rows'][0]['art']['id'] == str(artwork.pk)
        form = with_override.context['form']
        data = {name:form[name].value() for name in ('revision','queue_token','layout','start_slot',
            'left','top','width','height','gap_x','gap_y','offset_x','offset_y')}
        data.update(plan=plan.pk, selected=[key], standard_labels=[key], checked='on')
        for mode in ('preview','download'):
            pdf = client.post(url,{**data,'action':mode})
            assert pdf['Content-Type']=='application/pdf' and pdf.content.startswith(b'%PDF-')
        assert client.post(url,{**data,'action':'download','standard_labels':[]})['Content-Type']!='application/pdf'
        assert client.post(url,{**data,'action':'download','standard_labels':[key,f'{special.pk}-0']})['Content-Type']!='application/pdf'
        custom.refresh_from_db()
        assert custom.group.roast_level == 'French' and custom.packaging==[{'size_oz':'16','bags':1}]
        assert b'Standard label selected' not in client.get(url).content
        # Asset-specific approval can cover the actual standard roast while
        # retaining the artwork's printed roast and exact matching boundaries.
        coffee.standard_roast='French'
        coffee.save(update_fields=['standard_roast'])
        approval={'action':'approved_roast_mismatch','printed_roast':'Light','production_roast':'French',
                  'artwork_sha256':artwork.sha256}
        artwork.events=[{**approval,'artwork_sha256':'different'}]
        artwork.save(update_fields=['events'])
        assert not find_art(coffee.name,'',16,'French',grind='regular')[0]
        artwork.events=[approval]
        artwork.save(update_fields=['events'])
        approved, issue=find_art(coffee.name,'',16,'French',grind='regular')
        assert not issue and approved['id']==str(artwork.pk) and approved['roast']=='Light'
        assert not find_art(coffee.name,'',12,'French',grind='regular')[0]
        assert not find_art(coffee.name,'',16,'French',temp=410,grind='regular')[0]
        assert not find_art(coffee.name,label.name,16,'French',grind='regular')[0]
        assert b'Approved artwork says Light.' in client.get(url).content
        from portal.artwork_grind import grind_box, grind_boxes, revision
        from portal.label_sheets import saved_art_record
        from unittest.mock import patch
        mapping_url=f'/labels/artwork/{artwork.pk}/grind-boxes/'
        assert client.get(mapping_url).status_code==200
        before=revision(artwork)
        assert client.post(mapping_url,{'revision':before,'whole_x':'5'}).status_code==400
        coordinates={'revision':before,'whole_x':'5','whole_y':'85','ground_x':'5','ground_y':'90'}
        assert client.post(mapping_url,coordinates).status_code==302
        assert client.post(mapping_url,coordinates).status_code==400
        artwork.refresh_from_db()
        assert grind_boxes(artwork)=={'whole':[.05,.85],'ground':[.05,.9]}
        assert [grind_box(code) for code in ('whole','regular','fine','coarse','unknown',None)]==[
            'whole','ground','ground','ground',None,None]
        assert b'Preview Ground PDF' in client.get(mapping_url).content
        import reportlab.pdfgen.canvas as pdf_canvas
        from portal.label_sheets import make_pdf
        from decimal import Decimal
        preview=f'/labels/artwork/{artwork.pk}/preview/'
        calls=[]
        original_circle=pdf_canvas.Canvas.circle
        def record_dot(self,x,y,radius,*args,**kwargs):
            calls.append((x,y,radius,self._currentMatrix))
            return original_circle(self,x,y,radius,*args,**kwargs)
        with patch.object(pdf_canvas.Canvas,'circle',record_dot):
            for code in ('whole','regular','fine','coarse','unknown'):
                assert client.get(preview+f'?grind={code}').content.startswith(b'%PDF-')
            assert len(calls)==4 and calls[1]==calls[2]==calls[3] and calls[0][1]>calls[1][1]
            geometry={k:Decimal(str(v)) for k,v in {'left':.25,'top':.25,'width':4,'height':2.625,
                       'gap_x':0,'gap_y':0,'offset_x':0,'offset_y':0}.items()}
            data={'layout':8,'start_slot':1,**geometry}
            row={'art':saved_art_record(artwork),'bags':1,'grind_code':'whole'}
            assert make_pdf([row],data).startswith(b'%PDF-')
            assert len(calls)==5 and tuple(round(value, 8) for value in calls[-1][3][:4])==(0.0,1.0,-1.0,0.0)
            assert make_pdf([{**row,'grind_code':None}],data).startswith(b'%PDF-') and len(calls)==5
        transaction.set_rollback(True)
    print('PASS: approved artwork, standard-label override, 5 lb display and automatic grind dots on regular and rotated PDFs.')
