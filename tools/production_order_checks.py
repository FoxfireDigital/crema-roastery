"""Shipping labels must neither fabricate production nor duplicate its demand."""
def run_production_order_checks(client,user):
    import copy
    from django.db import transaction
    from django.test import Client
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from portal.models import ImportOrder,RoastPlan,IncomingOrderLine,PlannedBatch,Batch,OrderReviewEvent
    from portal.order_import import infer_item,source_signature,add_selected,readiness
    from portal.shopify import stage_orders
    from portal.roast_sheet import row_token
    from portal.production_orders import production_confirmed,source_hold_reason,review_token
    with transaction.atomic():
        line=infer_item('Demo Hearth - 16 oz / Whole bean',1,use_saved=False)
        line.update(line_key='1',source_line='1',source_total='16',fulfilled=False,api_line_id='gid://shopify/LineItem/9990001')
        signature=source_signature([line],'')
        order=ImportOrder.objects.create(external_id='9990001',reference='#FICTIONAL-SHIPPING',received_at=timezone.now(),financial_status='paid',fulfillment_status='unfulfilled',subscription='unknown',lines=[line],source_signature=signature,api_source_signature='a'*64)
        plan=RoastPlan.objects.create(created_by=user);add_selected(plan,[order.pk],user);plan.refresh_from_db()
        assert client.post(f'/plans/{plan.pk}/accept/',{'version':plan.version}).status_code==302
        row=PlannedBatch.objects.get(group__plan=plan)
        assert client.post(f'/roasts/{row.pk}/',{'revision':row_token(row),'roasted_oz':'17.1','measured_at':'on','roasted_at':'on'},HTTP_ACCEPT='application/json').status_code==200
        row.refresh_from_db();before=(row.batch.pk,row.batch.green_oz,row.batch.roasted_oz,row.batch.roasted_at)
        def refresh(cancelled=False,quantity=1,status='fulfilled'):
            latest={**copy.deepcopy(line),'fulfilled':status=='fulfilled','quantity':quantity,'source_total':str(16*quantity)}
            stage_orders([{'external_id':order.external_id,'reference':order.reference,'customer':'','received_at':order.received_at,'financial_status':'paid','fulfillment_status':status,'cancelled':cancelled,'subscription':'unknown','instructions':'','lines':[latest],'source_signature':signature,'api_signature':('a' if quantity==1 else 'b')*64}])
            order.refresh_from_db();plan.refresh_from_db()
        refresh()
        assert plan.accepted_at is None and order.fulfillment_status=='fulfilled'
        assert IncomingOrderLine.objects.filter(import_order=order).count()==1 and source_hold_reason(order)
        url=f'/imports/{order.pk}/production/'
        token=review_token(order,user)
        assert client.post(url,{'review_token':token,'reason':'Label bought before production'}).status_code==409
        assert client.post(url,{'review_token':'forged','confirmed':'on','reason':'Fixture'}).status_code==409
        csrf=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');csrf.force_login(user)
        assert csrf.post(url,{'review_token':token,'confirmed':'on','reason':'Fixture'}).status_code==403
        outsider=get_user_model().objects.create_user('fixture-packing-only',password='fictional-password-only')
        limited=Client(HTTP_HOST='localhost');limited.force_login(outsider)
        assert limited.post(url,{'review_token':token,'confirmed':'on','reason':'Fixture'}).status_code==302
        payload={'review_token':token,'confirmed':'on','reason':'Label bought before production'}
        assert client.post(url,payload).status_code==302
        order.refresh_from_db();assert production_confirmed(order) and not source_hold_reason(order)
        assert order.fulfillment_status=='fulfilled' and order.lines[0]['fulfilled'] is True
        assert not readiness(order)[0],'Confirmed imported demand became eligible for duplicate import'
        assert client.post(url,payload).status_code==302 and order.review_events.filter(after__has_key='production_confirmation').count()==1
        assert client.post(f'/plans/{plan.pk}/accept/',{'version':plan.version}).status_code==302
        refresh();assert plan.accepted_at and production_confirmed(order),'Unchanged shipping refresh paused a confirmed order'
        row.refresh_from_db();assert before==(row.batch.pk,row.batch.green_oz,row.batch.roasted_oz,row.batch.roasted_at)
        assert IncomingOrderLine.objects.filter(import_order=order).count()==1
        refresh(cancelled=True);assert not plan.accepted_at and not production_confirmed(order)
        assert client.post(url,{'review_token':review_token(order,user),'confirmed':'on','reason':'Cannot bypass cancellation'}).status_code==409
        refresh();assert not production_confirmed(order),'Reverting a cancellation resurrected an old confirmation'
        stale=review_token(order,user);refresh(quantity=2)
        assert order.source_changed and client.post(url,{'review_token':stale,'confirmed':'on','reason':'Stale review'}).status_code==409
        assert order.lines[0]['quantity']==1 and order.latest_lines[0]['quantity']==2
        transaction.set_rollback(True)
    print('PASS: shipping-only confirmation, retained demand/results, unchanged refresh, invalidation/reversion, duplicate protection, staff/CSRF and stale-review guards.')
