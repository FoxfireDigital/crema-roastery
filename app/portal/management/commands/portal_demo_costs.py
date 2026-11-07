"""Optional cost examples for the isolated shared demonstration only."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.http import QueryDict
from portal.costing import save_profile, ticket
from portal.models import Coffee, CostProfile


class Command(BaseCommand):
    help = 'Add clearly illustrative cost profiles to the confined fictional demo, without overwriting any existing profile.'

    def add_arguments(self, parser):
        parser.add_argument('--owner', required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        allowed = {'Demo Dawn', 'Demo Hearth', 'Demo Night', 'Demo Summit', 'Demo Single Origin', 'Demo Vanilla', 'Experimental'}
        if not settings.PORTAL_DEMO_MODE or set(Coffee.objects.values_list('name', flat=True)) != allowed:
            raise CommandError('Cost examples require the confined, exact fictional demo catalog. No real installation is seeded.')
        try:
            actor = get_user_model().objects.get(username=options['owner'], is_active=True, is_superuser=True)
        except get_user_model().DoesNotExist:
            raise CommandError('Use the existing demonstration administrator.')
        examples = [('Demo Hearth', '16', 'Medium', '5', '85', '.6', '0', '18', '12'),
                    ('Demo Vanilla', '12', 'Medium', '5', '85', '.55', '.25', '17', '11'),
                    ('Demo Single Origin', '80', 'Medium', '', '82', '1', '0', '65', '50')]
        created = 0
        for name, size, roast, green, yield_pct, bag, flavor, retail, wholesale in examples:
            title = name + ' ' + size + ' oz — illustrative costs'
            if CostProfile.objects.filter(name=title).exists():
                continue
            data = QueryDict('', mutable=True)
            data.update({'ticket': ticket(actor), 'name': title, 'coffee': str(Coffee.objects.get(name=name).pk),
                         'roast_level': roast, 'size_oz': size, 'currency': 'USD', 'active': 'on', 'yield_pct': yield_pct,
                         'green_cost_per_lb': green, 'bag_cost': bag, 'label_cost': '.1', 'flavor_cost': flavor,
                         'labor_minutes': '2', 'labor_rate': '18', 'other_production_cost': '.15',
                         'retail_price': retail, 'wholesale_price': wholesale, 'fee_pct': '2.9', 'fixed_fee': '.3',
                         'other_selling_cost': '0', 'wholesale_fee_pct': '0', 'wholesale_fixed_fee': '0', 'wholesale_other_selling_cost': '0',
                         'change_note': 'Illustrative demo amounts only. The single-origin example intentionally leaves its green price unknown.'})
            save_profile(data, actor)
            created += 1
        self.stdout.write('Fictional cost profiles added: ' + str(created) + '. Existing profiles, physical stock, orders, hours and production unchanged.')
