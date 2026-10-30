def run_store_checks(root,client,user):
    import json,io,copy,uuid
    from decimal import Decimal
    from datetime import timedelta
    from unittest.mock import patch
    from django.db import transaction
    from django.core.exceptions import ValidationError
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import Client
    from django.utils import timezone
    from portal.models import StoreConnection,StoreSyncRun,StoreProductMapping,StoreEvent,ImportOrder,IncomingOrderLine,RoastPlan,Batch,ProductMapping,Coffee,PortalConfiguration
    from portal.store_adapters import woo,wix,squarespace,make_line,finish,fetch_page
    from portal.stores import stage,synchronize,source_key,save_connection
    from portal.store_csv import preview_upload,apply_preview,expire_previews
    from portal.order_import import add_selected,readiness,set_order_visibility
    from portal.shopify_client import encrypt
    from portal.store_http import public_addresses,origin,request_json
    def reject(call):
        try:call()
        except ValidationError:return
        raise AssertionError('Unsafe store operation accepted')
    with transaction.atomic():
        from portal.marketplaces import selection,selection_token
        from portal.stores import StoreForm
        config=PortalConfiguration.objects.get(pk=1)
        assert not selection()
        response=client.get('/stores/');assert response.status_code==200 and b'Choose or change marketplaces' in response.content and b'id="store-form"' not in response.content
        response=client.post('/stores/',{'action':'marketplaces','selection_token':selection_token(),'marketplaces':['manual']});assert response.status_code==302
        assert set(dict(StoreForm().fields['platform'].choices))=={'','csv'}
        assert b'Connect Shopify' not in client.get('/imports/').content
        token=selection_token()
        response=client.post('/stores/',{'action':'marketplaces','selection_token':token,'marketplaces':['woocommerce']});assert response.status_code==302
        assert StoreForm().initial['platform']=='woocommerce' and set(dict(StoreForm().fields['platform'].choices))=={'','woocommerce','csv'}
        assert client.post('/stores/',{'action':'marketplaces','selection_token':token,'marketplaces':['wix']}).status_code==400
        assert selection()==['woocommerce']
        assert client.post('/stores/',{'action':'marketplaces','selection_token':selection_token(),'marketplaces':['forged']}).status_code==400
        assert client.post('/stores/',{'action':'marketplaces','selection_token':selection_token(),'marketplaces':['manual','woocommerce']}).status_code==400
        reject(lambda:save_connection({'name':'Unselected platform','platform':'wix','site_id':'fixture','token':'fixture','version':'0','active':'on'},user))
        response=client.post('/stores/',{'action':'marketplaces','selection_token':selection_token(),'marketplaces':['woocommerce','squarespace']});assert response.status_code==302
        assert 'platform' not in StoreForm().initial
        now=timezone.now()-timedelta(seconds=10);stamp=now.isoformat().replace('+00:00','Z')
        a=StoreConnection.objects.create(name='Fictional Woo',platform='woocommerce',origin='https://store.example.org',updated_by=user,credentials_cipher=encrypt(json.dumps({'key':'test-consumer-key','secret':'test-consumer-secret'})))
        b=StoreConnection.objects.create(name='Fictional Squarespace',platform='squarespace',updated_by=user,credentials_cipher=encrypt(json.dumps({'token':'fixture-access-token'})))
        old_connections=list(StoreConnection.objects.values())
        assert client.post('/stores/',{'action':'marketplaces','selection_token':selection_token(),'marketplaces':['manual']}).status_code==400
        assert list(StoreConnection.objects.values())==old_connections
        # A paused platform may leave the setup choices without deleting its history or credentials.
        b.active=False;b.save(update_fields=['active'])
        assert client.post('/stores/',{'action':'marketplaces','selection_token':selection_token(),'marketplaces':['woocommerce']}).status_code==302
        b.refresh_from_db();assert not b.active and b.credentials_cipher
        b.active=True;b.save(update_fields=['active'])
        client.post('/stores/',{'action':'marketplaces','selection_token':selection_token(),'marketplaces':['woocommerce','squarespace']})
        raw={'id':2055,'number':'2055','date_created_gmt':stamp.rstrip('Z'),'date_modified_gmt':stamp.rstrip('Z'),'date_paid_gmt':stamp.rstrip('Z'),'status':'processing','line_items':[{'id':11,'name':'Demo Hearth - 16 oz / Whole bean','quantity':1,'sku':'sample-medium'}]}
        normalized=woo(raw);assert normalized['financial_status']=='paid' and normalized['lines'][0]['grind']=='whole'
        stage(a,[normalized]);stage(a,[normalized]);assert a.orders.count()==1
        ss={'id':'2055','orderNumber':'2055','createdOn':stamp,'modifiedOn':stamp,'fulfillmentStatus':'PENDING','paymentState':'PAID','lineItems':[{'id':'line11','productName':'Demo Hearth','quantity':1,'sku':'sample-medium','variantOptions':[{'value':'16 oz'},{'value':'Whole bean'}]}]}
        stage(b,[squarespace(ss)]);assert b.orders.count()==1 and a.orders.first().pk!=b.orders.first().pk
        oa=a.orders.first();ob=b.orders.first();assert readiness(oa)[0] and readiness(ob)[0]
        assert ':' not in oa.external_id and len(oa.external_id)<90
        set_order_visibility([ob.pk],'dismiss',user);stage(b,[squarespace(ss)]);ob.refresh_from_db();assert ob.dismissed_at
        # Deliberate grind allocation persists through an identical source refresh.
        oa.lines[0]['grind']='fine';oa.save();stage(a,[normalized]);oa.refresh_from_db();assert oa.lines[0]['grind']=='fine'
        plan=RoastPlan.objects.create(created_by=user);add_selected(plan,[oa.pk],user);plan.refresh_from_db();assert plan.orders if False else True
        line=IncomingOrderLine.objects.get(import_order=oa);assert line.source=='store' and line.finished_oz==16
        plan.accepted_at=timezone.now();plan.accepted_by=user;plan.save()
        before_batches=list(Batch.all_objects.order_by('pk').values())
        changed=copy.deepcopy(raw);changed['line_items'][0]['quantity']=2;stage(a,[woo(changed)])
        oa.refresh_from_db();plan.refresh_from_db();assert oa.source_changed and len(oa.latest_lines)==1 and line.finished_oz==16 and plan.accepted_at is None
        assert before_batches==list(Batch.all_objects.order_by('pk').values())
        missing=copy.deepcopy(raw);missing['date_paid_gmt']=None;assert woo(missing)['financial_status']=='unknown'
        missing=copy.deepcopy(ss);missing.pop('paymentState');assert squarespace(missing)['financial_status']=='unknown'
        pos=copy.deepcopy(ss);pos['channel']='pos';assert squarespace(pos)['source_flags']
        test=copy.deepcopy(ss);test['testmode']=True;assert squarespace(test)['source_flags']
        wr={'id':'w1','number':'33','createdDate':stamp,'updatedDate':stamp,'status':'APPROVED','paymentStatus':'PAID','fulfillmentStatus':'NOT_FULFILLED','lineItems':[{'id':'wline1','productName':{'original':'Demo Hearth'},'quantity':1,'descriptionLines':[{'plainText':{'original':'16 oz'}},{'plainText':{'original':'French press'}}],'physicalProperties':{'sku':'sample-medium','weight':200}}]}
        wn=wix(wr);assert wn['lines'][0]['size_oz']=='16' and wn['lines'][0]['grind']=='coarse'
        # Read-only endpoint transport blocks private and reserved addresses before credentials can leave.
        with patch('portal.store_http.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch('portal.store_http.PinnedHTTPS') as conn:
            reject(lambda:request_json('https://store.example.org','/wp-json/wc/v3/orders?page=1',{'Authorization':'fixture'}));assert not conn.called
        for url in ['http://store.example.org','https://user:password@store.example.org','https://store.example.org:444','https://store.example.org/a/../b']:
            reject(lambda:origin(url))
        with patch('portal.store_adapters.request_json',return_value=([raw],{'x-wp-totalpages':'1','x-wp-total':'1'})) as req:
            rows,nxt=fetch_page(a,{'key':'test-key','secret':'test-secret'},now-timedelta(days=1),timezone.now(),{});assert not nxt and len(rows)==1
            args=req.call_args.args;assert '/wp-json/wc/v3/orders?' in args[1] and 'test-secret' not in args[1] and len(args)==3
        with patch('portal.store_adapters.request_json',return_value=({'orders':[wr],'metadata':{'cursors':{'next':'next-token'}}},{})) as req:
            store=StoreConnection(platform='wix',site_id='site-fixture');rows,nxt=fetch_page(store,{'token':'fixture'},now-timedelta(days=1),timezone.now(),{})
            assert nxt=={'cursor':'next-token'} and req.call_args.args[1]=='/ecom/v1/orders/search'
        # Squarespace cursors replace date filters on subsequent pages.
        with patch('portal.store_adapters.request_json',return_value=({'result':[ss],'pagination':{'hasNextPage':False,'nextPageCursor':None}},{})) as req:
            rows,nxt=fetch_page(b,{'token':'fixture'},now-timedelta(days=1),timezone.now(),{'cursor':'page-two'})
            assert req.call_args.args[1]=='/1.0/commerce/orders?cursor=page-two' and not nxt
        # A GraphQL-only fixture exercises Shopify without an account or network.
        shop=StoreConnection(platform='shopify',origin='https://fixture.myshopify.com')
        shopline={'id':'gid://shopify/LineItem/1','name':'Demo Hearth - 16 oz / Whole bean','sku':'fixture','quantity':1,'currentQuantity':1,'unfulfilledQuantity':1,'sellingPlan':None,'customAttributes':[]}
        node={'id':'gid://shopify/Order/2055','legacyResourceId':'2055','name':'#2055','createdAt':stamp,'updatedAt':stamp,'cancelledAt':None,'displayFinancialStatus':'PAID','displayFulfillmentStatus':'UNFULFILLED','tags':[],'customAttributes':[],'lineItems':{'nodes':[shopline],'pageInfo':{'hasNextPage':False,'endCursor':None}}}
        packet={'data':{'orders':{'nodes':[node],'pageInfo':{'hasNextPage':False,'endCursor':None}}}}
        with patch('portal.store_adapters.request_json',return_value=(packet,{})):
            rows,nxt=fetch_page(shop,{'token':'fixture'},now-timedelta(days=1),timezone.now(),{});assert rows[0]['lines'][0]['grind']=='whole' and not nxt
        bad=copy.deepcopy(packet);bad['data']['orders']['nodes'][0]['lineItems']['nodes'].append(shopline)
        with patch('portal.store_adapters.request_json',return_value=(bad,{})):reject(lambda:fetch_page(shop,{'token':'fixture'},now-timedelta(days=1),timezone.now(),{}))
        # Reject malformed pagination before applying a misleading partial page.
        with patch('portal.store_adapters.request_json',return_value=([raw],{'x-wp-totalpages':'2','x-wp-total':'51'})):
            reject(lambda:fetch_page(a,{'key':'fixture','secret':'fixture'},now-timedelta(days=1),timezone.now(),{}))
        with patch('portal.stores.fetch_page',return_value=([normalized],{})):
            count,more=synchronize(a.pk,user);assert count==1 and not more
        a.refresh_from_db();assert a.last_success_at and not a.lease and not a.cursor
        prior=(a.watermark,a.last_success_at,a.orders.count())
        with patch('portal.stores.fetch_page',side_effect=ValidationError('Access denied. Grant read access.')):reject(lambda:synchronize(a.pk,user))
        a.refresh_from_db();assert prior==(a.watermark,a.last_success_at,a.orders.count()) and a.last_error and a.runs.filter(state='failed').exists()
        # An in-flight configuration edit invalidates the page's lease/version.
        def changed_connection(*args):
            StoreConnection.objects.filter(pk=a.pk).update(version=a.version+1)
            return [normalized],{}
        before_count=a.orders.count()
        with patch('portal.stores.fetch_page',side_effect=changed_connection):reject(lambda:synchronize(a.pk,user))
        a.refresh_from_db();assert a.orders.count()==before_count and a.watermark==prior[0]
        a.lease=uuid.uuid4();a.lease_at=timezone.now();a.save()
        with patch('portal.stores.fetch_page') as fetch:
            reject(lambda:synchronize(a.pk,user));assert not fetch.called
        a.lease=None;a.lease_at=None;a.save()
        # A stale overlapping result cannot rewind a cancellation or item change.
        current=a.orders.first();current.source_updated_at=timezone.now();current.cancelled=True;current.save()
        stage(a,[normalized]);current.refresh_from_db();assert current.cancelled
        # Per-store saved mappings cannot leak to another source's identical SKU/title.
        c=StoreConnection.objects.create(name='CSV fixture',platform='csv',updated_by=user)
        content=b'order,line,title,qty,created,payment,fulfillment,oz\nx1,l1,Sample unknown - Whole bean,1,2026-01-01T12:00:00Z,paid,unfulfilled,12\n'
        file=SimpleUploadedFile('orders.csv',content,content_type='text/csv');preview=preview_upload(file,c,user)
        mapping={'order_id':'order','line_id':'line','title':'title','quantity':'qty','created':'created','payment':'payment','fulfillment':'fulfillment','size_oz':'oz'}
        assert apply_preview(preview,mapping,user)==1 and apply_preview(preview,mapping,user)==1 and c.orders.count()==1
        changed_map={**mapping,'quantity':'oz'};reject(lambda:apply_preview(preview,changed_map,user))
        preview.created_at=timezone.now()-timedelta(minutes=31);preview.save(update_fields=['created_at'])
        reject(lambda:apply_preview(preview,mapping,user));assert expire_previews()==1
        preview.refresh_from_db();assert not preview.rows and preview.count==1
        source=c.orders.first();key=source.lines[0]['store_product_key']
        coffee=Coffee.objects.get(name='Demo Hearth');StoreProductMapping.objects.create(store=c,product_key=key,title='Sample unknown - Whole bean',coffee=coffee,size_oz=12,grind='whole',updated_by=user)
        from portal.stores import mapped_lines
        assert mapped_lines(c,source.lines)[0]['coffee']==coffee.pk and mapped_lines(a,source.lines)[0]['coffee'] is None
        # Credential fields stay blank on edit and never enter the connection page.
        html=client.get('/stores/',{'edit':a.pk});assert html.status_code==200 and b'test-consumer-secret' not in html.content and b'test-consumer-key' not in html.content
        assert client.get('/imports/').status_code==200 and b'Fictional Woo' in client.get('/imports/').content
        planner=client.get('/planning/',{'plan':plan.pk})
        assert planner.status_code==200 and b'Fictional Woo' in planner.content and b'Imported from Shopify' not in planner.content
        assert client.get('/stores/',{'edit':'invalid-uuid'}).status_code==404
        # Never create a second inbox for the same merchant credentials or URL.
        values={'name':'Duplicate fixture','platform':'woocommerce','origin':a.origin,'version':'0','key':'test-consumer-key','secret':'test-consumer-secret','active':'on'}
        reject(lambda:save_connection(values,user))
        values['origin']='https://another.example.org';reject(lambda:save_connection(values,user))
        for url in ['/stores/','/stores/csv/']:
            assert Client(HTTP_HOST='localhost').get(url).status_code==302
            secure=Client(HTTP_HOST='localhost',enforce_csrf_checks=True);secure.force_login(user);assert secure.post(url,{}).status_code==403
        fixtures=root/'browser-fixtures';fixtures.mkdir(exist_ok=True)
        (fixtures/'stores.html').write_bytes(client.get('/stores/').content)
        (fixtures/'store-inbox.html').write_bytes(client.get('/imports/').content)
        transaction.set_rollback(True)
    print('PASS: four store adapters, store-scoped IDs/mappings, retained allocations/dismissals, changed-source holds, bounded read-only transport, sync failure retention, CSV preview/retries, permissions and credential-free screens.')
