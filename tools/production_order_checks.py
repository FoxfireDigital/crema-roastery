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
    # A shipping refund must retain remaining coffee demand without treating a
    # partial refund as a cancellation or manufacturing another subscription.
    from portal.shopify_client import normalize_order
    from portal.order_import import import_rows
    from portal.plan_completion import completion_checks
    with transaction.atomic():
        node={'id':'gid://shopify/Order/9990002','legacyResourceId':'9990002','name':'#FICTIONAL-PARTIAL-REFUND',
              'createdAt':timezone.now().isoformat(),'displayFinancialStatus':'PARTIALLY_REFUNDED','displayFulfillmentStatus':'UNFULFILLED',
              'all_lines':[{'id':'gid://shopify/LineItem/9990002','name':'Demo Hearth - 16 oz / Whole bean','sku':'','quantity':3,'currentQuantity':2,'unfulfilledQuantity':2}]}
        normalized=normalize_order(node)
        assert normalized['financial_status']=='partially_refunded' and normalized['lines'][0]['quantity']==2
        stage_orders([normalized]);order=ImportOrder.objects.get(external_id='9990002')
        assert readiness(order)[0] and not source_hold_reason(order)
        listing=next(r for r in import_rows() if r['order'].pk==order.pk)
        assert listing['ready'] and listing['actionable'] and listing['category']=='ready'
        assert b'Partial refund: check remaining coffee quantities' in client.get('/imports/').content
        for payment in ['refunded','pending','partially_paid','authorized','voided','unknown','']:
            order.financial_status=payment
            assert not readiness(order)[0] and source_hold_reason(order),payment
        order.financial_status='partially_refunded';order.cancelled=True
        assert not readiness(order)[0] and source_hold_reason(order)
        order.cancelled=False;order.fulfillment_status='partial'
        assert not readiness(order)[0] and source_hold_reason(order)
        order.fulfillment_status='fulfilled'
        assert not readiness(order)[0] and source_hold_reason(order)
        order.fulfillment_status='unfulfilled';order.source_changed=True
        assert not readiness(order)[0] and source_hold_reason(order)
        order.source_changed=False;order.financial_status='paid';order.save()
        plan=RoastPlan.objects.create(created_by=user);add_selected(plan,[order.pk],user);plan.refresh_from_db()
        assert client.post(f'/plans/{plan.pk}/accept/',{'version':plan.version}).status_code==302
        plan.refresh_from_db();before=list(IncomingOrderLine.objects.filter(import_order=order).values('pk','finished_oz','packaging','grind'))
        stage_orders([normalized]);order.refresh_from_db();plan.refresh_from_db()
        assert plan.accepted_at and not source_hold_reason(order),'Shipping-only partial refund paused unchanged coffee'
        assert not any('payment or fulfillment' in issue for issue in completion_checks(plan))
        assert list(IncomingOrderLine.objects.filter(import_order=order).values('pk','finished_oz','packaging','grind'))==before
        assert not readiness(order)[0] and readiness(order)[1].startswith('Already added')
        # A fulfilled, partially refunded order still needs an explicit production confirmation.
        fulfilled=copy.deepcopy(normalized);fulfilled['fulfillment_status']='fulfilled';fulfilled['lines'][0]['fulfilled']=True
        stage_orders([fulfilled]);order.refresh_from_db();plan.refresh_from_db()
        assert not plan.accepted_at and source_hold_reason(order)
        assert client.post(f'/imports/{order.pk}/production/',{'review_token':review_token(order,user),'confirmed':'on','reason':'Shipping refunded for local pickup; coffee still needed'}).status_code==302
        order.refresh_from_db();assert production_confirmed(order) and not source_hold_reason(order)
        changed=copy.deepcopy(node);changed['all_lines'][0].update(currentQuantity=1,unfulfilledQuantity=1)
        stage_orders([normalize_order(changed)]);order.refresh_from_db()
        assert order.source_changed and source_hold_reason(order)
        assert list(IncomingOrderLine.objects.filter(import_order=order).values('pk','finished_oz','packaging','grind'))==before
        empty=copy.deepcopy(node);empty['all_lines'][0].update(currentQuantity=0,unfulfilledQuantity=0)
        assert normalize_order(empty)['lines']==[],'Refunded item remained in demand'
        transaction.set_rollback(True)
    print('PASS: partial refunds retain current coffee quantities, visible status, import/active-plan/completion parity, fulfilled confirmation and refund/cancellation/change/duplicate guards.')
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
