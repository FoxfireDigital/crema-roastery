from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.contrib.auth import get_user_model
from portal.models import Coffee,Roaster,PortalConfiguration,BeanSupplier,GreenBeanItem,GreenBeanDetails,PayrollAccess
class Command(BaseCommand):
    help='Install clearly fictional sample catalog only in an otherwise empty business database.'
    def add_arguments(self,parser):parser.add_argument('--owner',required=True)
    @transaction.atomic
    def handle(self,*args,**opts):
        if Coffee.objects.exists() or Roaster.objects.exists() or GreenBeanItem.objects.exists():raise CommandError('Demo requires an empty catalog and inventory. It will not overwrite real work.')
        try:owner=get_user_model().objects.get(username=opts['owner'],is_superuser=True)
        except get_user_model().DoesNotExist:raise CommandError('Create your administrator first and use its username.')
        names=[('Demo Dawn','Light/Medium'),('Demo Hearth','Medium'),('Demo Night','Dark'),('Demo Summit','Medium/Dark')]
        coffees=[Coffee.objects.create(name=n,kind='blend',standard_roast=r) for n,r in names]
        Coffee.objects.create(name='Demo Single Origin',kind='single_origin',standard_roast='Medium')
        Coffee.objects.create(name='Demo Vanilla',kind='flavored',standard_roast='Medium',roast_base=coffees[1],bulk_stock_enabled=False)
        Coffee.objects.create(name='Experimental',experimental=True,bulk_stock_enabled=False)
        Roaster.objects.create(name='Demo Small',max_green_oz=40);Roaster.objects.create(name='Demo Large',max_green_oz=140)
        c,_=PortalConfiguration.objects.get_or_create(pk=1);c.flavor_base=coffees[1];c.frac_one,c.frac_two,c.frac_three,c.frac_four=coffees;c.save()
        supplier=BeanSupplier.objects.create(name='Example Cooperative (fictional)',country='Example country',updated_by=owner)
        item=GreenBeanItem.objects.create(name='Demo washed lot — count before use',remaining_oz=0,recorded_by=owner)
        GreenBeanDetails.objects.create(item=item,supplier=supplier,country='Example country',processing='Washed',updated_by=owner)
        PayrollAccess.objects.get_or_create(user=owner,defaults={'manages_rates':True})
        self.stdout.write('Fictional catalog installed. No orders, hours, stock, roasts, labels or profiles were fabricated.')
