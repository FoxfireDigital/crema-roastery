# Crema

Self-hosted coffee production planning, from received orders through roasting, packing and labels. **MIT-licensed source beta**, with one separate installation and database per roastery.

[Guided setup](docs/GETTING-STARTED.md) · [Public beta review](docs/PUBLIC-BETA-REVIEW.md)

The source is available for self-hosting, review and contributions. Install by building the included Docker Compose YAML. Prebuilt service images and Windows Companion installers are a separate distribution step; the repository does not promise a public image registry or a one-click hosted service. This beta has automated checks and operational use, but has not received an independent security audit. Back up important records and rehearse upgrades on a restored copy.

## What it includes

- Reviewed product costs, receipt/recipe sourcing, planned/actual yield, retail and wholesale margins, saved estimates and CSV exports. Read-only Shopify catalog price links; missing costs remain unknown. See [costing guide](docs/COSTING.md).

- Shopify read-only order/product checks and CSV imports, duplicate protection, subscription assortments, wholesale orders and dismissals.
- Experimental: store-specific order adapters for Shopify, WooCommerce, Wix and Squarespace, plus a mapped CSV preview. New adapters have synthetic coverage; merchant-account verification is pending. See docs/MARKETPLACES.md.
- Stock-first planning, separate custom roasts, safe configured machine capacities, actual yield history by machine/load, and clear finished-weight coverage.
- Green recipes and automatic measured-load deductions, supplier contacts, receipt costs, bean details and a tasting notebook with flavor charts.
- Bagging/grind instructions, user-supplied retail/wholesale artwork, Letter PDFs and optional final-sheet fillers.
- Editable single-origin order roasts across bag sizes, explicit standard-artwork exceptions, configurable printed grind marks and label-first packing checklists shared between Today and Bagging.
- Artisan profile uploads, guarded alarm preparation, completed logs, an optional Windows helper and optional roast photos.
- Manual supply inventory, maintenance, forecasts, editable audited hours, effective-dated rates and downloadable records.

## Primary deployment: Compose YAML

`compose.yaml` is the main installation artifact. Use Docker Compose 2.23.1+ on a dedicated Docker host. Edit the image reference, domain, HTTPS origin and time zone at the top of the YAML. The domain must resolve to this host, with ports 80/443 available for its included Caddy proxy. The file contains the proxy configuration; no separate Caddyfile or host-side Python is required.

The YAML starts a one-time initializer, PostgreSQL, the web app, the background worker and HTTPS proxy. Unique keys are created inside a dedicated persistent Docker volume. They survive restarts and upgrades. No default administrator or password is supplied.

### Build and install the source beta

Clone this repository, enter its directory, and edit `compose.yaml` for your domain and time zone. Build all three service images, then deploy:

```sh
docker compose -f compose.yaml -f compose.build.yaml build web postgres proxy
docker compose config --quiet
docker compose up -d
docker compose exec web python manage.py createsuperuser
```

The YAML uses `pull_policy: never` for the locally built services. Database and proxy builds extend pinned official PostgreSQL and Caddy base images and apply the package changes described in [service images](docs/SERVICE-IMAGES.md). Public prebuilt images will need their own reviewed versions, digests and distribution notices; source availability does not imply those images are published.

Visit your HTTPS domain and sign in. Open the first-run “Set up your roastery” checklist, also under More → Roastery setup. PostgreSQL and the app have no public host ports; only the proxy publishes 80/443. If those ports belong to an existing NAS interface or proxy, follow docs/DEPLOYMENT.md rather than starting another proxy on them. This release does not change DNS, NAS addresses or existing applications.

TrueNAS users can use a reviewed Custom App Compose definition once the application image is available on that host. See docs/TRUENAS.md for storage and proxy adaptations. YAML compatibility has been tested using the NAS Compose engine; this does not certify every third-party stack manager or the TrueNAS app-form path.

## Existing review installations

New installations use the Compose project name `crema`. If you already installed an earlier Roastery Portal candidate, keep its existing project name when using this YAML: for example `docker compose -p roastery_portal up -d`. This retains its named volumes. Do not start a second project expecting it to find the old database. Keep the same instance keys and follow the rc1-to-rc2 key migration notes if applicable. Existing saved display names remain configurable in Administration → Portal configuration; this rename does not overwrite them.

## First setup

1. Administration → Roasters: add machine names and safe **green input** capacities in ounces.
2. Administration → Coffees: add origins/blends/flavors and standard roasts. For flavors, select a full-caffeine Medium base. Disable flavor-base eligibility for decaf/half-caff or other unsuitable coffee.
3. Administration → Portal configuration: set your name, optional four-coffee frac assortment, default Medium base and Shopify Admin bookmark. No supplier recipe, customer list or artwork is bundled.
4. Green beans: enter current lots/counts and recipes totalling 100%. Counts must exclude already measured loads.
5. Add staff accounts as needed. Grant PayrollAccess deliberately to whoever manages rates. Upload your own artwork and Artisan files; preview and validate before use.
6. Configure and test backups before storing important work. See docs/BACKUPS.md.

For a **disposable empty trial installation**, optionally load fictional catalog examples:

```sh
docker compose exec web python manage.py portal_demo --owner YOUR_ADMIN_USERNAME
```

This refuses an existing catalog and creates no orders, stock, hours, roasted results or artwork. There is no automatic demo-to-production cleanup; use a separate clean installation for real work.

## Operating and updating

The worker checks enabled Shopify connections once a minute and honors the saved reconciliation interval. Each merchant configures and authorizes their own app; see docs/SHOPIFY.md. Other features work without Shopify, cameras or Artisan.

Before an upgrade, make a verified backup and test the new version against a restored copy. For this source candidate, rebuild with the optional build file, then use `docker compose up -d`. For a published image, pull the reviewed version before recreating the services. Startup applies schema migrations; rolling application code backward after a schema change may require a tested database restore. Never use `docker compose down -v` on a valuable installation.

## Community and services

MIT allows self-hosting, modification, paid hosting, setup, migration and support. The license does not grant rights to somebody else’s artwork, trademarks, customer data or roast profiles. Start managed services with separate installations; this is not a shared multi-tenant service or billing platform.

See CONTRIBUTING.md, SECURITY.md, PRIVACY.md and docs/RELEASE.md. No telemetry, shared cloud account or production dataset is included.

See [ROADMAP.md](ROADMAP.md) for the proposed stages to 1.0, release acceptance criteria and subsequent 1.x priorities. The production front page remains the accepted roast sheet.

The generic image includes component declarations and available notices. See [image review](docs/IMAGE-REVIEW.md) for source/revision verification, build-context checks and remaining distribution gates. Dependencies retain their own licenses.

The Linux [deployment/recovery trial](docs/DEPLOYMENT-QA.md) verifies fictional data restored into separate volumes. The [distribution worksheet](docs/DISTRIBUTION-REVIEW.md) tracks dependency/native-library questions that still need review.

Roast-day corrections, early subscriptions and saved wholesale accounts: [operator guide](docs/roast-day-corrections.md).
