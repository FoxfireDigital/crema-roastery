"""Preview, map and atomically stage orders from a general UTF-8 CSV."""
import csv,io,json,hashlib
from datetime import timedelta
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods,require_GET
from .models import StoreConnection,OrderImportPreview,StoreEvent
from .store_adapters import make_line,finish
from .stores import stage

COLUMNS=[('order_id','Order ID',True),('line_id','Line item ID',True),('reference','Order number',False),('title','Product / coffee title',True),('quantity','Number of bags / units',True),('created','Received time (ISO timestamp with timezone)',True),('updated','Last updated time (optional)',False),('payment','Payment status',True),('fulfillment','Fulfillment status',True),('sku','SKU',False),('options','Size / grind / roast options',False),('size_oz','Net coffee ounces per bag (not shipping weight)',False),('subscription','Subscription / selling plan',False),('notes','Order instructions',False),('customer','Customer name (only if enabled for this store)',False)]

class UploadForm(forms.Form):
    store=forms.ModelChoiceField(queryset=StoreConnection.objects.filter(active=True),label='Store that owns these order IDs')
    document=forms.FileField(label='UTF-8 orders CSV, up to 5 MB')
    def clean_document(self):
        file=self.cleaned_data['document']
        if not 0<file.size<=5*1024*1024:raise forms.ValidationError('Choose an orders CSV no larger than 5 MB.')
        return file

class ColumnsForm(forms.Form):
    def __init__(self,*args,headers,**kwargs):
        super().__init__(*args,**kwargs)
        for key,label,required in COLUMNS:self.fields[key]=forms.ChoiceField(label=label,required=required,choices=[('','Choose column' if required else 'Not provided')]+[(h,h) for h in headers])

def preview_upload(file,store,actor):
    try:
        reader=csv.DictReader(io.StringIO(file.read().decode('utf-8-sig'),newline=''));headers=reader.fieldnames or []
        if not headers or len(headers)>80 or len(set(headers))!=len(headers) or any(not h.strip() or len(h)>150 for h in headers):raise ValidationError('Use distinct nonempty column headings, at most 80 columns.')
        rows=[]
        for row in reader:
            if len(rows)>=5000 or None in row or any(v is None or len(v)>4000 for v in row.values()):raise ValidationError('Use at most 5,000 complete CSV rows; individual cells must be under 4,000 characters.')
            rows.append(row)
        if not rows:raise ValidationError('This CSV contains no orders.')
    except (UnicodeError,csv.Error):raise ValidationError('Use a readable UTF-8 orders CSV.')
    return OrderImportPreview.objects.create(store=store,created_by=actor,headers=headers,rows=rows,store_version=store.version)

def normalize_csv(preview,mapping):
    grouped={}
    for row in preview.rows:
        v={key:(row.get(mapping.get(key,'')) or '').strip() for key,_,_ in COLUMNS}
        title=v['title']+(' - '+v['options'] if v['options'] else '')
        line=make_line(v['line_id'],title,v['quantity'],v['sku'],v['subscription'])
        if v['size_oz']:
            try:
                size=Decimal(v['size_oz'])
                if not size.is_finite() or not Decimal('.1')<=size<=160000 or size!=size.quantize(Decimal('.01')):raise ValueError()
            except (ValueError,ArithmeticError):raise ValidationError('Net coffee ounces must be positive with at most two decimal places.')
            line['size_oz']=str(size);line['source_total']=str(size*line['quantity'])
        payment='paid' if v['payment'].casefold() in ['paid','fully paid','fully_paid','fully_paid'] else v['payment'].casefold() or 'unknown'
        fulfillment={'unfulfilled':'unfulfilled','not fulfilled':'unfulfilled','not_fulfilled':'unfulfilled','pending':'unfulfilled','fulfilled':'fulfilled','partially fulfilled':'partial','partially_fulfilled':'partial'}.get(v['fulfillment'].casefold(),'unknown')
        core=(v['created'],v['updated'] or v['created'],payment,fulfillment,v['notes'],v['customer'] if preview.store.include_customer_names else '')
        entry=grouped.setdefault(v['order_id'],{'core':core,'reference':v['reference'] or v['order_id'],'lines':[]})
        if entry['core']!=core or entry['reference']!=(v['reference'] or v['order_id']):raise ValidationError('Rows for the same order disagree on its dates, status, reference or instructions.')
        entry['lines'].append(line)
    result=[]
    for identity,entry in grouped.items():
        created,updated,payment,fulfillment,notes,customer=entry['core']
        result.append(finish(identity,entry['reference'],created,updated,entry['lines'],payment,fulfillment,payment in ['cancelled','canceled'],notes,customer))
    return result

def apply_preview(preview,values,actor):
    form=ColumnsForm(values,headers=preview.headers)
    if not form.is_valid():raise ValidationError('Choose columns for every required field from this preview.')
    fingerprint=hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()
    with transaction.atomic():
        preview=OrderImportPreview.objects.select_for_update().select_related('store').get(pk=preview.pk,created_by=actor)
        if preview.created_at<timezone.now()-timedelta(minutes=30):raise ValidationError('This CSV preview expired. Upload the current export again.')
        if preview.applied_at:
            if fingerprint!=preview.mapping_hash:raise ValidationError('This preview was already applied with different columns. Upload a new preview for another change.')
            return preview.count
        store=StoreConnection.objects.select_for_update().get(pk=preview.store_id)
        if not store.active or store.version!=preview.store_version:raise ValidationError('The store settings changed. Upload and review the CSV again.')
        data=normalize_csv(preview,values);total=stage(store,data)
        store.csv_mapping=values;store.save(update_fields=['csv_mapping'])
        preview.applied_at=timezone.now();preview.mapping_hash=fingerprint;preview.count=total;preview.save(update_fields=['applied_at','mapping_hash','count'])
        StoreEvent.objects.create(store=store,actor=actor,action='csv_staged',details={'preview':str(preview.pk),'orders':total})
        return total

@staff_member_required
@require_http_methods(['GET','POST'])
def csv_import(request):
    upload=UploadForm(request.POST or None,request.FILES or None);preview=None;columns=None;error='';status=200
    try:
        if request.method=='POST':
            if request.POST.get('action')=='preview':
                if not upload.is_valid():raise ValidationError([str(e) for errors in upload.errors.values() for e in errors])
                preview=preview_upload(upload.cleaned_data['document'],upload.cleaned_data['store'],request.user)
            elif request.POST.get('action')=='apply':
                preview=get_object_or_404(OrderImportPreview.objects.select_related('store'),pk=request.POST.get('preview'),created_by=request.user)
                columns=ColumnsForm(request.POST,headers=preview.headers)
                if not columns.is_valid():raise ValidationError('Choose columns for every required field.')
                if request.POST.get('confirmed')!='on':raise ValidationError('Confirm that these are real orders and the selected columns are correct.')
                count=apply_preview(preview,columns.cleaned_data,request.user);messages.success(request,f'Loaded {count} orders for review. No production demand was added.');return redirect('/imports/')
            else:raise ValidationError('Choose Preview before applying an orders CSV.')
        if preview and columns is None:
            defaults={key:preview.store.csv_mapping.get(key,'') for key,_,_ in COLUMNS}
            columns=ColumnsForm(headers=preview.headers,initial=defaults)
    except ValidationError as exc:error='; '.join(exc.messages);status=400
    return render(request,'portal/store_csv.html',{'upload':upload,'columns':columns,'preview':preview,'sample_rows':preview.rows[:3] if preview else [],'error':error},status=status)

@staff_member_required
@require_GET
def csv_example(request):
    response=HttpResponse(content_type='text/csv');response['Content-Disposition']='attachment; filename="crema-orders-example.csv"';writer=csv.writer(response)
    writer.writerow(['Order ID','Line ID','Order number','Product','Quantity','Received','Payment','Fulfillment','SKU','Options'])
    writer.writerow(['demo-order-1','demo-line-1','#DEMO-1','Demo Hearth','2','2026-01-01T12:00:00Z','paid','unfulfilled','demo-hearth-16','16 oz / Whole bean'])
    return response


def expire_previews():
    # Keep audit metadata, but do not retain an expired upload's raw rows.
    return OrderImportPreview.objects.filter(created_at__lt=timezone.now()-timedelta(minutes=30)).exclude(rows=[]).update(rows=[])
