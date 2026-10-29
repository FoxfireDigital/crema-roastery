def run_sourcing_cupping_checks(root,client,user):
    import io,re,zipfile
    from decimal import Decimal
    from datetime import timedelta
    from django.db import transaction
    from django.http import QueryDict
    from django.core.exceptions import ValidationError
    from django.contrib.auth import get_user_model
    from django.test import Client
    from django.utils import timezone
    from portal.models import BeanSupplier,GreenBeanDetails,GreenPurchase,CuppingRecord,SourcingEvent,GreenBeanItem,GreenMovement,Batch
    from portal.sourcing import ticket,save_supplier,save_details,save_purchase,void_purchase
    from portal.cupping import save_tasting,artisan_flavors,radar
    def post(**values):
        q=QueryDict('',mutable=True);q.update({k:str(v) for k,v in values.items()});return q
    def rejected(call):
        try:call()
        except ValidationError:return
        raise AssertionError('Invalid or stale mutation accepted')
    with transaction.atomic():
        before=list(Batch.all_objects.order_by('pk').values())
        item=GreenBeanItem.objects.create(name='Fictional sourcing sample',remaining_oz=16,recorded_by=user)
        p=post(ticket=ticket(user,'supplier'),name='Example Bean Seller',contact='Sample contact',version=0,active='on',notes='<script>unsafe</script>')
        seller=save_supplier(p,user);assert save_supplier(p,user).pk==seller.pk
        assert BeanSupplier.objects.filter(name='Example Bean Seller').count()==1
        old=p.copy();old['ticket']=ticket(user,'supplier');old['pk']=seller.pk
        rejected(lambda:save_supplier(old,user))
        desc=post(ticket=ticket(user,'bean',item=item.pk),version=0,supplier=seller.pk,country='Example country',processing='Washed',supplier_score='86.50')
        save_details(desc,user,item);save_details(desc,user,item)
        assert GreenBeanDetails.objects.get(item=item).supplier_score==Decimal('86.50')
        item.refresh_from_db();assert item.remaining_oz==16
        p=post(ticket=ticket(user,'purchase',versions={str(item.pk):item.version}),item=item.pk,supplier=seller.pk,quantity='2.5',unit='lb',received_on=str(timezone.localdate()),total_cost='50',currency='USD',reference='Demo invoice')
        receipt=save_purchase(p,user);save_purchase(p,user)
        item.refresh_from_db();assert item.remaining_oz==56 and receipt.quantity_oz==40
        assert GreenMovement.objects.filter(item=item).count()==1
        altered=p.copy();altered['quantity']='3';rejected(lambda:save_purchase(altered,user))
        stale=p.copy();stale['ticket']=ticket(user,'purchase',versions={str(item.pk):0});rejected(lambda:save_purchase(stale,user))
        correction=post(ticket=ticket(user,'purchase'),pk=receipt.pk,version=receipt.version,supplier=seller.pk,received_on=str(timezone.localdate()),total_cost='60',currency='USD',reference='Corrected invoice',quantity='9999',unit='lb',item=item.pk)
        save_purchase(correction,user);item.refresh_from_db();receipt.refresh_from_db()
        assert receipt.total_cost==60 and item.remaining_oz==56 and GreenMovement.objects.filter(item=item).count()==1
        correction['ticket']=ticket(user,'purchase');rejected(lambda:save_purchase(correction,user))
        void=post(ticket=ticket(user,'purchase_void'),pk=receipt.pk,version=receipt.version,reason='Duplicate invoice details',stock_unchanged='on')
        void_purchase(void,user);void_purchase(void,user);item.refresh_from_db();assert item.remaining_oz==56
        bad=p.copy();bad['ticket']=ticket(user,'purchase',versions={str(item.pk):item.version});bad['received_on']=str(timezone.localdate()+timedelta(days=1));rejected(lambda:save_purchase(bad,user))
        for quantity in ['NaN','-1','Infinity','0.001']:
            bad=p.copy();bad.update({'ticket':ticket(user,'purchase',versions={str(item.pk):item.version}),'quantity':quantity,'unit':'oz'});rejected(lambda:save_purchase(bad,user))
        tasting=post(ticket=ticket(user,'cupping'),title='Example washed sample',tasted_on=str(timezone.localdate()),green_item=item.pk,taster='Example taster',brew_method='Cupping',notes='<img src=x onerror=alert(1)>',version=0,aroma='7.5',flavor='8')
        note=save_tasting(tasting,user);save_tasting(tasting,user)
        assert note.ratings=={'aroma':'7.5','flavor':'8'} and CuppingRecord.objects.filter(pk=note.pk).count()==1
        assert radar(['A','B','C'],[1,None,2])['points']==''
        assert artisan_flavors({'flavorlabels':['A','B','C'],'flavors':[7,8,9]})['scale']==10
        assert artisan_flavors({'flavorlabels':['A','B','C'],'flavors':[7,float('nan'),9]}) is None
        assert artisan_flavors({'flavorlabels':['A','B','C'],'flavors':[True,1,2]}) is None
        bad=tasting.copy();bad['ticket']=ticket(user,'cupping');bad['pk']=note.pk;bad['version']=note.version;bad['aroma']='11';rejected(lambda:save_tasting(bad,user))
        bad['aroma']='8';bad['version']='0';rejected(lambda:save_tasting(bad,user))
        archive=tasting.copy();archive.update({'ticket':ticket(user,'cupping'),'pk':str(note.pk),'version':str(note.version),'archived':'on','reason':'Sample reviewed'})
        save_tasting(archive,user);note.refresh_from_db();assert note.archived_at
        restore=archive.copy();restore.update({'ticket':ticket(user,'cupping'),'version':str(note.version),'archived':'','reason':'Reopen tasting'})
        save_tasting(restore,user);note.refresh_from_db();assert not note.archived_at
        outsider=get_user_model().objects.create_user(username='sourcing-nonstaff',password='Example-testing-password',is_staff=False)
        wrong=tasting.copy();wrong['ticket']=ticket(outsider,'cupping');rejected(lambda:save_tasting(wrong,user))
        anon=Client(HTTP_HOST='localhost');limited=Client(HTTP_HOST='localhost');limited.force_login(outsider)
        paths=['/suppliers/','/purchases/',f'/green-beans/{item.pk}/details/','/cupping/']
        fixtures=root/'browser-fixtures';fixtures.mkdir(exist_ok=True)
        for name,path in zip(['suppliers','purchases','bean-details','cupping'],paths):
            assert anon.get(path).status_code==302 and limited.get(path).status_code==302
            response=client.get(path);assert response.status_code==200,(path,response.status_code)
            assert 'no-store' in response['Cache-Control']
            (fixtures/(name+'.html')).write_bytes(response.content)
        html=client.get('/cupping/').content.decode();assert '<img src=x onerror' not in html and '&lt;img' in html
        html=client.get('/suppliers/',{'edit':seller.pk}).content.decode();assert '&lt;script&gt;' in html and 'Change history' in html
        assert 'Change history' in client.get('/purchases/',{'edit':receipt.pk}).content.decode()
        response=client.get('/recovery/records/');content=b''.join(response.streaming_content)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert all(name+'.csv' in archive.namelist() for name in ['BeanSupplier','GreenBeanDetails','GreenPurchase','CuppingRecord','SourcingEvent'])
        item.refresh_from_db();assert item.remaining_oz==56 and before==list(Batch.all_objects.order_by('pk').values())
        transaction.set_rollback(True)
    print('PASS: sourcing receipts, replay/stale protection, costs, tastings, safe charts, permissions and record exports.')

