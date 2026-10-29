"""Administrator recovery status and portable business-record exports."""
from datetime import timedelta
from pathlib import Path
import csv,io,json,re,tempfile,zipfile
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import FileResponse,HttpResponseForbidden,Http404
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def backup_root():return Path(getattr(settings,'COFFEE_BACKUP_ROOT','/var/lib/coffee-backups'))


def backup_status():
    try:
        data=json.loads((backup_root()/'status.json').read_text())
        stamp=parse_datetime(data.get('verified_at',''))
        if stamp and timezone.is_naive(stamp):stamp=timezone.make_aware(stamp)
        name=data.get('filename','')
        data['downloadable']=bool(re.fullmatch(r'routine-\d{8}T\d{6}Z\.tar\.gz',name) and (backup_root()/name).is_file())
        data['verified_at']=stamp;data['stale']=not stamp or stamp<timezone.now()-timedelta(hours=36)
        return data
    except (OSError,ValueError,TypeError):return {'stale':True,'downloadable':False,'error':'A verified routine backup is not available yet.'}


def offsite_status():
    try:
        data=json.loads((backup_root()/'offsite-status.json').read_text(encoding='utf-8'))
        if not isinstance(data,dict):raise ValueError('Invalid offsite status')
        result={key:data.get(key) for key in ['state','reason','account','folder_url','last_uploaded_at','last_restore_test','recovery_key_saved']}
        result['last_check_at']=data.get('last_check_at') or data.get('last_uploaded_at')
        for key in ['last_uploaded_at','last_restore_test','last_check_at']:
            stamp=parse_datetime(result[key]) if isinstance(result[key],str) else None
            result[key]=timezone.make_aware(stamp) if stamp and timezone.is_naive(stamp) else stamp
        result['upload_stale']=not result['last_uploaded_at'] or not timedelta(minutes=-5)<=timezone.now()-result['last_uploaded_at']<=timedelta(hours=36)
        result['check_stale']=not result['last_check_at'] or not timedelta(minutes=-5)<=timezone.now()-result['last_check_at']<=timedelta(hours=3)
        result['stale']=result['upload_stale'] or result['check_stale']
        if result['state']=='verified' and result['upload_stale']:result['reason']='A recent offsite upload is not confirmed. Existing verified backups are retained; check the cloud task.'
        elif result['state']=='verified' and result['check_stale']:result['reason']='The hourly backup connection has not confirmed a successful check in the last three hours. Existing verified backups are retained; check the cloud task.'
        return result
    except (OSError,ValueError,TypeError):return {'state':'not_configured','reason':'An automatic off-NAS backup is not confirmed.'}


@staff_member_required
def recovery_page(request):
    if not request.user.is_superuser:return HttpResponseForbidden('Administrator access required.')
    return render(request,'portal/recovery.html',{'backup':backup_status(),'offsite':offsite_status()})


@staff_member_required
def download_backup(request):
    if not request.user.is_superuser:return HttpResponseForbidden('Administrator access required.')
    status=backup_status()
    if not status.get('downloadable'):raise Http404('Verified backup unavailable.')
    root=backup_root().resolve();path=(root/status['filename']).resolve()
    if path.parent!=root:raise Http404()
    response=FileResponse(path.open('rb'),as_attachment=True,filename=status['filename'],content_type='application/gzip')
    response['Cache-Control']='no-store';return response


def csv_cell(value):
    if isinstance(value,(dict,list)):value=json.dumps(value,default=str,ensure_ascii=False)
    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):value="'"+value
    return value


@staff_member_required
def export_records(request):
    if not request.user.is_superuser:return HttpResponseForbidden('Administrator access required.')
    from . import models
    from django.contrib.auth import get_user_model
    names=['StoreProductMapping','StoreSyncRun','StoreEvent','PortalConfiguration','BeanSupplier','GreenBeanDetails','GreenPurchase','CuppingRecord','SourcingEvent','SupplyItem','SupplyMovement','FlavorSupplyRate','MaintenanceTask','MaintenanceService','Coffee','LabelVariant','Roaster','RoastPlan','RoastGroup','IncomingOrderLine','WholesaleOrder','WholesaleCustomer',
           'GreenBeanItem','GreenRecipe','GreenBatchUsage','GreenMovement','GreenRecipeEvent','CustomerPreferenceEvent','OrderLookupEvent','PlannedBatch','Batch','HistoricalRoast','ImportOrder','ProductMapping','PackingProgress','PackingProgressEvent',
           'Shift','WorkBreak','TimeEvent','TimeAdjustment','HoursPayment','HourlyRate','PayrollAccess','RoastedStock','RoastedStockAllocation','PlanEvent','SubscriptionContract','LabelPrintRun']
    output=tempfile.SpooledTemporaryFile(max_size=5*1024*1024,mode='w+b')
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('README.txt','Business records exported from Crema. Deleted rows are retained. Times include timezone offsets. IDs link the CSV files. This export excludes passwords, Shopify credentials and binary label artwork; use the full recovery backup for disaster recovery.\n')
        for name in names:
            model=getattr(models,name);manager=getattr(model,'all_objects',model.objects)
            stream=io.StringIO(newline='');writer=csv.writer(stream);fields=[field.name for field in model._meta.concrete_fields]
            writer.writerow(fields)
            for row in manager.order_by('pk').values_list(*fields).iterator(chunk_size=1000):writer.writerow([csv_cell(v) for v in row])
            archive.writestr(name+'.csv','\ufeff'+stream.getvalue())
        stream=io.StringIO(newline='');writer=csv.writer(stream);writer.writerow(['id','username'])
        writer.writerows((pk,csv_cell(name)) for pk,name in get_user_model().objects.values_list('pk','username'))
        archive.writestr('Users.csv','\ufeff'+stream.getvalue())
    output.seek(0);response=FileResponse(output,as_attachment=True,filename='coffee-records-'+str(timezone.localdate())+'.zip',content_type='application/zip')
    response['Cache-Control']='no-store';return response
