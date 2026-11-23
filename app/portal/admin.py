from django.contrib import admin
from .models import Coffee,LabelVariant,Roaster,Batch,CustomOrder,Shift,WorkBreak,TimeEvent,TimeAdjustment,HistoricalRoast,ProductMapping,HoursPayment,BatchProgressEvent,PlanEvent,BatchMergeEvent,PackingEvent,LabelPrintRun
admin.site.site_header='Crema Administration'
from django.forms.models import BaseInlineFormSet
from django.core.exceptions import ValidationError
from .models import ProductBundle,ProductBundleItem

class BundleItemFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):return
        rows=[form.cleaned_data for form in self.forms if form.cleaned_data and not form.cleaned_data.get('DELETE')]
        if len(rows)>20 or self.instance.active and not rows:raise ValidationError('An active box needs between one and twenty coffee rows.')

class BundleItemInline(admin.TabularInline):
    model=ProductBundleItem
    formset=BundleItemFormSet
    extra=1

@admin.register(ProductBundle)
class ProductBundleAdmin(admin.ModelAdmin):
    list_display=['name','source_title','sku','default_grind','active','updated_at']
    list_filter=['active']
    search_fields=['name','source_title','sku']
    readonly_fields=['updated_by','updated_at']
    inlines=[BundleItemInline]
    def save_model(self,request,obj,form,change):
        obj.updated_by=request.user
        super().save_model(request,obj,form,change)
@admin.register(Coffee)
class CoffeeAdmin(admin.ModelAdmin):
    list_display=['name','kind','standard_roast','experimental','roast_base','flavor_base_allowed','bulk_stock_enabled','active']
    list_filter=['kind','active']
    search_fields=['name']
    actions=['deactivate']
    def formfield_for_foreignkey(self,db_field,request,**kwargs):
        if db_field.name=='roast_base':kwargs['queryset']=Coffee.objects.filter(active=True,standard_roast='Medium').exclude(kind='flavored').filter(flavor_base_allowed=True)
        return super().formfield_for_foreignkey(db_field,request,**kwargs)
    @admin.action(description='Deactivate selected coffees (preserve history)')
    def deactivate(self,request,queryset): queryset.update(active=False)
@admin.register(LabelVariant)
class LabelVariantAdmin(admin.ModelAdmin):
    list_display=['name','customer','coffee','active']
    list_filter=['active','customer']
    search_fields=['name','coffee__name']
@admin.register(Roaster)
class RoasterAdmin(admin.ModelAdmin):
    list_display=['name','min_green_oz','max_green_oz','active']
@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display=['date','coffee','roaster','operator','green_oz','roasted_oz','roast_level','status']
    list_filter=['date','roaster','coffee','roast_level']
    search_fields=['coffee__name','operator__username']
    readonly_fields=['created_at','planned_group','merged_into']
@admin.register(CustomOrder)
class CustomOrderAdmin(admin.ModelAdmin):
    list_display=['id','customer_name','coffee','roast_level','label_variant','target_finish_temp_f','bags_5lb','due_date','status']
    list_filter=['coffee','roast_level','due_date']
    search_fields=['customer_name','order_reference']
    readonly_fields=['created_at','created_by','fulfilled_at','cancelled_at']
    def save_model(self,request,obj,form,change):
        if not change: obj.created_by=request.user
        super().save_model(request,obj,form,change)
@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display=['user','started_at','ended_at','removed_at']
    list_filter=['user','removed_at']
    readonly_fields=['user','started_at','ended_at','removed_at']
    def has_add_permission(self,request): return False
    def has_delete_permission(self,request,obj=None): return False
@admin.register(WorkBreak)
class WorkBreakAdmin(admin.ModelAdmin):
    list_display=['shift','started_at','ended_at']
    readonly_fields=['shift','started_at','ended_at']
    def has_add_permission(self,request): return False
    def has_delete_permission(self,request,obj=None): return False
@admin.register(TimeEvent)
class TimeEventAdmin(admin.ModelAdmin):
    list_display=['user','action','at','shift']
    readonly_fields=['user','action','at','shift']
    def has_add_permission(self,request): return False
    def has_delete_permission(self,request,obj=None): return False

@admin.register(TimeAdjustment)
class TimeAdjustmentAdmin(admin.ModelAdmin):
    list_display=['shift','actor','at','note']
    readonly_fields=['shift','actor','at','before','after','note']
    def has_add_permission(self,request): return False
    def has_delete_permission(self,request,obj=None): return False

@admin.register(HistoricalRoast)
class HistoricalRoastAdmin(admin.ModelAdmin):
    list_display=['date','operator_name','coffee_name','coffee','roast_level','green_oz','roasted_oz','sheet','row_number']
    search_fields=['coffee_name','operator_name']
    list_filter=['sheet','roast_level']
    readonly_fields=[f.name for f in HistoricalRoast._meta.fields if f.name!='coffee']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False

@admin.register(ProductMapping)
class ProductMappingAdmin(admin.ModelAdmin):
    list_display=['title','sku','coffee','label_variant','size_oz','skip']
    search_fields=['title','sku','coffee__name']
    readonly_fields=['fingerprint','updated_by','updated_at']
    def has_add_permission(self,request):return False

@admin.register(HoursPayment)
class HoursPaymentAdmin(admin.ModelAdmin):
    list_display=['paid_on','payer','payee','through_date','credited_seconds','amount','voided_at']
    readonly_fields=[f.name for f in HoursPayment._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False

@admin.register(BatchProgressEvent)
class BatchProgressEventAdmin(admin.ModelAdmin):
    list_display=['batch','actor','action','at']
    readonly_fields=[f.name for f in BatchProgressEvent._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False

@admin.register(PlanEvent)
class PlanEventAdmin(admin.ModelAdmin):
    list_display=['plan','actor','action','at']
    readonly_fields=[f.name for f in PlanEvent._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False


@admin.register(BatchMergeEvent)
class BatchMergeEventAdmin(admin.ModelAdmin):
    list_display=['source','target','actor','at']
    readonly_fields=[f.name for f in BatchMergeEvent._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False


@admin.register(PackingEvent)
class PackingEventAdmin(admin.ModelAdmin):
    list_display=['line','actor','at']
    readonly_fields=[f.name for f in PackingEvent._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False

@admin.register(LabelPrintRun)
class LabelPrintRunAdmin(admin.ModelAdmin):
    list_display=['id','created_at','created_by','plan','status']
    readonly_fields=[f.name for f in LabelPrintRun._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False

from .models import BeanSupplier,GreenBeanDetails,GreenPurchase,CuppingRecord,SourcingEvent
class SourcingReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self,request,obj=None):return [f.name for f in self.model._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False
    def has_change_permission(self,request,obj=None):return False
for model in [BeanSupplier,GreenBeanDetails,GreenPurchase,CuppingRecord,SourcingEvent]:admin.site.register(model,SourcingReadOnlyAdmin)

from .models import PortalConfiguration
@admin.register(PortalConfiguration)
class InstanceAdmin(admin.ModelAdmin):
    def has_add_permission(self,request):return not PortalConfiguration.objects.exists()
    def has_delete_permission(self,request,obj=None):return False

from .models import PayrollAccess
@admin.register(PayrollAccess)
class PayrollAccessAdmin(admin.ModelAdmin):
    list_display=['user','manages_rates']
    def has_view_permission(self,request,obj=None):return request.user.is_superuser
    def has_add_permission(self,request):return request.user.is_superuser
    def has_change_permission(self,request,obj=None):return request.user.is_superuser
    def has_delete_permission(self,request,obj=None):return request.user.is_superuser

from .models import StoreConnection,StoreSyncRun,StoreProductMapping,StoreEvent
for model in [StoreSyncRun,StoreProductMapping,StoreEvent]:admin.site.register(model,SourcingReadOnlyAdmin)
@admin.register(StoreConnection)
class StoreDirectoryAdmin(SourcingReadOnlyAdmin):
    exclude=['credentials_cipher']
    def get_readonly_fields(self,request,obj=None):return [f.name for f in self.model._meta.fields if f.name!='credentials_cipher']

from .models import CostProfile,CostEstimate,CostEvent
for model in [CostProfile,CostEstimate,CostEvent]:admin.site.register(model,SourcingReadOnlyAdmin)
