from .models import PortalConfiguration
def configuration():return PortalConfiguration.objects.filter(pk=1).first()
def assortment_names():
    c=configuration()
    return [x.name for x in [c.frac_one,c.frac_two,c.frac_three,c.frac_four] if x] if c else []
def default_base():
    c=configuration();return c.flavor_base if c else None
def instance_context(request):
    from django.conf import settings
    from .models import Coffee,Roaster
    needs_setup=request.user.is_authenticated and request.user.is_staff and (not Coffee.objects.filter(active=True).exists() or not Roaster.objects.filter(active=True,max_green_oz__gt=0).exists())
    from .marketplaces import selection
    c=configuration();platforms=selection(c) if request.user.is_authenticated else []
    return {'portal_name':c.name if c else 'Crema','portal_timezone':settings.TIME_ZONE,'portal_demo_mode':settings.PORTAL_DEMO_MODE,'shop_admin_url':c.shop_admin_url if c else '','needs_roastery_setup':needs_setup,'chosen_marketplaces':platforms,'shopify_selected':'shopify' in platforms}

from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_GET
from django.shortcuts import render
@staff_member_required
@require_GET
def setup_page(request):
    from .models import Coffee,Roaster,GreenBeanItem,LabelArtwork,ShopifyConnection,PayrollAccess
    return render(request,'portal/setup.html',{'coffee_count':Coffee.objects.filter(active=True).count(),'machine_count':Roaster.objects.filter(active=True,max_green_oz__gt=0).count(),'green_count':GreenBeanItem.objects.filter(active=True).count(),'art_count':LabelArtwork.objects.filter(active=True).count(),'connected':ShopifyConnection.objects.filter(connected_at__isnull=False).exists(),'pay_managers':PayrollAccess.objects.filter(manages_rates=True).count()})
