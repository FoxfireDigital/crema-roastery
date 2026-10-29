import os,time
os.environ.setdefault('DJANGO_SETTINGS_MODULE','project_settings')
import django;django.setup()
from portal.shopify_automatic import tick
from portal.stores import tick_stores
while True:
    try:
        print(tick(),flush=True);tick_stores()
    except Exception:print('Automatic check failed; inspect the connection screen and retry.',flush=True)
    time.sleep(60)
