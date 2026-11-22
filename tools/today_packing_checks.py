"""Shared-screen writes and demo boundaries, using fictional transactional data."""
def run_today_packing_checks(client,owner):
    import re
    from decimal import Decimal
    from django.db import transaction
    from django.test import Client,override_settings
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from portal.models import Coffee,RoastPlan,RoastGroup,IncomingOrderLine,PackingProgress,PackingProgressEvent
    from portal.packing import packing_context,progress_token
    with transaction.atomic():
        operator=get_user_model().objects.create_user('fictional-operator',password='Fictional-only-test-5825!')
        admin=get_user_model().objects.create_user('fictional-admin',password='Fictional-only-test-5826!',is_staff=True)
        coffee=Coffee.objects.get(name='Demo Hearth')
        plans=[RoastPlan.objects.create(created_by=owner,accepted_at=timezone.now()) for _ in range(2)]
        lines=[]
        for n,plan in enumerate(plans):
            group=RoastGroup.objects.create(plan=plan,key='test-shared-'+str(n),coffee=coffee,roast_level='Medium')
            lines.append(IncomingOrderLine.objects.create(group=group,customer='Fictional shared customer',reference='QA-SHARED-'+str(n),finished_oz=Decimal(16),grind='regular',packaging=[{'size_oz':'16','bags':1}]))
        operator_client=Client(HTTP_HOST='localhost');operator_client.force_login(operator)
        html=operator_client.get('/').content.decode()
        assert html.count('<details class="card today-packing-card"')==2
        assert 'Label requirements</h2>' not in html
        for plan in plans:assert f'/labels/?plan={plan.pk}' in html
        assert 'name="ground_at"' in html and 'Adjust grind / bags' not in html
        assert html.index('name="labeled_at"') < html.index('name="ground_at"') < html.index('name="bagged_at"') < html.index('name="sealed_at"')
        line=IncomingOrderLine.objects.select_related('group__plan').get(pk=lines[0].pk);initial=progress_token(line,None)
        result=operator_client.post(f'/packing/{line.pk}/progress/',{'revision':initial,'ground_at':'on','bagged_at':'on'})
        assert result.status_code==400 and not PackingProgress.objects.filter(line=line).exists()
        result=operator_client.post(f'/packing/{line.pk}/progress/',{'revision':initial,'labeled_at':'on'})
        assert result.status_code==200 and result.json()['steps']['labeled_at'] and not result.json()['steps']['ground_at']
        result=operator_client.post(f'/packing/{line.pk}/progress/',{'revision':result.json()['revision'],'labeled_at':'on','ground_at':'on','bagged_at':'on'})
        assert result.status_code==200,result.content
        assert PackingProgress.objects.get(line=line).bagged_at
        bagging=operator_client.get(f'/packing/?plan={plans[0].pk}')
        assert bagging.context['rows'][0]['progress_revision']==result.json()['revision']
        assert bagging.context['rows'][0]['progress'].bagged_at
        # A second screen must never silently overwrite a newer checklist.
        stale=client.post(f'/packing/{line.pk}/progress/',{'revision':initial})
        assert stale.status_code==409
        result=client.post(f'/packing/{line.pk}/progress/',{'revision':result.json()['revision'],'ground_at':'on','bagged_at':'on','labeled_at':'on','sealed_at':'on'})
        assert result.status_code==200
        today=operator_client.get('/')
        assert today.context['packing_lists'][0]['completed']==1 and today.context['packing_lists'][1]['completed']==0
        assert PackingProgressEvent.objects.filter(progress__line=line).count()==3
        # Real CSRF validation and non-staff edit boundaries apply on Today too.
        csrf_client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');csrf_client.force_login(operator)
        assert csrf_client.post(f'/packing/{line.pk}/progress/',{'revision':result.json()['revision']}).status_code==403
        assert operator_client.post(f'/packing/{lines[1].pk}/',{}).status_code==302
        form=packing_context(plans[1])['rows'][0]['form']
        data={**form.initial,'grind':'coarse','size_oz':'16','bags':'1','return_to':'today'}
        response=client.post(f'/packing/{lines[1].pk}/',data)
        assert response['Location']==f'/#packing-plan-{plans[1].pk}'
        lines[1].refresh_from_db();assert lines[1].grind=='coarse'
        # Never allow a return URL to become an open redirect.
        form=packing_context(plans[1])['rows'][0]['form'];data.update(revision=form.initial['revision'],return_to='https://invalid.example/')
        assert client.post(f'/packing/{lines[1].pk}/',data)['Location']==f'/packing/?plan={plans[1].pk}'
        # Previously saved packing steps can be kept while labeling is added.
        packed_at=timezone.now()
        old_progress=PackingProgress.objects.create(line=lines[1], ground_at=packed_at, bagged_at=packed_at)
        assert operator_client.post(f'/packing/{lines[1].pk}/progress/',{'revision':progress_token(lines[1],old_progress),
            'labeled_at':'on','ground_at':'on','bagged_at':'on'}).status_code==200
        old_progress.refresh_from_db();assert old_progress.labeled_at and old_progress.bagged_at==packed_at
        plans[0].closed_at=timezone.now();plans[0].save(update_fields=['closed_at'])
        assert operator_client.post(f'/packing/{line.pk}/progress/',{'revision':result.json()['revision']}).status_code==404
        assert f'id="packing-plan-{plans[0].pk}"' not in operator_client.get('/').content.decode()
        blocked=['/recovery/','/stores/','/shopify/','/setup/','/imports/find/','/admin/auth/user/','/admin/auth/user/add/','/admin/password_change/','/admin/portal/storeconnection/','/admin/portal/portalconfiguration/','/admin/portal/payrollaccess/']
        with override_settings(PORTAL_DEMO_MODE=True,STORAGES={'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}}):
            for actor in [owner,admin,operator]:
                trial=Client(HTTP_HOST='localhost');trial.force_login(actor)
                for path in blocked:
                    assert trial.get(path).status_code==403,(actor.username,path)
                    assert trial.post(path,{}).status_code==403,(actor.username,path)
                assert trial.get('/').status_code==200 and trial.get('/packing/').status_code==200
            assert client.get('/admin/portal/coffee/').status_code==200
            assert operator_client.get('/admin/portal/coffee/').status_code==302
        assert client.get('/setup/').status_code==200,'Demo restrictions leaked into ordinary installations'
        transaction.set_rollback(True)
    print('PASS: Today/Bagging shared progress, stale/CSRF guards, per-plan counts, closed-plan protection, safe return and demo role boundaries.')
