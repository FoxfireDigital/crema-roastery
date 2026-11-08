"""Setup guidance must show gaps without changing operational configuration."""
def run_onboarding_checks(client, owner):
    from django.contrib.auth import get_user_model
    from django.db import connection, transaction
    from django.test import Client, override_settings
    from django.test.utils import CaptureQueriesContext
    from portal.models import Coffee, Roaster, PortalConfiguration
    from portal.onboarding import checklist
    with transaction.atomic():
        with CaptureQueriesContext(connection) as queries:
            report = checklist(owner)
            response = client.get('/getting-started/')
            assert response.status_code == 200
            assert client.get('/setup/').status_code == 200
        assert not any(q['sql'].lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ')) for q in queries), 'Setup GET wrote data'
        assert len(report['steps']) == 10 and report['core_total'] == 3
        by_key = {s['key']: s for s in report['steps']}
        assert by_key['people']['state'] == by_key['recovery']['state'] == 'Review in person'
        assert not by_key['costs']['ready'] and not by_key['inventory']['ready']
        # Configured catalogs are not proof that every minimum has been reviewed.
        machine = Roaster.objects.filter(active=True).first()
        Roaster.objects.filter(pk=machine.pk).update(min_green_oz=0)
        assert not next(s for s in checklist(owner)['steps'] if s['key'] == 'machines')['ready']
        Roaster.objects.filter(pk=machine.pk).update(min_green_oz=1,max_green_oz=0)
        assert any('limits' in i for i in next(s for s in checklist(owner)['steps'] if s['key'] == 'machines')['issues'])
        sample = Coffee.objects.filter(active=True).first()
        Coffee.objects.filter(pk=sample.pk).update(name='<script>alert(1)</script>')
        response = client.get('/getting-started/')
        assert b'<script>alert(1)</script>' not in response.content and b'&lt;script&gt;' in response.content
        # Optional manual-only use needs no saved merchant credentials.
        config = PortalConfiguration.objects.get(pk=1)
        PortalConfiguration.objects.filter(pk=1).update(marketplaces=['manual'])
        assert next(s for s in checklist(owner)['steps'] if s['key'] == 'orders')['ready']
        staff = get_user_model().objects.create_user('setup-staff',is_staff=True)
        limited = Client(HTTP_HOST='localhost');limited.force_login(staff)
        assert limited.get('/getting-started/').status_code == 200
        assert b'href="/admin/auth/user/"' not in limited.get('/getting-started/').content
        normal = get_user_model().objects.create_user('setup-employee')
        limited.force_login(normal)
        assert limited.get('/getting-started/').status_code == 302
        assert Client(HTTP_HOST='localhost').get('/getting-started/').status_code == 302
        with override_settings(PORTAL_DEMO_MODE=True):
            response = client.get('/getting-started/');assert response.status_code == 200
            assert b'Fictional setup preview' in response.content
            assert b'href="/stores/"' not in response.content and b'href="/recovery/"' not in response.content
            assert client.get('/setup/').status_code == 403
            assert client.post('/getting-started/',{}).status_code == 405
        transaction.set_rollback(True)
    print('PASS: setup gaps, manual-only use, machine minimums, escaping, read-only GETs, staff access and confined demo preview.')
