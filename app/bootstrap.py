import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','project_settings')
import django;django.setup()
from portal.models import LabelQueueLock,RoastedStockLock,ShopifyCatalog,PortalConfiguration
for model in [LabelQueueLock,RoastedStockLock,ShopifyCatalog,PortalConfiguration]:model.objects.get_or_create(pk=1)
