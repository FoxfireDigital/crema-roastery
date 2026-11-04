"""Operator evidence controls stay visible and remain bound to the actual batch."""
def run_evidence_actions_checks(client,user):
    from decimal import Decimal
    from django.db import transaction
    from django.utils import timezone
    from django.contrib.auth import get_user_model
    from django.test import Client
    from portal.models import Coffee,Roaster,RoastPlan,RoastGroup,IncomingOrderLine,PlannedBatch,Batch
    from portal.roast_sheet import row_token
    with transaction.atomic():
        coffee=Coffee.objects.get(name='Demo Hearth');machine=Roaster.objects.filter(active=True).first()
        plan=RoastPlan.objects.create(created_by=user,accepted_at=timezone.now(),use_roasted_stock=False)
        group=RoastGroup.objects.create(plan=plan,key='evidence-controls',coffee=coffee,roast_level='Medium')
        IncomingOrderLine.objects.create(group=group,product_coffee=coffee,finished_oz=16,packaging=[{'bags':1,'size_oz':'16'}],grind='whole')
        row=PlannedBatch.objects.create(group=group,roaster=machine,green_oz=20)
        html=client.get('/').content.decode()
        fragment=html.split('data-endpoint="/roasts/'+str(row.pk)+'/"',1)[1].split('</tr>',1)[0]
        assert '>Capture photo</a>' in fragment and '>Upload .alog</a>' in fragment
        assert 'aria-disabled="true"' in fragment and 'Available once' in fragment
        row=PlannedBatch.objects.select_related('group__plan','batch','roaster').get(pk=row.pk)
        response=client.post('/roasts/'+str(row.pk)+'/',{'revision':row_token(row),'measured_at':'on','roasted_oz':'17.0'})
        assert response.status_code==200,response.content
        row.refresh_from_db();batch=row.batch
        html=client.get('/').content.decode();fragment=html.split('data-endpoint="/roasts/'+str(row.pk)+'/"',1)[1].split('</tr>',1)[0]
        capture='/batches/'+str(batch.pk)+'/photos/?capture=1#capture';upload='/batches/'+str(batch.pk)+'/artisan/upload/'
        assert capture in fragment and upload in fragment
        source=fragment.split('data-label="Date / plan"',1)[1].split('</td>',1)[0]
        assert 'row-photo' not in source,'Photo action was buried in source details'
        detail=client.get('/batches/'+str(batch.pk)+'/').content.decode()
        assert detail.index(capture)<detail.index('id="artisan-logs"') and detail.index('>Upload .alog</a>')<detail.index('id="artisan-logs"')
        ordinary=client.get('/batches/'+str(batch.pk)+'/photos/')
        capture_page=client.get('/batches/'+str(batch.pk)+'/photos/?capture=1')
        assert ordinary.status_code==capture_page.status_code==200
        assert b'data-start-camera="0"' in ordinary.content and b'data-start-camera="1"' in capture_page.content
        assert b'id="capture"' in capture_page.content
        # A GET opens the browser preview only; it never creates a photo or alters the roast.
        assert batch.photos.count()==0
        batch.refresh_from_db();assert batch.green_oz==20 and batch.roasted_oz==17
        viewer=get_user_model().objects.create_user('evidence-viewer',password='Synthetic-viewer-only-192!')
        restricted=Client(HTTP_HOST='localhost');restricted.force_login(viewer)
        assert b'>Capture photo</a>' not in restricted.get('/').content
        assert restricted.get(upload).status_code==403
        assert restricted.get('/batches/'+str(batch.pk)+'/photos/?capture=1').status_code==403
        transaction.set_rollback(True)
    print('PASS: visible batch evidence actions, roast-state availability, exact batch routing, camera opt-in and staff permissions.')
