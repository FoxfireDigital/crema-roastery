from django.core.management.base import BaseCommand
from portal.shopify_automatic import tick


class Command(BaseCommand):
    help='Process signed Shopify notifications and periodic reconciliation.'
    def handle(self,*args,**options):self.stdout.write(tick())
