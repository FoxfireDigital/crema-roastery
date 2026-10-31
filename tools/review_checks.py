"""Regressions for the frozen-beta maintainer review findings."""
def run_review_checks(client,user):
    import csv,io
    from datetime import timedelta
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from django.test import override_settings
    from django.utils import timezone
    from portal.models import Batch,Coffee,CustomOrder,Roaster,Shift
    with transaction.atomic():
        employee=get_user_model().objects.create_user('+1-2')
        now=timezone.now();Shift.objects.create(user=employee,started_at=now-timedelta(hours=2),ended_at=now-timedelta(hours=1))
        response=client.get('/timesheets/export/');assert response.status_code==200
        rows=list(csv.reader(io.StringIO(response.content.decode())))
        assert any(row and row[0]=="'+1-2" for row in rows),'Employee names must remain literal spreadsheet text'
        Shift.objects.create(user=user,started_at=now-timedelta(hours=2),ended_at=now-timedelta(hours=1))
        for zone in ['UTC','Asia/Tokyo']:
            with override_settings(TIME_ZONE=zone):
                with timezone.override(zone):
                    response=client.get('/payroll/export/');assert response.status_code==200
                    rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
                    assert rows[0][1:4]==[f'Work date ({zone})',f'Clock segment start ({zone})',f'Clock segment end ({zone})']
                    assert any(row[2].endswith('+09:00' if zone=='Asia/Tokyo' else '+00:00') for row in rows[1:] if len(row)>2),'CSV timestamp offsets must agree with its timezone heading'
                    page=client.get('/payroll/');assert page.status_code==200 and ('In / out ('+zone+')').encode() in page.content
        coffee=Coffee.objects.get(name='Demo Single Origin');roaster=Roaster.objects.filter(active=True).first()
        order=CustomOrder.objects.create(customer_name='Fictional review order',coffee=coffee,roast_level=coffee.standard_roast,bags_5lb=1,created_by=user)
        before=Batch.objects.count()
        for weight,machine in [('NaN',roaster.pk),('sNaN',roaster.pk),('Infinity',roaster.pk),('-Infinity',roaster.pk),('1','bad'),('1',str(2**100))]:
            response=client.post(f'/orders/{order.pk}/',{'action':'add_batch','green_oz':weight,'roaster_id':machine})
            assert response.status_code==302,(weight,machine,response.status_code)
            assert Batch.objects.count()==before,'Malformed custom weights/machines must not create production'
        transaction.set_rollback(True)
    print('PASS: formula-safe legacy timesheets, configured payroll timezone/offsets, and non-finite custom input rejection without production writes.')
