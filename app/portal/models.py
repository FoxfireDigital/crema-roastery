from django.db import models
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
import uuid

ROAST_LEVELS=[(x,x) for x in ['Light','Light/Medium','Medium','Medium/Dark','Dark','French']]
GRIND_CHOICES=[('unknown','Confirm grind'),('whole','Whole bean'),('regular','Ground — Regular'),('fine','Ground — Fine'),('coarse','Ground — Coarse'),('ground','Ground — size not specified')]

class Coffee(models.Model):
    name=models.CharField(max_length=100,unique=True)
    active=models.BooleanField(default=True,help_text='Deactivate to remove from new work while retaining history.')
    kind=models.CharField(max_length=20,choices=[('single_origin','Single origin'),('blend','Blend'),('flavored','Flavored coffee')],default='single_origin')
    standard_roast=models.CharField(max_length=20,choices=ROAST_LEVELS,blank=True)
    experimental=models.BooleanField(default=False,help_text='Test batches may use any roast at any size; record their origin on each batch.')
    roast_base=models.ForeignKey('self',on_delete=models.PROTECT,null=True,blank=True,related_name='flavors',help_text='Default Medium base when no suitable Medium roast is planned. The ordered flavor remains separate for packaging and labels.')
    flavor_base_allowed=models.BooleanField(default=True,help_text='Disable for decaf, half-caff or any coffee unsuitable for flavor bases.')
    bulk_stock_enabled=models.BooleanField(default=True,help_text='Include this coffee in manual roasted whole-bean counts.')
    wholesale_only_customer=models.ForeignKey('WholesaleCustomer',on_delete=models.PROTECT,null=True,blank=True,related_name='exclusive_coffees',help_text='Optional: offer this product only on wholesale orders for this saved account.')
    @property
    def roasting_coffee(self):return self.roast_base if self.roast_base_id else self
    @property
    def roast_locked(self): return self.kind in ('blend','flavored')
    @property
    def flavor_base_eligible(self):
        return self.active and self.flavor_base_allowed and not self.experimental and self.kind!='flavored'
    def clean(self):
        super().clean()
        if self.experimental and self.kind!='single_origin':raise ValidationError({'experimental':'Experimental entries must be single origins.'})
        if self.kind=='flavored':
            self.standard_roast='Medium'
            if not self.roast_base_id:raise ValidationError({'roast_base':'Choose a physical Medium roast base for this flavor.'})
        if self.roast_base_id:
            if self.kind!='flavored' or self.roast_base_id==self.pk or not self.roast_base.flavor_base_eligible or self.roast_base.roast_base_id or self.roast_base.standard_roast!='Medium':
                raise ValidationError({'roast_base':'Choose an active, unflavored Medium roast base. Excluded coffees cannot be used for flavors.'})
        if self.roast_locked and not self.standard_roast:
            raise ValidationError({'standard_roast':'Choose the standard roast for this blend.'})
    def save(self,*args,**kwargs):
        self.full_clean()
        return super().save(*args,**kwargs)
    def __str__(self): return self.name
    class Meta: ordering=['name']

class LabelVariant(models.Model):
    name=models.CharField(max_length=100,unique=True)
    customer=models.CharField(max_length=120,blank=True)
    coffee=models.ForeignKey(Coffee,on_delete=models.PROTECT,related_name='labels')
    active=models.BooleanField(default=True)
    def __str__(self): return self.name
    class Meta: ordering=['name']

class Roaster(models.Model):
    name=models.CharField(max_length=40,unique=True)
    active=models.BooleanField(default=True)
    max_green_oz=models.DecimalField(max_digits=7,decimal_places=2,null=True,blank=True,help_text='Maximum safe green input in ounces for this machine. Set before planning.')
    min_green_oz=models.DecimalField(max_digits=7,decimal_places=2,default=0,help_text='Minimum green input in ounces. Use tenths; 0 leaves the minimum unset.')
    @property
    def capacity(self):
        return self.max_green_oz
    @property
    def minimum(self):
        return self.min_green_oz or Decimal('.1')
    def clean(self):
        super().clean()
        if self.active and (self.max_green_oz is None or not self.max_green_oz.is_finite() or self.max_green_oz<Decimal('.1')):raise ValidationError({'max_green_oz':'Set a positive safe green input capacity before activating this machine.'})
        if self.min_green_oz is None or not self.min_green_oz.is_finite() or self.min_green_oz<0 or self.min_green_oz!=self.min_green_oz.quantize(Decimal('.1')):raise ValidationError({'min_green_oz':'Enter a nonnegative minimum in tenths of an ounce.'})
        if self.max_green_oz is not None and self.max_green_oz.is_finite() and self.minimum>self.max_green_oz:raise ValidationError({'min_green_oz':'The minimum cannot exceed this machine’s maximum green input.'})
    def save(self,*args,**kwargs):
        self.full_clean();return super().save(*args,**kwargs)
    def __str__(self): return self.name

class CurrentBatches(models.Manager):
    def get_queryset(self):return super().get_queryset().filter(removed_at__isnull=True)

class Batch(models.Model):
    LEVELS=ROAST_LEVELS
    date=models.DateField(default=timezone.localdate)
    operator=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    roaster=models.ForeignKey(Roaster,on_delete=models.PROTECT)
    coffee=models.ForeignKey(Coffee,on_delete=models.PROTECT)
    label_variant=models.ForeignKey(LabelVariant,on_delete=models.PROTECT,null=True,blank=True)
    green_oz=models.DecimalField(max_digits=9,decimal_places=2)
    green_override=models.JSONField(default=dict,db_default={},blank=True)
    roasted_oz=models.DecimalField(max_digits=9,decimal_places=2,null=True,blank=True)
    roast_level=models.CharField(max_length=20,choices=LEVELS)
    measured_at=models.DateTimeField(null=True,blank=True)
    roasted_at=models.DateTimeField(null=True,blank=True)
    cooled_at=models.DateTimeField(null=True,blank=True)
    bagged_at=models.DateTimeField(null=True,blank=True)
    sealed_at=models.DateTimeField(null=True,blank=True)
    note=models.TextField(blank=True)
    experimental_origin=models.CharField(max_length=160,blank=True,help_text='Origin / lot for this test, for example India — trial lot A.')
    green_item=models.ForeignKey('GreenBeanItem',on_delete=models.PROTECT,null=True,blank=True,help_text='Optional direct green origin for this load; otherwise use the coffee’s green recipe.')
    actual_finish_temp_f=models.DecimalField(max_digits=5,decimal_places=1,null=True,blank=True,help_text='Actual finish temperature in degrees F; not a roaster control')
    order=models.ForeignKey('CustomOrder',null=True,blank=True,on_delete=models.PROTECT,related_name='batches')
    planned_group=models.ForeignKey('RoastGroup',null=True,blank=True,on_delete=models.PROTECT,related_name='actual_batches')
    created_at=models.DateTimeField(auto_now_add=True)
    merged_into=models.ForeignKey('self',on_delete=models.PROTECT,null=True,blank=True,related_name='merged_inputs')
    removed_at=models.DateTimeField(null=True,blank=True)
    removed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='removed_roast_batches')
    removal_reason=models.CharField(max_length=300,blank=True)
    objects=CurrentBatches()
    all_objects=models.Manager()
    @property
    def status(self):
        if self.removed_at:return 'Deleted / excluded'
        if self.merged_into_id:return f'Measured input combined into batch #{self.merged_into_id}'
        return 'Sealed' if self.sealed_at else 'Bagged' if self.bagged_at else 'Cooled' if self.cooled_at else 'Roasted' if self.roasted_at else 'Measured' if self.measured_at else 'Pending'
    @property
    def loss_percent(self):
        if self.green_oz and self.roasted_oz is not None:
            return round((1-float(self.roasted_oz/self.green_oz))*100,1)
        return None
    @property
    def has_green_override(self):
        from .load_override import authorized_weight
        return authorized_weight(self)
    def clean(self):
        super().clean()
        errors={}
        if self.green_oz is not None:
            if not self.green_oz.is_finite() or self.green_oz<=0:
                errors['green_oz']='Enter a positive green input weight.'
            elif self.roaster_id and (self._state.adding or self.roasted_at is None):
                cap=self.roaster.capacity
                if cap is None or cap<=0:
                    errors['roaster']='Set the green input capacity for this roaster first.'
                elif self.green_oz>cap and not self.has_green_override:
                    errors['green_oz']=f'{self.roaster.name} holds at most {cap:g} oz of green coffee.'
                elif self.green_oz<self.roaster.minimum and not self.has_green_override and (self._state.adding or Batch.all_objects.filter(pk=self.pk).exclude(green_oz=self.green_oz,roaster_id=self.roaster_id).exists()):
                    errors['green_oz']=f'{self.roaster.name} needs at least {self.roaster.minimum:g} oz of green coffee.'
        if self.coffee_id:
            if self.coffee.experimental and not (self.experimental_origin or '').strip():errors['experimental_origin']='Record the origin or lot for this experimental batch.'
            if self._state.adding and self.coffee.roast_base_id:
                errors['coffee']='Record the actual Medium roast base here; flavored products belong on orders and labels.'
            if self._state.adding and not self.coffee.active:
                errors['coffee']='This coffee is inactive.'
            if self.coffee.roast_locked and self.roast_level!=self.coffee.standard_roast:
                errors['roast_level']=f'{self.coffee.name} must use its standard {self.coffee.standard_roast} roast.'
            changed=self._state.adding or (self.pk and Batch.objects.filter(pk=self.pk).exclude(coffee_id=self.coffee_id,roast_level=self.roast_level).exists())
            if changed and not self.coffee.experimental and not self.coffee.roast_locked and self.roast_level!=self.coffee.standard_roast:
                approved=(self.order_id and self.order.roast_level==self.roast_level) or (self.planned_group_id and self.planned_group.orders.filter(finished_oz__gte=80).exists())
                if not approved:errors['roast_level']='A custom roast needs a linked single-origin order of 5 lb or more.'
        if self.planned_group_id and (self.planned_group.coffee_id!=self.coffee_id or self.planned_group.roast_level!=self.roast_level or self.planned_group.label_variant_id!=self.label_variant_id):
            errors['planned_group']='Batch coffee, roast and label must match its plan.'
        if self._state.adding and self.planned_group_id and not self.coffee.flavor_base_eligible and self.planned_group.orders.filter(product_coffee__kind='flavored').exists():
            errors['coffee']='This coffee is excluded from flavor-base use. Review the plan’s flavor base first.'
        if self.label_variant_id:
            if self.label_variant.coffee_id!=self.coffee_id:
                errors['label_variant']='This label belongs to a different coffee.'
            elif self._state.adding and not self.label_variant.active:
                errors['label_variant']='This label is inactive.'
        if self.order_id:
            flavored=self.order.coffee.kind=='flavored' and self.order.coffee.roast_base_id
            matching=(self.coffee.flavor_base_eligible and self.roast_level=='Medium') if flavored else self.order.coffee_id==self.coffee_id
            if flavored and not self._state.adding and not matching and Batch.objects.filter(pk=self.pk,coffee_id=self.coffee_id,roast_level=self.roast_level).exists():matching=True
            if not matching or (not flavored and self.order.label_variant_id!=self.label_variant_id):errors['order']='Batch coffee and label must match the linked order.'
        if errors: raise ValidationError(errors)
    def save(self,*args,**kwargs):
        from django.db import transaction
        from .green_stock import sync_batch
        with transaction.atomic():
            previous=type(self).all_objects.select_for_update().filter(pk=self.pk).first() if self.pk else None
            self.full_clean();result=super().save(*args,**kwargs)
            sync_batch(type(self).all_objects.get(pk=self.pk),previous)
            return result
    @property
    def display_coffee(self):return f'{self.coffee.name} — {self.experimental_origin}' if self.coffee.experimental and self.experimental_origin else self.coffee.name
    class Meta:
        ordering=['-date','-id']
        base_manager_name='all_objects'

class CustomOrder(models.Model):
    LEVELS=Batch.LEVELS
    customer_name=models.CharField(max_length=120)
    order_reference=models.CharField(max_length=80,blank=True)
    coffee=models.ForeignKey(Coffee,on_delete=models.PROTECT)
    label_variant=models.ForeignKey(LabelVariant,on_delete=models.PROTECT,null=True,blank=True)
    roast_level=models.CharField(max_length=20,choices=LEVELS)
    target_finish_temp_f=models.DecimalField(max_digits=5,decimal_places=1,null=True,blank=True,help_text='Requested finish temp in Fahrenheit; confirm with roaster before use')
    bags_5lb=models.PositiveSmallIntegerField(default=1)
    estimated_loss_pct=models.DecimalField(max_digits=4,decimal_places=1,default=16,help_text='Estimate only; adjust for actual green coffee and roast profile')
    due_date=models.DateField(null=True,blank=True)
    notes=models.TextField(blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    fulfilled_at=models.DateTimeField(null=True,blank=True)
    cancelled_at=models.DateTimeField(null=True,blank=True)
    @property
    def target_roasted_oz(self): return self.bags_5lb*80
    @property
    def estimated_green_oz(self):
        return round(self.target_roasted_oz/(1-float(self.estimated_loss_pct)/100),1)
    @property
    def sealed_roasted_oz(self):
        return sum(float(b.roasted_oz) for b in self.batches.all() if b.sealed_at and b.roasted_oz is not None)
    @property
    def status(self):
        if self.cancelled_at: return 'Cancelled'
        if self.fulfilled_at: return 'Fulfilled'
        bs=list(self.batches.all())
        if bs and self.sealed_roasted_oz >= self.target_roasted_oz: return 'Ready'
        if any(b.bagged_at for b in bs): return 'Bagging'
        if any(b.roasted_at for b in bs): return 'Cooling'
        if bs: return 'Roasting'
        return 'Ordered'
    def __str__(self): return f'Custom #{self.pk} - {self.customer_name}'
    def clean(self):
        super().clean()
        errors={}
        if self.coffee_id:
            if self._state.adding and not self.coffee.active:
                errors['coffee']='This coffee is inactive.'
            if self.coffee.roast_locked and self.roast_level!=self.coffee.standard_roast:
                errors['roast_level']=f'{self.coffee.name} must use its standard {self.coffee.standard_roast} roast.'
        if self.label_variant_id:
            if self.label_variant.coffee_id!=self.coffee_id:
                errors['label_variant']='This label belongs to a different coffee.'
            elif self._state.adding and not self.label_variant.active:
                errors['label_variant']='This label is inactive.'
        if self.coffee_id and self.coffee.roast_locked and self.target_finish_temp_f is not None:
            errors['target_finish_temp_f']='Blends and flavored coffees use their standard roast; custom temperature requests are unavailable.'
        if self.bags_5lb<1: errors['bags_5lb']='Order at least one 5 lb bag.'
        request_changed=self._state.adding or (self.pk and CustomOrder.objects.filter(pk=self.pk).exclude(coffee_id=self.coffee_id,roast_level=self.roast_level,target_finish_temp_f=self.target_finish_temp_f,bags_5lb=self.bags_5lb).exists())
        if request_changed and self.coffee_id and not self.coffee.roast_locked and self.bags_5lb<1:
            if not self.coffee.standard_roast:
                errors['coffee']='Set this coffee’s standard roast in Admin first.'
            elif self.roast_level!=self.coffee.standard_roast:
                errors['roast_level']='Orders under 5 lb use the standard roast.'
            if self.target_finish_temp_f is not None:
                errors['target_finish_temp_f']='Custom roast requests require 5 lb or more of this coffee.'
        if errors: raise ValidationError(errors)
    def save(self,*args,**kwargs):
        self.full_clean()
        return super().save(*args,**kwargs)
    class Meta: ordering=['-created_at']

class Shift(models.Model):
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='shifts')
    started_at=models.DateTimeField(default=timezone.now)
    ended_at=models.DateTimeField(null=True,blank=True)
    removed_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        ordering=['-started_at']
        constraints=[models.UniqueConstraint(fields=['user'],condition=Q(ended_at__isnull=True,removed_at__isnull=True),name='one_active_shift_per_user')]

class WorkBreak(models.Model):
    shift=models.ForeignKey(Shift,on_delete=models.CASCADE,related_name='breaks')
    started_at=models.DateTimeField(default=timezone.now)
    ended_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['shift'],condition=Q(ended_at__isnull=True),name='one_active_break_per_shift')]

class TimeEvent(models.Model):
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    shift=models.ForeignKey(Shift,on_delete=models.PROTECT)
    action=models.CharField(max_length=30)
    at=models.DateTimeField(default=timezone.now)
    class Meta: ordering=['-at']


class TimeAdjustment(models.Model):
    shift=models.ForeignKey(Shift,on_delete=models.PROTECT,related_name='adjustments')
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    at=models.DateTimeField(default=timezone.now)
    before=models.JSONField(default=dict)
    after=models.JSONField(default=dict)
    note=models.CharField(max_length=300,blank=True)
    class Meta: ordering=['-at','-id']


class CurrentPlans(models.Manager):
    def get_queryset(self):return super().get_queryset().filter(removed_at__isnull=True,historical=False,closed_at__isnull=True)


class RoastPlan(models.Model):
    date=models.DateField(default=timezone.localdate)
    historical=models.BooleanField(default=False,db_index=True)
    creation_key=models.UUIDField(unique=True,null=True,blank=True,editable=False)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    estimated_loss_pct=models.DecimalField(max_digits=4,decimal_places=1,default=16)
    spillage_pct=models.DecimalField(max_digits=4,decimal_places=1,default=5)
    use_roasted_stock=models.BooleanField(default=True)
    version=models.PositiveIntegerField(default=0)
    accepted_at=models.DateTimeField(null=True,blank=True)
    accepted_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='accepted_roast_plans')
    removed_at=models.DateTimeField(null=True,blank=True)
    removed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='removed_roast_plans')
    closed_at=models.DateTimeField(null=True,blank=True)
    closed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='closed_roast_plans')
    released_imports=models.JSONField(default=list)
    created_at=models.DateTimeField(auto_now_add=True)
    objects=CurrentPlans()
    all_objects=models.Manager()
    class Meta:
        ordering=['-id']
        base_manager_name='all_objects'
        constraints=[models.UniqueConstraint(fields=['date'],condition=Q(historical=True),name='one_historical_plan_per_day')]


class WholesaleCustomer(models.Model):
    name=models.CharField(max_length=120)
    name_key=models.CharField(max_length=256,unique=True)
    active=models.BooleanField(default=True,db_default=True)
    notes=models.CharField(max_length=500,blank=True,db_default='')
    default_grind=models.CharField(max_length=12,choices=GRIND_CHOICES,default='whole')
    usual_items=models.JSONField(default=list)
    version=models.PositiveIntegerField(default=0)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta: ordering=['name']


class CustomerPreferenceEvent(models.Model):
    customer=models.ForeignKey(WholesaleCustomer,on_delete=models.PROTECT)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    before=models.JSONField(default=dict)
    after=models.JSONField(default=dict)
    at=models.DateTimeField(default=timezone.now)


class WholesaleOrder(models.Model):
    plan=models.ForeignKey(RoastPlan,on_delete=models.PROTECT,related_name='wholesale_orders')
    account=models.ForeignKey(WholesaleCustomer,on_delete=models.PROTECT,null=True,blank=True,related_name='orders')
    customer=models.CharField(max_length=120)
    reference=models.CharField(max_length=100,blank=True)
    request_key=models.UUIDField(unique=True,editable=False)
    request_hash=models.CharField(max_length=64,editable=False)
    original_items=models.JSONField(default=list,editable=False)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-id']


class PlanEvent(models.Model):
    plan=models.ForeignKey(RoastPlan,on_delete=models.PROTECT,related_name='events')
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    action=models.CharField(max_length=20)
    details=models.JSONField(default=dict,blank=True)
    at=models.DateTimeField(default=timezone.now)
    class Meta: ordering=['-id']


class RoastGroup(models.Model):
    plan=models.ForeignKey(RoastPlan,on_delete=models.CASCADE,related_name='groups')
    key=models.CharField(max_length=64)
    loss_override=models.DecimalField(max_digits=4,decimal_places=1,null=True,blank=True)
    auto_batches=models.BooleanField(default=True)
    coffee=models.ForeignKey(Coffee,on_delete=models.PROTECT)
    label_variant=models.ForeignKey(LabelVariant,on_delete=models.PROTECT,null=True,blank=True)
    roast_level=models.CharField(max_length=20,choices=ROAST_LEVELS)
    target_finish_temp_f=models.DecimalField(max_digits=5,decimal_places=1,null=True,blank=True)
    legacy_order=models.OneToOneField(CustomOrder,on_delete=models.PROTECT,null=True,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['plan','key'],name='unique_profile_per_roast_plan')]
        ordering=['coffee__name','id']


class CurrentPlanningRows(models.Manager):
    def get_queryset(self):return super().get_queryset().filter(removed_at__isnull=True)


class IncomingOrderLine(models.Model):
    import_order=models.ForeignKey('ImportOrder',on_delete=models.PROTECT,null=True,blank=True,related_name='allocations')
    group=models.ForeignKey(RoastGroup,on_delete=models.PROTECT,related_name='orders')
    wholesale_order=models.ForeignKey('WholesaleOrder',on_delete=models.PROTECT,null=True,blank=True,related_name='lines')
    reference=models.CharField(max_length=100,blank=True,help_text='Order number or stock reference')
    customer=models.CharField(max_length=120,blank=True)
    received_at=models.DateTimeField(default=timezone.now)
    finished_oz=models.DecimalField(max_digits=10,decimal_places=2)
    product_coffee=models.ForeignKey(Coffee,on_delete=models.PROTECT,null=True,blank=True,related_name='product_order_lines')
    product_label=models.ForeignKey(LabelVariant,on_delete=models.PROTECT,null=True,blank=True,related_name='product_order_lines')
    packaging=models.JSONField(default=list,blank=True,help_text='Known package sizes and bag counts; empty means pack size needs confirmation.')
    grind=models.CharField(max_length=12,choices=GRIND_CHOICES,default='unknown')
    @property
    def ordered_coffee(self):return self.product_coffee if self.product_coffee_id else self.group.coffee
    @property
    def ordered_label(self):return self.product_label if self.product_coffee_id else self.group.label_variant
    source=models.CharField(max_length=20,default='manual',editable=False)
    external_id=models.CharField(max_length=120,blank=True,editable=False)
    removed_at=models.DateTimeField(null=True,blank=True)
    objects=CurrentPlanningRows()
    all_objects=models.Manager()
    class Meta:
        base_manager_name='all_objects'
        ordering=['received_at','id']
        constraints=[models.UniqueConstraint(fields=['source','external_id'],condition=~Q(external_id=''),name='unique_imported_order_line')]
    def clean(self):
        super().clean()
        if self.finished_oz is None or not self.finished_oz.is_finite() or self.finished_oz<=0:
            raise ValidationError({'finished_oz':'Enter a positive finished coffee quantity.'})
        if self.group_id:
            c=self.ordered_coffee
            matching_base=(self.group.coffee.flavor_base_eligible and self.group.roast_level=='Medium' and self.group.target_finish_temp_f is None) if c.kind=='flavored' and c.roast_base_id else self.group.coffee_id==c.pk
            if not matching_base:
                # Historical flavored production is retained at its original coffee.
                historical=self.pk and type(self).all_objects.filter(pk=self.pk,group_id=self.group_id,product_coffee_id=self.product_coffee_id).exists()
                if not historical:raise ValidationError('The order must use the selected coffee’s roast base.')
            if self.product_label_id and self.product_label.coffee_id!=c.pk:raise ValidationError('This packaging label belongs to a different finished coffee.')
            if c.roast_locked or self.finished_oz<80:
                if not c.standard_roast or self.group.roast_level!=c.standard_roast:
                    raise ValidationError('This order must use the coffee’s standard roast.')
                if self.group.target_finish_temp_f is not None:
                    raise ValidationError('Custom temperatures require a single-origin order 5 lb or more.')
    def save(self,*args,**kwargs):
        self.full_clean()
        return super().save(*args,**kwargs)


class PlannedBatch(models.Model):
    group=models.ForeignKey(RoastGroup,on_delete=models.PROTECT,related_name='planned_batches')
    roaster=models.ForeignKey(Roaster,on_delete=models.PROTECT)
    green_oz=models.DecimalField(max_digits=9,decimal_places=2)
    green_override=models.JSONField(default=dict,db_default={},blank=True)
    estimated_loss_pct=models.DecimalField(max_digits=4,decimal_places=1,null=True,blank=True)
    yield_basis=models.JSONField(default=dict,blank=True)
    batch=models.OneToOneField(Batch,on_delete=models.PROTECT,null=True,blank=True,related_name='planned_from')
    removed_at=models.DateTimeField(null=True,blank=True)
    objects=CurrentPlanningRows()
    all_objects=models.Manager()
    class Meta:
        ordering=['id']
        base_manager_name='all_objects'
    @property
    def has_green_override(self):
        from .load_override import authorized_weight
        return authorized_weight(self)
    def clean(self):
        super().clean()
        if self.green_oz is None or not self.green_oz.is_finite() or self.green_oz<=0:
            raise ValidationError({'green_oz':'Enter a positive green input weight.'})
        if self.roaster_id:
            cap=self.roaster.capacity
            if cap is None or cap<=0 or (self.green_oz>cap and not self.has_green_override):
                raise ValidationError({'green_oz':f'{self.roaster.name} allows at most {cap or 0:g} oz green input.'})
            if not self.batch_id and not self.removed_at and self.green_oz<self.roaster.minimum and not self.has_green_override:
                raise ValidationError({'green_oz':f'{self.roaster.name} needs at least {self.roaster.minimum:g} oz green input.'})
    def save(self,*args,**kwargs):
        self.full_clean()
        return super().save(*args,**kwargs)


class ImportOrder(models.Model):
    store=models.ForeignKey('StoreConnection',on_delete=models.PROTECT,null=True,blank=True,related_name='orders')
    source_order_id=models.CharField(max_length=250,blank=True)
    due_on=models.DateField(null=True,blank=True)
    source_updated_at=models.DateTimeField(null=True,blank=True)
    source_flags=models.JSONField(default=list)
    external_id=models.CharField(max_length=120,unique=True)
    reference=models.CharField(max_length=100)
    customer=models.CharField(max_length=120,blank=True)
    received_at=models.DateTimeField()
    refreshed_at=models.DateTimeField(auto_now=True)
    financial_status=models.CharField(max_length=40,blank=True)
    fulfillment_status=models.CharField(max_length=40,blank=True)
    cancelled=models.BooleanField(default=False)
    subscription=models.CharField(max_length=20,default='unknown',choices=[('unknown','Not provided'),('recurring','Subscription'),('prepaid','Prepaid — review delivery schedule')])
    lines=models.JSONField(default=list)
    imported_plan=models.ForeignKey(RoastPlan,on_delete=models.PROTECT,null=True,blank=True)
    imported_at=models.DateTimeField(null=True,blank=True)
    removed_at=models.DateTimeField(null=True,blank=True)
    source_signature=models.CharField(max_length=64,blank=True)
    instructions=models.TextField(blank=True)
    instructions_confirmed=models.BooleanField(default=False)
    source_changed=models.BooleanField(default=False)
    latest_lines=models.JSONField(default=list)
    api_source_signature=models.CharField(max_length=64,blank=True)
    latest_api_signature=models.CharField(max_length=64,blank=True)
    dismissed_at=models.DateTimeField(null=True,blank=True,db_index=True)
    history_assignment_locked=models.BooleanField(default=False)
    dismissed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='dismissed_import_orders')
    class Meta:
        ordering=['received_at','id']
        constraints=[models.UniqueConstraint(fields=['store','source_order_id'],condition=Q(store__isnull=False),name='unique_order_per_connected_store')]


class ImportOrderVisibilityEvent(models.Model):
    order=models.ForeignKey(ImportOrder,on_delete=models.PROTECT,related_name='visibility_events')
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    action=models.CharField(max_length=10,choices=[('dismiss','Dismissed'),('restore','Restored')])
    at=models.DateTimeField(default=timezone.now)
    class Meta: ordering=['-id']


class OrderLookupEvent(models.Model):
    order=models.ForeignKey(ImportOrder,on_delete=models.PROTECT,related_name='lookup_events')
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    action=models.CharField(max_length=20,default='recovered')
    at=models.DateTimeField(default=timezone.now)


class ProductMapping(models.Model):
    fingerprint=models.CharField(max_length=64,unique=True)
    title=models.CharField(max_length=500)
    sku=models.CharField(max_length=150,blank=True)
    coffee=models.ForeignKey(Coffee,on_delete=models.PROTECT,null=True,blank=True)
    label_variant=models.ForeignKey(LabelVariant,on_delete=models.PROTECT,null=True,blank=True)
    size_oz=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    skip=models.BooleanField(default=False)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True)
    updated_at=models.DateTimeField(auto_now=True)
    def clean(self):
        if not self.skip and (not self.coffee_id or self.size_oz is None or self.size_oz<=0):raise ValidationError('Choose a coffee and positive bag size, or exclude this product.')
        if self.label_variant_id and self.label_variant.coffee_id!=self.coffee_id:raise ValidationError('This packaging label belongs to a different coffee.')


class BatchProgressEvent(models.Model):
    batch=models.ForeignKey(Batch,on_delete=models.PROTECT,related_name='progress_events')
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    action=models.CharField(max_length=20)
    at=models.DateTimeField(default=timezone.now)
    before=models.JSONField(default=dict)
    after=models.JSONField(default=dict)
    undoes=models.OneToOneField('self',on_delete=models.PROTECT,null=True,blank=True,related_name='reversal')
    class Meta: ordering=['-id']


class BatchMergeEvent(models.Model):
    source=models.OneToOneField(Batch,on_delete=models.PROTECT,related_name='merge_record')
    target=models.ForeignKey(Batch,on_delete=models.PROTECT,related_name='merge_events')
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    at=models.DateTimeField(default=timezone.now)
    before=models.JSONField(default=dict)
    after=models.JSONField(default=dict)
    note=models.CharField(max_length=300)
    class Meta:ordering=['-id']


class PackingEvent(models.Model):
    line=models.ForeignKey(IncomingOrderLine,on_delete=models.PROTECT,related_name='packing_events')
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    at=models.DateTimeField(default=timezone.now)
    before=models.JSONField(default=dict)
    after=models.JSONField(default=dict)
    class Meta:ordering=['-id']


class HistoricalRoast(models.Model):
    source_key=models.CharField(max_length=64,unique=True)
    plan=models.ForeignKey(RoastPlan,on_delete=models.PROTECT,null=True,blank=True,related_name='workbook_roasts')
    workbook=models.CharField(max_length=200)
    sheet=models.CharField(max_length=40)
    row_number=models.PositiveIntegerField()
    date=models.DateField(null=True,blank=True)
    operator_name=models.CharField(max_length=100,blank=True)
    roaster_name=models.CharField(max_length=60,blank=True)
    coffee_name=models.CharField(max_length=120)
    coffee=models.ForeignKey(Coffee,on_delete=models.PROTECT,null=True,blank=True)
    roast_level=models.CharField(max_length=40,blank=True)
    green_oz=models.DecimalField(max_digits=12,decimal_places=3,null=True,blank=True)
    roasted_oz=models.DecimalField(max_digits=12,decimal_places=3,null=True,blank=True)
    time_recorded=models.CharField(max_length=100,blank=True)
    flags=models.JSONField(default=list)
    raw_data=models.JSONField(default=list)
    imported_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-date','-id']


class HoursPayment(models.Model):
    request_key=models.UUIDField(unique=True)
    payer=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='hours_payments_sent')
    payee=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='hours_payments_received')
    paid_on=models.DateField()
    through_date=models.DateField()
    covered_until=models.DateTimeField()
    credited_seconds=models.PositiveBigIntegerField(default=0)
    amount=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    estimated_gross=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    pay_calculation=models.JSONField(default=dict,blank=True)
    note=models.CharField(max_length=300,blank=True)
    recorded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='hours_payments_recorded')
    recorded_at=models.DateTimeField(default=timezone.now)
    voided_at=models.DateTimeField(null=True,blank=True)
    voided_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='hours_payments_voided')
    class Meta: ordering=['-paid_on','-id']
    @property
    def hours(self):return round(self.credited_seconds/3600,2)


class SubscriptionContract(models.Model):
    external_id=models.CharField(max_length=120,unique=True)
    customer=models.CharField(max_length=120,blank=True)
    status=models.CharField(max_length=20)
    next_billing_at=models.DateTimeField(null=True,blank=True)
    interval=models.CharField(max_length=20,blank=True)
    interval_count=models.PositiveIntegerField(default=1)
    delivery_method=models.CharField(max_length=20,blank=True)
    lines=models.JSONField(default=list)
    refreshed_at=models.DateTimeField(auto_now=True)
    class Meta: ordering=['next_billing_at','id']


class SubscriptionCycle(models.Model):
    contract=models.ForeignKey(SubscriptionContract,on_delete=models.PROTECT,related_name='production_cycles')
    due_at=models.DateTimeField()
    plan=models.ForeignKey(RoastPlan,on_delete=models.PROTECT,related_name='subscription_cycles')
    forecast_order=models.OneToOneField(ImportOrder,on_delete=models.PROTECT,related_name='forecast_cycle')
    renewal_order=models.OneToOneField(ImportOrder,on_delete=models.PROTECT,null=True,blank=True,related_name='advance_cycle')
    schedule_refreshed_at=models.DateTimeField()
    created_at=models.DateTimeField(default=timezone.now)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['contract','due_at'],name='unique_subscription_production_cycle')]
        ordering=['due_at','id']


class LabelQueueLock(models.Model):
    """Singleton row serializes page-filler reservations, including an empty queue."""
    version=models.PositiveIntegerField(default=0)


class LabelPrintRun(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    request_key=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    order_revision=models.CharField(max_length=64)
    source_revision=models.CharField(max_length=64)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    plan=models.ForeignKey(RoastPlan,on_delete=models.PROTECT,null=True,blank=True)
    status=models.CharField(max_length=12,default='queued',choices=[('queued','Queued'),('printed','Printed'),('released','Released')])
    rows=models.JSONField(default=list)
    subscription_labels=models.JSONField(default=list)
    sheet_settings=models.JSONField(default=dict)
    events=models.JSONField(default=list)
    class Meta: ordering=['-created_at','-id']


class ShopifyConnection(models.Model):
    shop_domain=models.CharField(max_length=100)
    client_id=models.CharField(max_length=150)
    client_secret_cipher=models.TextField(blank=True)
    access_token_cipher=models.TextField(blank=True)
    refresh_token_cipher=models.TextField(blank=True)
    refresh_token_expires_at=models.DateTimeField(null=True,blank=True)
    token_expires_at=models.DateTimeField(null=True,blank=True)
    auth_mode=models.CharField(max_length=20,default='oauth')
    granted_scopes=models.JSONField(default=list)
    connected_at=models.DateTimeField(null=True,blank=True)
    last_sync_at=models.DateTimeField(null=True,blank=True)
    last_sync_until=models.DateTimeField(null=True,blank=True)
    sync_cursor=models.TextField(blank=True)
    sync_since=models.DateTimeField(null=True,blank=True)
    sync_until=models.DateTimeField(null=True,blank=True)
    sync_started_at=models.DateTimeField(null=True,blank=True)
    last_count=models.PositiveIntegerField(default=0)
    last_error=models.CharField(max_length=300,blank=True)
    include_customer_names=models.BooleanField(default=False)
    version=models.PositiveIntegerField(default=0)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    updated_at=models.DateTimeField(auto_now=True)


class ShopifyAutoState(models.Model):
    enabled=models.BooleanField(default=False)
    heartbeat_at=models.DateTimeField(null=True,blank=True)
    last_attempt_at=models.DateTimeField(null=True,blank=True)
    last_success_at=models.DateTimeField(null=True,blank=True)
    lease_key=models.UUIDField(null=True,blank=True)
    lease_at=models.DateTimeField(null=True,blank=True)
    last_error=models.CharField(max_length=300,blank=True)
    registration_error=models.CharField(max_length=300,blank=True)
    registered_at=models.DateTimeField(null=True,blank=True)
    registered_version=models.PositiveIntegerField(null=True,blank=True)
    registered_topics=models.JSONField(default=list)


class ShopifyWebhookEvent(models.Model):
    delivery_key=models.CharField(max_length=64,unique=True)
    shop_domain=models.CharField(max_length=100)
    topic=models.CharField(max_length=50)
    connection_version=models.PositiveIntegerField()
    received_at=models.DateTimeField(default=timezone.now)
    processed_at=models.DateTimeField(null=True,blank=True,db_index=True)


class ShopifyCatalog(models.Model):
    shop_domain=models.CharField(max_length=100,blank=True)
    products=models.JSONField(default=list)
    checked_at=models.DateTimeField(null=True,blank=True)
    checked_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True)
    checking_started_at=models.DateTimeField(null=True,blank=True)
    last_error=models.CharField(max_length=300,blank=True)


class LabelArtwork(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    coffee=models.ForeignKey(Coffee,on_delete=models.PROTECT)
    label_variant=models.ForeignKey(LabelVariant,on_delete=models.PROTECT,null=True,blank=True)
    size_oz=models.DecimalField(max_digits=10,decimal_places=2)
    roast_level=models.CharField(max_length=20,choices=[*ROAST_LEVELS,('Unmarked','No fixed roast — 5 lb single origins')])
    print_masks=models.JSONField(default=list,blank=True,editable=False)
    per_sheet=models.PositiveSmallIntegerField(default=4)
    image_data=models.BinaryField()
    image_format=models.CharField(max_length=10)
    width=models.PositiveIntegerField()
    height=models.PositiveIntegerField()
    sha256=models.CharField(max_length=64)
    source_name=models.CharField(max_length=150)
    active=models.BooleanField(default=False)
    events=models.JSONField(default=list)
    uploaded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-created_at','-id']
    def clean(self):
        from .artwork_rules import NEUTRAL_ROAST,neutral_allowed,validate_masks
        super().clean();validate_masks(self.print_masks)
        if self.roast_level==NEUTRAL_ROAST and self.coffee_id and not neutral_allowed(self.coffee,self.size_oz,self.per_sheet):
            raise ValidationError({'roast_level':'Roast-neutral artwork is only for 5 lb single origins, four per sheet.'})
        if self.print_masks and self.roast_level!=NEUTRAL_ROAST:raise ValidationError('Print-only covers belong to roast-neutral masters.')


class ArtworkCoffeeDecision(models.Model):
    source_name=models.CharField(max_length=100,unique=True)
    state=models.CharField(max_length=15,default='review',choices=[('review','Needs review'),('matched','Matched'),('unavailable','Not available')])
    coffee=models.ForeignKey(Coffee,on_delete=models.PROTECT,null=True,blank=True)
    version=models.PositiveIntegerField(default=0)
    events=models.JSONField(default=list)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        ordering=['source_name']
        constraints=[models.CheckConstraint(condition=Q(state='matched',coffee__isnull=False)|Q(state__in=['review','unavailable'],coffee__isnull=True),name='artwork_decision_coffee_state')]


class RoastedStockLock(models.Model):
    version=models.PositiveIntegerField(default=0)


class RoastedStock(models.Model):
    request_key=models.UUIDField(unique=True,default=uuid.uuid4,editable=False)
    coffee=models.ForeignKey(Coffee,on_delete=models.PROTECT)
    roast_level=models.CharField(max_length=20,choices=ROAST_LEVELS)
    target_finish_temp_f=models.DecimalField(max_digits=5,decimal_places=1,null=True,blank=True)
    remaining_oz=models.DecimalField(max_digits=10,decimal_places=1)
    measured_at=models.DateTimeField(null=True,blank=True)
    roasted_on=models.DateField(null=True,blank=True)
    note=models.CharField(max_length=300,blank=True)
    active=models.BooleanField(default=True)
    needs_recount=models.BooleanField(default=False)
    version=models.PositiveIntegerField(default=0)
    recorded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        ordering=['roasted_on','created_at','id']
        constraints=[models.CheckConstraint(condition=Q(remaining_oz__gte=0),name='nonnegative_roasted_stock')]


class RoastedStockAllocation(models.Model):
    stock=models.ForeignKey(RoastedStock,on_delete=models.PROTECT,related_name='allocations')
    line=models.ForeignKey(IncomingOrderLine,on_delete=models.PROTECT,related_name='stock_allocations')
    amount_oz=models.DecimalField(max_digits=10,decimal_places=1)
    status=models.CharField(max_length=12,default='reserved',choices=[('reserved','Reserved'),('used','Used'),('released','Released')])
    created_at=models.DateTimeField(default=timezone.now)
    class Meta:
        ordering=['id']
        constraints=[models.UniqueConstraint(fields=['stock','line'],condition=Q(status='reserved'),name='unique_active_stock_line_reservation'),models.CheckConstraint(condition=Q(amount_oz__gt=0),name='positive_roasted_stock_allocation')]


class RoastedStockEvent(models.Model):
    stock=models.ForeignKey(RoastedStock,on_delete=models.PROTECT,related_name='events')
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True)
    action=models.CharField(max_length=20)
    at=models.DateTimeField(default=timezone.now)
    before=models.JSONField(default=dict)
    after=models.JSONField(default=dict)
    class Meta: ordering=['-id']


class PackingProgress(models.Model):
    line=models.OneToOneField(IncomingOrderLine,on_delete=models.PROTECT,related_name='packing_progress')
    flavored_at=models.DateTimeField(null=True,blank=True)
    ground_at=models.DateTimeField(null=True,blank=True)
    bagged_at=models.DateTimeField(null=True,blank=True)
    labeled_at=models.DateTimeField(null=True,blank=True)
    sealed_at=models.DateTimeField(null=True,blank=True)
    version=models.PositiveIntegerField(default=0)


class PackingProgressEvent(models.Model):
    progress=models.ForeignKey(PackingProgress,on_delete=models.PROTECT,related_name='events')
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    at=models.DateTimeField(default=timezone.now)
    before=models.JSONField(default=dict)
    after=models.JSONField(default=dict)
    undoes=models.OneToOneField('self',on_delete=models.PROTECT,null=True,blank=True,related_name='reversal')
    class Meta:ordering=['-id']


class OrderReviewEvent(models.Model):
    order=models.ForeignKey(ImportOrder,on_delete=models.PROTECT,related_name='review_events')
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    at=models.DateTimeField(default=timezone.now)
    before=models.JSONField(default=dict)
    after=models.JSONField(default=dict)
    class Meta:ordering=['-id']


class UserAppearance(models.Model):
    user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='appearance_settings')
    palette=models.CharField(max_length=20,default='forest',choices=[('forest','Forest'),('espresso','Espresso'),('ocean','Ocean'),('plum','Plum'),('slate','Slate dusk'),('midnight','Midnight forest'),('crimson','Crimson'),('gold','Black & Gold')])


class GreenBeanItem(models.Model):
    name=models.CharField(max_length=120,unique=True)
    remaining_oz=models.DecimalField(max_digits=12,decimal_places=1,default=0)
    reorder_oz=models.DecimalField(max_digits=12,decimal_places=1,default=0)
    notes=models.TextField(blank=True)
    active=models.BooleanField(default=True)
    version=models.PositiveIntegerField(default=0)
    recorded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:ordering=['name']
    def __str__(self):return self.name


class GreenRecipe(models.Model):
    coffee=models.OneToOneField(Coffee,on_delete=models.PROTECT,related_name='green_recipe')
    components=models.JSONField(default=list)
    version=models.PositiveIntegerField(default=0)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    updated_at=models.DateTimeField(auto_now=True)


class GreenBatchUsage(models.Model):
    batch=models.OneToOneField(Batch,on_delete=models.PROTECT,related_name='green_usage')
    percentages=models.JSONField(default=dict)
    amounts=models.JSONField(default=dict)
    updated_at=models.DateTimeField(auto_now=True)


class GreenMovement(models.Model):
    item=models.ForeignKey(GreenBeanItem,on_delete=models.PROTECT,related_name='movements')
    batch=models.ForeignKey(Batch,on_delete=models.PROTECT,null=True,blank=True)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    action=models.CharField(max_length=24)
    delta_oz=models.DecimalField(max_digits=12,decimal_places=1)
    before_oz=models.DecimalField(max_digits=12,decimal_places=1)
    after_oz=models.DecimalField(max_digits=12,decimal_places=1)
    note=models.CharField(max_length=300,blank=True)
    request_key=models.UUIDField(null=True,blank=True,unique=True)
    request_hash=models.CharField(max_length=64,blank=True)
    at=models.DateTimeField(default=timezone.now)
    class Meta:ordering=['-id']


class GreenRecipeEvent(models.Model):
    recipe=models.ForeignKey(GreenRecipe,on_delete=models.PROTECT)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    before=models.JSONField(default=list)
    after=models.JSONField(default=list)
    at=models.DateTimeField(default=timezone.now)

class PayrollAccess(models.Model):
    user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    manages_rates=models.BooleanField(default=False)

class HourlyRate(models.Model):
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='hourly_rates')
    effective_on=models.DateField()
    amount=models.DecimalField(max_digits=8,decimal_places=2)
    reason=models.CharField(max_length=300)
    request_key=models.UUIDField(unique=True,default=uuid.uuid4,editable=False)
    request_hash=models.CharField(max_length=64)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='rates_recorded')
    created_at=models.DateTimeField(default=timezone.now)
    class Meta:ordering=['-effective_on','-id']


class ArtisanProfileRevision(models.Model):
    profile_key=models.CharField(max_length=64)
    revision=models.PositiveIntegerField()
    configuration=models.JSONField(default=dict)
    source=models.ForeignKey('ArtisanProfileSource',on_delete=models.PROTECT,null=True,blank=True)
    upload_key=models.UUIDField(null=True,blank=True,unique=True,editable=False)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(default=timezone.now)
    class Meta:
        ordering=['-revision','-id']
        constraints=[models.UniqueConstraint(fields=['profile_key','revision'],name='unique_artisan_profile_revision')]


class ArtisanPreparation(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    revision=models.ForeignKey(ArtisanProfileRevision,on_delete=models.PROTECT)
    planned_batch=models.ForeignKey('PlannedBatch',on_delete=models.PROTECT,null=True,blank=True)
    snapshot=models.JSONField(default=dict)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(default=timezone.now)
    class Meta:ordering=['-created_at']


class ArtisanProfileSource(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    sha256=models.CharField(max_length=64,unique=True)
    filename=models.CharField(max_length=180)
    original_b64=models.TextField()
    inspection=models.JSONField(default=dict)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(default=timezone.now)


class BatchArtisanLog(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    batch=models.ForeignKey(Batch,on_delete=models.PROTECT,related_name='artisan_logs')
    source=models.ForeignKey(ArtisanProfileSource,on_delete=models.PROTECT,related_name='batch_logs')
    reference_source=models.ForeignKey(ArtisanProfileSource,on_delete=models.PROTECT,null=True,blank=True,related_name='reference_logs')
    reference_snapshot=models.JSONField(default=dict)
    notes=models.CharField(max_length=1200,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='attached_artisan_logs')
    created_at=models.DateTimeField(default=timezone.now)
    removed_at=models.DateTimeField(null=True,blank=True)
    removed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='unlinked_artisan_logs')
    removal_reason=models.CharField(max_length=300,blank=True)
    class Meta:
        ordering=['-created_at','id']
        constraints=[models.UniqueConstraint(fields=['batch','source'],condition=Q(removed_at__isnull=True),name='unique_active_batch_artisan_log')]


class BatchPhoto(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    batch=models.ForeignKey(Batch,on_delete=models.PROTECT,related_name='photos')
    request_key=models.UUIDField(unique=True,editable=False)
    request_hash=models.CharField(max_length=64)
    sha256=models.CharField(max_length=64)
    source_name=models.CharField(max_length=180)
    image_data=models.BinaryField()
    thumbnail_data=models.BinaryField()
    image_format=models.CharField(max_length=10)
    width=models.PositiveIntegerField()
    height=models.PositiveIntegerField()
    origin=models.CharField(max_length=12,choices=[('camera','Camera capture'),('upload','Uploaded photo')])
    note=models.CharField(max_length=1200,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='recorded_batch_photos')
    created_at=models.DateTimeField(default=timezone.now)
    removed_at=models.DateTimeField(null=True,blank=True)
    removed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='unlinked_batch_photos')
    removal_reason=models.CharField(max_length=300,blank=True)
    class Meta:
        ordering=['-created_at','id']
        constraints=[models.UniqueConstraint(fields=['batch','sha256'],condition=Q(removed_at__isnull=True),name='unique_active_batch_photo')]


class SupplyItem(models.Model):
    name=models.CharField(max_length=120,unique=True)
    kind=models.CharField(max_length=12,choices=[('bags','Bags'),('labels','Label sheets'),('flavoring','Flavoring'),('other','Other supply')])
    unit=models.CharField(max_length=12,choices=[('each','Each'),('sheets','Sheets'),('ml','Milliliters'),('fl_oz','US fluid ounces'),('g','Grams'),('oz','Weight ounces')])
    size_oz=models.DecimalField(max_digits=6,decimal_places=1,null=True,blank=True)
    per_sheet=models.PositiveSmallIntegerField(null=True,blank=True)
    remaining=models.DecimalField(max_digits=12,decimal_places=1,default=0)
    reorder_at=models.DecimalField(max_digits=12,decimal_places=1,default=0)
    notes=models.CharField(max_length=2000,blank=True)
    active=models.BooleanField(default=True)
    version=models.PositiveIntegerField(default=0)
    recorded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:ordering=['kind','name']


class SupplyMovement(models.Model):
    item=models.ForeignKey(SupplyItem,on_delete=models.PROTECT,related_name='movements')
    action=models.CharField(max_length=12)
    before=models.DecimalField(max_digits=12,decimal_places=1)
    delta=models.DecimalField(max_digits=12,decimal_places=1)
    after=models.DecimalField(max_digits=12,decimal_places=1)
    note=models.CharField(max_length=300,blank=True)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    at=models.DateTimeField(default=timezone.now)
    request_key=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    class Meta:ordering=['-at','-pk']


class FlavorSupplyRate(models.Model):
    coffee=models.ForeignKey(Coffee,on_delete=models.PROTECT)
    item=models.ForeignKey(SupplyItem,on_delete=models.PROTECT)
    units_per_lb=models.DecimalField(max_digits=9,decimal_places=3)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    updated_at=models.DateTimeField(auto_now=True)
    version=models.PositiveIntegerField(default=0)
    class Meta:constraints=[models.UniqueConstraint(fields=['coffee','item'],name='unique_flavor_supply_rate')]


class MaintenanceTask(models.Model):
    roaster=models.ForeignKey(Roaster,on_delete=models.PROTECT)
    name=models.CharField(max_length=120)
    interval_days=models.PositiveIntegerField(null=True,blank=True)
    interval_batches=models.PositiveIntegerField(null=True,blank=True)
    instructions=models.CharField(max_length=2000,blank=True)
    active=models.BooleanField(default=True)
    version=models.PositiveIntegerField(default=0)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    class Meta:
        ordering=['roaster__name','name']
        constraints=[models.UniqueConstraint(fields=['roaster','name'],name='unique_roaster_maintenance_task')]


class MaintenanceService(models.Model):
    task=models.ForeignKey(MaintenanceTask,on_delete=models.PROTECT,related_name='services')
    date=models.DateField()
    note=models.CharField(max_length=2000,blank=True)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    recorded_at=models.DateTimeField(default=timezone.now)
    known_batches=models.JSONField(default=list)
    request_key=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    voided_at=models.DateTimeField(null=True,blank=True)
    voided_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='voided_maintenance_records')
    void_reason=models.CharField(max_length=300,blank=True)
    class Meta:ordering=['-date','-recorded_at','-pk']


class LoginAttemptWindow(models.Model):
    """Short-lived shared login limits; identities are keyed hashes, never raw."""
    key=models.CharField(max_length=64,primary_key=True)
    attempts=models.PositiveIntegerField(default=0)
    expires_at=models.DateTimeField(db_index=True)


class BeanSupplier(models.Model):
    name=models.CharField(max_length=160,unique=True)
    contact=models.CharField(max_length=160,blank=True)
    email=models.EmailField(blank=True)
    phone=models.CharField(max_length=60,blank=True)
    website=models.URLField(blank=True)
    country=models.CharField(max_length=100,blank=True)
    notes=models.TextField(blank=True)
    active=models.BooleanField(default=True)
    version=models.PositiveIntegerField(default=0)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:ordering=['name']
    def __str__(self):return self.name


class GreenBeanDetails(models.Model):
    item=models.OneToOneField(GreenBeanItem,on_delete=models.PROTECT,related_name='details')
    supplier=models.ForeignKey(BeanSupplier,on_delete=models.PROTECT,null=True,blank=True)
    country=models.CharField(max_length=100,blank=True)
    region=models.CharField(max_length=160,blank=True)
    farmer=models.CharField(max_length=160,blank=True)
    variety=models.CharField(max_length=160,blank=True)
    crop=models.CharField(max_length=80,blank=True)
    processing=models.CharField(max_length=120,blank=True)
    supplier_score=models.DecimalField(max_digits=5,decimal_places=2,null=True,blank=True)
    source_url=models.URLField(blank=True)
    roast_levels=models.JSONField(default=list,blank=True)
    flavor_tags=models.CharField(max_length=300,blank=True,help_text='Optional comma-separated flavor notes, for example cocoa, nuts, citrus. Used for substitution suggestions only.')
    caffeine=models.CharField(max_length=12,blank=True,choices=[('','Not recorded'),('regular','Caffeinated'),('decaf','Decaf')])
    version=models.PositiveIntegerField(default=0)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    updated_at=models.DateTimeField(auto_now=True)


class GreenPurchase(models.Model):
    item=models.ForeignKey(GreenBeanItem,on_delete=models.PROTECT)
    supplier=models.ForeignKey(BeanSupplier,on_delete=models.PROTECT,null=True,blank=True)
    supplier_name=models.CharField(max_length=160,blank=True)
    bean_name=models.CharField(max_length=120)
    received_on=models.DateField()
    quantity_oz=models.DecimalField(max_digits=12,decimal_places=1)
    total_cost=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    currency=models.CharField(max_length=3,default='USD')
    reference=models.CharField(max_length=120,blank=True)
    notes=models.TextField(blank=True)
    receipt=models.OneToOneField(GreenMovement,on_delete=models.PROTECT)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    voided_at=models.DateTimeField(null=True,blank=True)
    void_reason=models.CharField(max_length=300,blank=True)
    version=models.PositiveIntegerField(default=0)
    class Meta:ordering=['-received_on','-pk']


class CuppingRecord(models.Model):
    title=models.CharField(max_length=160)
    tasted_on=models.DateField()
    batch=models.ForeignKey(Batch,on_delete=models.PROTECT,null=True,blank=True)
    green_item=models.ForeignKey(GreenBeanItem,on_delete=models.PROTECT,null=True,blank=True)
    taster=models.CharField(max_length=120,blank=True)
    brew_method=models.CharField(max_length=120,blank=True)
    ratings=models.JSONField(default=dict)
    notes=models.TextField(blank=True)
    archived_at=models.DateTimeField(null=True,blank=True)
    archive_reason=models.CharField(max_length=300,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    version=models.PositiveIntegerField(default=0)
    class Meta:ordering=['-tasted_on','-pk']


class SourcingEvent(models.Model):
    kind=models.CharField(max_length=20)
    object_id=models.PositiveBigIntegerField()
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    before=models.JSONField(default=dict)
    after=models.JSONField(default=dict)
    request_key=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    reason=models.CharField(max_length=300,blank=True)
    at=models.DateTimeField(default=timezone.now)
    class Meta:ordering=['-pk']

class PortalConfiguration(models.Model):
    name=models.CharField(max_length=100,default='Crema')
    marketplaces=models.JSONField(null=True,blank=True,default=None,editable=False)
    flavor_base=models.ForeignKey(Coffee,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    frac_one=models.ForeignKey(Coffee,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    frac_two=models.ForeignKey(Coffee,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    frac_three=models.ForeignKey(Coffee,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    frac_four=models.ForeignKey(Coffee,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    shop_admin_url=models.URLField(blank=True,help_text='Optional Shopify Admin bookmark; not an API credential.')
    def clean(self):
        if self.pk not in [None,1]:raise ValidationError('Use the existing instance configuration.')
        if self.flavor_base_id and (not self.flavor_base.flavor_base_eligible or self.flavor_base.standard_roast!='Medium'):raise ValidationError('Default flavor base must be an eligible Medium coffee.')
        ids=[self.frac_one_id,self.frac_two_id,self.frac_three_id,self.frac_four_id]
        selected=[x for x in ids if x]
        if selected and (len(selected)!=4 or len(set(selected))!=4):raise ValidationError('Choose four different coffees, or leave all assortment coffees blank.')
        if selected and Coffee.objects.filter(pk__in=selected,active=True,experimental=False).count()!=4:raise ValidationError('Assortments require four active non-experimental coffees.')
    def save(self,*args,**kwargs):
        self.pk=1;self.full_clean();return super().save(*args,**kwargs)
    def __str__(self):return self.name


class StoreConnection(models.Model):
    PLATFORMS=[('shopify','Shopify'),('woocommerce','WooCommerce'),('wix','Wix'),('squarespace','Squarespace'),('csv','Orders CSV')]
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    name=models.CharField(max_length=120,unique=True)
    platform=models.CharField(max_length=20,choices=PLATFORMS)
    origin=models.URLField(max_length=250,blank=True)
    site_id=models.CharField(max_length=100,blank=True)
    credentials_cipher=models.TextField(blank=True)
    active=models.BooleanField(default=True)
    automatic=models.BooleanField(default=False)
    include_customer_names=models.BooleanField(default=False)
    version=models.PositiveIntegerField(default=0)
    last_attempt_at=models.DateTimeField(null=True,blank=True)
    last_success_at=models.DateTimeField(null=True,blank=True)
    last_error=models.CharField(max_length=300,blank=True)
    last_count=models.PositiveIntegerField(default=0)
    watermark=models.DateTimeField(null=True,blank=True)
    window_start=models.DateTimeField(null=True,blank=True)
    window_end=models.DateTimeField(null=True,blank=True)
    cursor=models.JSONField(default=dict)
    lease=models.UUIDField(null=True,blank=True)
    lease_at=models.DateTimeField(null=True,blank=True)
    csv_mapping=models.JSONField(default=dict)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        ordering=['name']
        constraints=[
            models.UniqueConstraint(fields=['platform','origin'],condition=Q(platform__in=['shopify','woocommerce','squarespace']) & ~Q(origin=''),name='unique_connected_store_origin'),
            models.UniqueConstraint(fields=['site_id'],condition=Q(platform='wix') & ~Q(site_id=''),name='unique_connected_wix_site'),
        ]
    def __str__(self):return self.name

class StoreProductMapping(models.Model):
    store=models.ForeignKey(StoreConnection,on_delete=models.PROTECT)
    product_key=models.CharField(max_length=64)
    title=models.CharField(max_length=500)
    sku=models.CharField(max_length=150,blank=True)
    coffee=models.ForeignKey(Coffee,on_delete=models.PROTECT,null=True,blank=True)
    label_variant=models.ForeignKey(LabelVariant,on_delete=models.PROTECT,null=True,blank=True)
    size_oz=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    grind=models.CharField(max_length=12,choices=GRIND_CHOICES,default='unknown')
    skip=models.BooleanField(default=False)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:constraints=[models.UniqueConstraint(fields=['store','product_key'],name='unique_mapping_per_store_product')]

class StoreSyncRun(models.Model):
    store=models.ForeignKey(StoreConnection,on_delete=models.PROTECT,related_name='runs')
    started_at=models.DateTimeField(default=timezone.now)
    finished_at=models.DateTimeField(null=True,blank=True)
    state=models.CharField(max_length=20,default='running')
    count=models.PositiveIntegerField(default=0)
    message=models.CharField(max_length=300,blank=True)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True)

class StoreEvent(models.Model):
    store=models.ForeignKey(StoreConnection,on_delete=models.PROTECT)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    action=models.CharField(max_length=30)
    at=models.DateTimeField(default=timezone.now)
    details=models.JSONField(default=dict)

class CompanionDevice(models.Model):
    """Opaque, revocable preparation-only credentials; never store bearer secrets."""
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    name=models.CharField(max_length=80)
    created_at=models.DateTimeField(default=timezone.now)
    last_seen_at=models.DateTimeField(null=True,blank=True)
    revoked_at=models.DateTimeField(null=True,blank=True)
    access_hash=models.CharField(max_length=64,unique=True)
    refresh_hash=models.CharField(max_length=64,unique=True)
    access_expires_at=models.DateTimeField()
    refresh_expires_at=models.DateTimeField()
    auth_fingerprint=models.CharField(max_length=64)

class CompanionGrant(models.Model):
    device_hash=models.CharField(max_length=64,primary_key=True)
    code_hash=models.CharField(max_length=64,unique=True)
    name=models.CharField(max_length=80)
    expires_at=models.DateTimeField()
    next_poll_at=models.DateTimeField()
    interval=models.PositiveIntegerField(default=5)
    state=models.CharField(max_length=12,default='pending')
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,null=True)

class OrderImportPreview(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    store=models.ForeignKey(StoreConnection,on_delete=models.PROTECT)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(default=timezone.now)
    headers=models.JSONField(default=list)
    rows=models.JSONField(default=list)
    applied_at=models.DateTimeField(null=True,blank=True)
    count=models.PositiveIntegerField(default=0)
    mapping_hash=models.CharField(max_length=64,blank=True)
    store_version=models.PositiveIntegerField(default=0)
