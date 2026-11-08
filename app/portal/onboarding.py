"""Read-only setup guidance: configuration evidence is not an operator sign-off."""
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.utils import timezone
from .models import (Coffee, Roaster, PortalConfiguration, GreenBeanItem,
                     StoreConnection, ShopifyConnection, CostProfile, CompanionDevice)


def checklist(user):
    from .marketplaces import selection
    from .green_stock import recipe_percentages
    from .label_sheets import catalog as artwork_catalog
    from .artisan_profiles import library_entries
    from .costing import estimate
    from django.contrib.auth import get_user_model
    config = PortalConfiguration.objects.filter(pk=1).first()
    coffees = list(Coffee.objects.filter(active=True).order_by('name'))
    roasters = list(Roaster.objects.filter(active=True).order_by('name'))
    demo = settings.PORTAL_DEMO_MODE
    steps = []

    def add(key, title, detail, ready, links, *, core=False, issues=(), manual=False):
        steps.append({'key': key, 'title': title, 'detail': detail,
                      'state': 'Review in person' if manual else 'Configured' if ready else 'Needs attention',
                      'ready': bool(ready) and not manual, 'core': core,
                      'issues': list(issues)[:12], 'extra_issues': max(0, len(issues)-12),
                      'links': [{'url': url, 'label': label} for url, label in links]})

    config_issues = []
    if config:
        try: config.full_clean()
        except ValidationError: config_issues.append('Review the roastery name, default flavor base and four-coffee assortment settings.')
    else: config_issues.append('Save your roastery configuration.')
    links = []
    if not demo and user.has_perm('portal.change_portalconfiguration'):
        links.append(('/admin/portal/portalconfiguration/', 'Name & assortments'))
    links.append(('/help/#setup', 'Setup guide'))
    add('identity', 'Name & preferences', 'Current timezone: '+settings.TIME_ZONE+'. Change the deployment timezone before recording time-sensitive work.',
        bool(config) and not config_issues, links, core=True, issues=config_issues)

    machine_issues = []
    for machine in roasters:
        try: machine.full_clean()
        except ValidationError: machine_issues.append(machine.name+': review minimum and maximum green-input limits.')
        if machine.min_green_oz == 0: machine_issues.append(machine.name+': minimum load is unset; confirm whether this is appropriate.')
    if not roasters: machine_issues.append('Add at least one active roaster with its safe green-input limits.')
    links = [('/artisan/', 'Profiles & alarms')]
    if user.has_perm('portal.change_roaster'): links.insert(0, ('/admin/portal/roaster/', 'Manage roasters'))
    add('machines', 'Machine limits', str(len(roasters))+' active machines. Saved limits do not certify physical capacity or alarm behavior.',
        bool(roasters) and not machine_issues, links, core=True, issues=machine_issues)

    coffee_issues = []
    for coffee in coffees:
        try: coffee.full_clean()
        except ValidationError: coffee_issues.append(coffee.name+': review its type, roast and flavor-base rules.')
    if not coffees: coffee_issues.append('Add your own coffees and their standard roasts. No real catalog is bundled.')
    if any(c.kind == 'flavored' for c in coffees) and (not config or not config.flavor_base_id):
        coffee_issues.append('Choose an eligible Medium default base for flavored coffees.')
    links = [('/products/', 'Product checks')]
    if user.has_perm('portal.change_coffee'): links.insert(0, ('/admin/portal/coffee/', 'Manage coffees'))
    add('coffees', 'Coffees & roast rules', str(len(coffees))+' active coffees. Check single-origin customization, blends, flavors and experimental origins.',
        bool(coffees) and not coffee_issues, links, core=True, issues=coffee_issues)

    physical = [c for c in coffees if c.kind != 'flavored' and not c.roast_base_id and not c.experimental]
    missing = [c.name+': no usable recipe with active origins totaling 100%.' for c in physical if not recipe_percentages(c.pk)]
    add('inventory', 'Green recipes & bulk counts',
        str(GreenBeanItem.objects.filter(active=True).count())+' active green origins. Optional for planning; usable recipes are needed for automatic green tracking. Bagged/on-deck sacks are not ready bucket stock. Bulk counts need a fresh physical measurement.',
        bool(physical) and not missing, [('/green-beans/', 'Green beans & recipes'), ('/purchases/', 'Receipts & on-deck notes'), ('/stock/', 'Count roasted bulk')], issues=missing)

    chosen = selection(config)
    stores = list(StoreConnection.objects.filter(active=True).exclude(platform='csv'))
    legacy = ShopifyConnection.objects.filter(connected_at__isnull=False, access_token_cipher__gt='').exists()
    store_issues = []
    for platform in chosen:
        if platform == 'manual': continue
        matches = [s for s in stores if s.platform == platform]
        if not matches and not (platform == 'shopify' and legacy): store_issues.append(platform.title()+': no saved connection. CSV/manual orders can be used meanwhile.')
        elif matches and any(not s.last_success_at or s.last_error for s in matches): store_issues.append(platform.title()+': run a successful order refresh and review mappings.')
    if not config or config.marketplaces is None: store_issues.append('Choose one or more marketplaces, or explicitly choose manual orders / CSV only.')
    links = [('/imports/', 'Review orders'), ('/wholesale/', 'Wholesale order')]
    if not demo: links.insert(0, ('/stores/', 'Choose marketplaces'))
    add('orders', 'Order sources', 'Saved connections are not a live compatibility certification. Shopify is operationally tested; other adapters still need authorized merchant testing. Manual orders and CSV remain available.',
        bool(chosen) and not store_issues, links, issues=store_issues)

    artwork = artwork_catalog()
    artwork_names = {a['coffee'] for a in artwork if not a.get('blocked')}
    art_issues = [c.name+': no available artwork found.' for c in coffees if not c.experimental and c.name not in artwork_names]
    add('artwork', 'Artwork & label alignment', str(len(artwork))+' catalog artwork records. A coffee match does not establish coverage of every bag size, special label or roast. Review the artwork matrix and print an alignment test on plain paper.',
        bool(artwork) and not art_issues, [('/labels/artwork/', 'Review artwork matrix'), ('/help/#bagging', 'Printing guide')], issues=art_issues)

    profiles = list(CostProfile.objects.filter(active=True).select_related('coffee', 'label_variant'))
    cost_issues = []
    for profile in profiles:
        try:
            result = estimate(profile)['result']
            if not result['production_complete'] or result['missing_selling'] or any(c['price'] is None for c in result['channels']):
                cost_issues.append(profile.name+': cost or selling assumptions are incomplete.')
        except ValidationError: cost_issues.append(profile.name+': review its cost sources.')
    if not profiles: cost_issues.append('Add a cost profile when actual costs are known; blank inputs remain unknown.')
    add('costs', 'Costs & margins', str(len(profiles))+' active profiles. These are optional management estimates. Completeness does not verify the prices or account for every product size.',
        bool(profiles) and not cost_issues, [('/costing/', 'Set up costing'), ('/help/#costing', 'Costing guide')], issues=cost_issues)

    profile_count = len(library_entries())
    linked = CompanionDevice.objects.filter(user__is_active=True, revoked_at__isnull=True, refresh_expires_at__gt=timezone.now()).count()
    add('companion', 'Artisan & Companion', str(profile_count)+' reference profiles; '+str(linked)+' unrevoked, unexpired paired computers. Pairing is not proof that a computer is online. Optional: verify the selected machine, background and alarms while Artisan is idle.',
        bool(profile_count) and bool(linked), [('/artisan/', 'Review profiles'), ('/companion/install/', 'Install Companion'), ('/companion/', 'Paired computers')] if settings.COMPANION_ENABLED else [('/artisan/', 'Review profiles'), ('/help/#artisan', 'Artisan guide')])

    users = get_user_model().objects.filter(is_active=True)
    links = [('/help/#hours', 'Hours & permissions guide')]
    if not demo and user.has_perm('auth.change_user'): links.insert(0, ('/admin/auth/user/', 'Review individual accounts'))
    add('people', 'People & permissions', str(users.count())+' active accounts. Review individual sign-ins, staff access and separate pay-manager permissions; account counts alone do not verify access.', False, links, manual=True)
    links = [('/help/#security', 'Recovery guide')]
    if not demo and user.is_superuser: links.insert(0, ('/recovery/', 'Records & recovery'))
    add('recovery', 'Backup & first-day rehearsal', 'Confirm a consistent database backup with matching instance keys, an independent restore, and a full trial from order review through packing. This page cannot verify an external backup or physical test.', False, links, manual=True)
    core = [s for s in steps if s['core']]
    return {'steps': steps, 'core_ready': sum(s['ready'] for s in core), 'core_total': len(core),
            'next_step': next((s for s in steps if not s['ready']), None), 'demo_preview': demo}


@staff_member_required
@require_GET
def getting_started(request):
    return render(request, 'portal/setup.html', checklist(request.user))
