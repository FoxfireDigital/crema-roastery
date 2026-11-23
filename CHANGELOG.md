# Changelog

## Unreleased — configurable coffee boxes

* Configure coffee boxes in Administration with exact source titles, optional SKUs, a default grind and individually labeled bag components. Empty or inactive recipes never silently drop coffee demand.
* Expand imported quantities into separate roast/packing rows; retain original sold-box counts, protect component composition during review, and carry explicit grind choices through to labels.
* Keep installation-specific products and artwork outside the public source.

## 0.1.0-rc29 — public source beta

* Make the generic MIT source available with source-build Compose instructions. Public image/installer distribution and independent security review remain separate work.
* Edit single-origin roasts on planned orders across bag sizes, with stale-edit checks and preservation of completed work.
* Display ordinary bag weights, allow explicit standard-artwork overrides for custom roasts, and configure grind-checkbox marks per artwork with snapshot checks.
* Put labeling first in packing, followed by flavoring/grinding where needed, bagging and sealing. Today and Bagging share the same saved progress.
* Update the matching Debian libpq build/runtime pins to 15.20-0+deb12u1 after the previous version left the current archive.
* Verify offline image configuration hashes on both classic and containerd Docker stores, retaining registry manifest and layer-integrity checks.

## 0.1.0-rc28 candidate — patched package manager

Pins Debian APT and libapt-pkg6.0 to 2.6.2 in the application build/runtime and database image. Initial package operations disable retry reuse while the older base package manager installs the fix. Exact-image checks assert the patched package versions. Remaining vendor findings are retained for assessment.

## 0.1.0-rc27 candidate — guided setup and exact release review

Adds a read-only Getting started checklist, live missing-configuration indicators and existing-screen action buttons. Shared demo gets a confined fictional preview. Adds bounded source/history/manifest/archive review tooling and current public-beta decision/evidence instructions. No schema, stock, account, order or hardware changes.

## 0.1.0-rc26 candidate — costs and margins

* Add staff-only product cost profiles, receipt/recipe-based or manual green costs, planned and actual-batch yield, packaging/flavor/labor allocations, retail and wholesale production/contribution comparisons and per-order fixed-fee allocation. Unknown costs remain unknown; currencies remain separate.
* Retain reviewed calculations in immutable dated snapshots with source references, audited stale/replay guards and formula-safe CSV exports. Costing never changes inventory, production or employee pay.
* Read Shopify variant list prices, currency and tax treatment during catalog checks. Link a price only after explicit matching; no store writes, tax guesses or fabricated revenue.
* Add costing help and a financial-workflow regression suite. Public-source, hosting and Companion release gates remain unchanged.

## 0.1.0-rc25 candidate — partial-refund production handling

* Reorganize Help into linked roast-day chapters, with bagged/on-deck and measured-bucket guidance, finished totals, completed-record corrections, Companion and saving help. Identify manual workflows without promising unavailable transfer/correction controls. Add an offline user guide.

* Recognize paid and partially refunded orders throughout import readiness, active-plan holds, subscription renewal linking and completion. Preserve original payment status and all cancellation, changed-item, fulfillment and duplicate checks.
* Explain shipping refunds/local pickup and remaining item quantities on imports and in the how-to. Retain completed orders in their existing plans rather than flagging them as new early-subscription renewals.

## 0.1.0-rc24 candidate — compact Companion and roast-day corrections

* Show saved wholesale business names in the account selector instead of internal model record labels.
* Companion 0.2.0-preview.2 uses the compact preparation/quick-view layouts, rounded cards and the account palette. X and Hide to tray retain the process; the coffee tray menu offers Quick view, Open and Exit. Reopening a shortcut restores the existing window without an Artisan handoff.
* Add authenticated Windows installer/portable/source downloads inside Crema, using an administrator-published read-only release with exact checksums; no remote installation or silent update.
* Explain marketing-site, redirect, gateway and invalid-API connection responses. Keep remembered portal origins separate from protected credentials.
* Add an audited per-load green-weight override for started/accepted plans, including explicit exceptions to configured capacity. Preserve results/packing and reconcile measured green usage by the difference using the saved recipe.
* Resolve subscription CSV variants using saved product/contract details without requiring a private mapping file; reject unknown variants without overwriting existing contracts.
* Review known subscriptions due in the next four days, require per-cycle assortment choices, and explicitly link later renewals to early production without duplicate demand or inferred payment.
* Put saved wholesale accounts at the top of order entry, support account creation without an order, and enforce account-exclusive coffees. Keep private customer/catalog seeds outside the product source.
* Close plans using Measured/Roasted/Cooled plus customer packing, removing the obsolete per-batch Bagged/Sealed requirement. Add backward-write-compatible defaults to additive fields; preserve existing closure snapshots.
* See docs/roast-day-corrections.md and the in-app how-to. These notes describe the candidate; deployment evidence is recorded separately.

## 0.1.0-rc23 candidate — connected Companion

* Add opt-in browser-approved device connections with revocation, expiring/rotating protected credentials and preparation-only API capabilities.
* List accepted, active unroasted loads and matching approved profiles; retrieve the signed-in user's saved palette and installation name. Recheck snapshots before connected handoffs.
* Companion 0.2.0-preview.1 renders the preparation-window design using bundled HTML/CSS in WebView2, retaining the reviewed Artisan transport and explicit operator checks. Keep the classic offline window and preparation ZIP fallback.
* Add two device/pairing tables. Existing production, stock, orders, evidence and hours are unchanged. See docs/companion-connections.md for migration, permissions and operator acceptance gates.

## 0.1.0-rc22 — direct batch photo and log controls

* Put Capture photo and Upload .alog directly under each coffee on Today and at the top of batch details, with the same actions on planner batch cards. Pending loads show disabled controls; recording a roast enables the controls without a reload.
* Capture opens the existing batch camera preview when supported, keeping permission, review, retake and save explicit. Ordinary photo-page visits keep the camera off.
* Preselect the latest matching saved preparation when uploading a completed log; retain explicit comparison changes and blank selections. Measurements, stock, existing attachments and plan history are unchanged. No schema or Companion change.

## 0.1.0-rc21 — configured minimum green loads

- Roasters have configurable minimum and maximum green input. Automatic suggestions meet the minimum and show extra green/finished coffee; zero demand creates no roast. Manual sizing, splits, exact-total combining, acceptance, yield adjustments and Artisan preparations enforce the same bounds.
- Machine-policy changes invalidate stale roast-sheet and preparation tokens. Recorded physical and historical roasts retain their original inputs.
- Occasional standard-roast single-origin leftovers can be recorded as measured bulk whole beans without changing the regular quick-count list. Measurement replay retains one stock entry; estimates and roast checkboxes never credit stock automatically.


## 0.1.0-rc20 — previewed manual draft combining

* Add Combine / rebalance drafts on Plans. Select matching unstarted loads, choose a roaster and preview balanced replacements that preserve the selected green total.
* Preserve unselected load weights and per-order labels/grind/bags, retain original drafts and audit history, and require reviewing/reaccepting an edited plan.
* Protect physical production, used stock, packing, green-origin decisions and legacy workflows; reject stale, expired, replayed or cross-account confirmations.

## 0.1.0-rc19 — shared roast loads across packaging labels

* Pool matching coffee, roast level and finish-temperature requirements across retail and wholesale labels. Keep each order's label, grind and bag sizes on its packing allocation.
* Consolidate only unstarted automatic groups with matching loss settings. Retain superseded draft rows and an audit event; leave measured/started work, manual sizing, used stock and historical/legacy plans intact.

## 0.1.0-rc18 — Today packing cards and isolated demo roles

* Show collapsible customer/order packing cards and per-plan label-sheet buttons on Today. Reuse Bagging forms, progress records, audit events, CSRF and stale-edit checks; keep roast-row cooling separate.
* Add an opt-in demonstration boundary that disables connections, recovery, installation settings and account administration even for a demo administrator. Ordinary installations keep their existing permissions. Requires a separate fictional-data database and isolated network.

## 0.1.0-rc17 — read-only proxy installation correction

* Bake the reviewed default Caddyfile into the proxy image. This avoids Compose trying to create an inline configuration inside a read-only root filesystem. Verify the baked file against the source and use a read-only file override for local TLS testing.
* Retain the failed rc16 installation evidence; repeat the exact artifact, YAML and recovery rehearsal for this replacement candidate.

## 0.1.0-rc16 — service images and distribution rehearsal

* Build the pinned Caddy release with patched Go dependencies in a minimal proxy image, using a traced CA trust bundle and compiled-module notices. Disable its administration API and restrict filesystem writes/capabilities.
* Rebuild the upstream database privilege-drop helper with the patched Go toolchain/dependencies, preserving PostgreSQL 16 and the original entrypoint/data layout; refresh timezone data.
* Build Pillow and CFFI against system libraries from verified sources. Preserve the portal’s PNG/JPEG/WebP support while excluding unused optional image/font codecs and their separate bundled libraries. Capture asset/browser/font notices alongside package metadata.
* Add exact service-image verification, checked offline image loading and an anonymous local-registry rehearsal that downloads complete blobs, verifies layer/config hashes, renders digest-pinned YAML, and exercises installation plus recovery. Public publication remains a separate approval gate.

## 0.1.0-rc15 — retained-source access correction

* Make the retained driver source archive readable by the non-root runtime user. Exact-image verification caught the upstream download’s restrictive default permissions in the unpromoted rc14 candidate.
* Retain rc14’s system-linked C driver, source/build provenance and runtime cleanup. Fresh image, deployment and recovery checks are required for this replacement candidate.

## 0.1.0-rc14 — database-client distribution correction

* Build Psycopg’s C extension from its checksum-verified source against the system PostgreSQL client; remove the bundled binary client wheel. Retain the extension source, build-tool versions and source/wheel hashes in the runtime image.
* Keep compilers and headers in a separate build stage. Verify the C implementation, system-library linkage, source integrity and absence of bundled/build-only distributions.
* Pin matching libpq headers/runtime and refresh tzdata. Source-based CI explicitly installs client headers. No application behavior or database schema change.

## 0.1.0-rc13 — frozen-beta review corrections

* Escape formula-like employee names in the legacy timesheet CSV and label payroll clocks/exports with their configured timezone.
* Reject non-finite custom-order green weights and malformed/out-of-range machine identifiers without creating production or returning an unhandled error.
* Remove the package installer and bootstrap wheel from the runtime filesystem, including installer-vendored dependencies. Keep the reviewed build-tool pin for installation only and capture notices after runtime cleanup.
* Pin the reviewed base, proxy and database references by digest. Digest identity makes the candidate repeatable; outstanding upstream advisory and distribution review remain explicit release gates.
* Add focused export/input regressions, image checks for installer removal and the beta scope/review boundary. No feature expansion, schema migration or production data correction.

## 0.1.0-rc12 — roasting and log review

* Today now records Measured, Roasted and an explicit Cooled step. Bagging/sealing controls stay on the separate packing checklist; Today corrections preserve existing packing timestamps. Existing batches receive no invented cooling timestamps.
* Added direct roast/log review buttons on Today and paginated actual/reference curve overlays beneath Completed Artisan logs on the batch screen. Original files, notes and staff access remain intact; unverifiable curves show a warning.
* Grouped Connections & orders directly below Coffee & artwork in the More menu.
* Added a nullable cooling timestamp, stale-save/undo and packing-preservation regressions, inline curve/reference-integrity and access checks.

## 0.1.0-rc11 — private production-status candidate

* Added a signed, staff-confirmed “still needs production” review for unchanged paid fulfilled orders already assigned to active plans. It preserves existing demand/results and the marketplace's true shipping status.
* Retained confirmations across identical refreshes; invalidated them after source/payment/cancellation/assignment changes without resurrecting old approvals if source values later revert.
* Applied the same hold decision to legacy Shopify, connected stores, CSV refreshes, plan acceptance and daily review. Already fulfilled unimported orders and partial deliveries remain held for separate review.
* Added regression coverage for status-only fulfillment, retained actual weights, duplicate prevention, stale/forged/CSRF/staff guards and confirmation invalidation.

No source-store writes, new production demand, fabricated roasting/stock usage or schema migration are introduced. Shipping labels should normally be created when production is ready; this review handles an early-label exception.

## 0.1.0-rc10 — private Artisan naming candidate

* Named preparation ZIPs with First/Second, City/City+/Full City/Full City+/Vienna/French, the roaster and load number, so suggested extraction folders are readable.
* Displayed the package name before download and retained its full preparation ID/checksums in the manifest. Internal helper/reference/alarms filenames stay fixed.
* Added safe Windows filename handling, real download/manifest/stale-preparation regressions and Windows helper validation from a folder containing spaces.

Existing downloaded ZIPs are unchanged. Stale preparations still require a fresh selection; readable names do not bypass that protection. No production schema or hardware-control change is included.

## 0.1.0-rc9 — private recovery review candidate

* Added a reusable Linux Compose trial with synthetic installation, HTTPS/CSRF, restart and PostgreSQL checks to CI.
* Changed PostgreSQL readiness to TCP so the temporary initialization socket is not mistaken for the final application database server.
* Added full dump/key restoration into separate database/key volumes, record comparisons, account login, encrypted mock credential and original-byte checks, plus wrong-key/corrupt-dump rejection.
* Added a distribution-review worksheet identifying native-library/provenance and corresponding-source questions that package notice collection alone does not close.

No production schema or roast-day workflow change is included. The synthetic restore test does not establish offsite recovery, hardware/alarm behavior or independent security/license clearance.

## 0.1.0-rc8 — private distribution review candidate

* Restricted the generic image build context to required application sources and empty generic catalogs; added actual-image checks with fictional private-state canaries.
* Included Crema's MIT notice and captured installed Python/Debian component versions, available license notices and native-library hashes inside the application image. This is preparation for distribution review, not legal clearance or a complete standardized SBOM.
* Added source/version image labels and offline image verification for source hashes, non-root identity, empty keys/catalogs and immutable application files. CI checks the built image rather than only a successful build.
* Pinned an updated image package installer and included actually installed Python tooling in advisory checks, closing a gap in resolver-only dependency checks.
* Expanded the staged roadmap through 1.0 and subsequent 1.x themes; retained the accepted roast sheet.

No runtime production workflow or database schema change is included. An existing deployment does not update itself; promote only after the applicable release checks.

## 0.1.0-rc7 — private review candidate

* Added optional, audited green-stock checks with one-click Skip that records availability as not checked.
* Added green-origin substitution requests and explicit approval for a plan group's unmeasured loads. Global recipes, ordered coffees and already measured ingredient history are preserved.
* Ranked alternatives by documented roast suitability first, then shared flavor tags; added optional origin metadata, caffeine/quantity guards and stale-request protection.
* Included approved plan ingredients in green deductions and forecasts, and invalidated old production/preparation revisions after approval or cancellation.

## 0.1.0-rc6 — private review candidate

* Added explicit single or multiple marketplace selection, with relevant connection fields and a manual/CSV-only option. Existing connections and their order identities are retained.
* Named prepared Artisan backgrounds using coffee, scheduled green ounces, First/Second and roast code; added title copying for Artisan's separate active roast properties.
* Exposed completed Artisan log uploads from the roast sheet and preparation page, including after an automatic row save; expanded confirmed-upload and native-format regressions.

The existing Artisan background handoff does not set the active roast title. Paste the generated title into Roast Properties; automatic title entry and automatic finished-file uploads are not provided.

## 0.1.0-rc5 — private review candidate

* Fixed prepared Artisan backgrounds to use the native Python-literal file format required by Artisan 3.1, preserving boolean/null values and source curves.
* Rejected incomplete background files before issuing a preparation package.
* Allowed configured machine names in the Windows helper, retaining checksums, idle confirmation and the existing-instance handoff.

## 0.1.0-rc4 — private review candidate

* Added independent store identities, encrypted connection credentials, store-specific product mappings and refresh history.
* Added experimental order adapters for Shopify, WooCommerce, Wix and Squarespace, and a general CSV preview with explicit column mapping.
* Preserved dismissals and deliberate allocations on unchanged refreshes; held changed or unsupported source states for review.
* Added bounded read-only requests, pagination/refresh leases, stale-source protection, duplicate-store guards and expiring raw CSV previews.
* Added fresh-install CI for source privacy, SQLite, PostgreSQL and the container build.
* Updated Pillow to 13.0.0 after advisory review; added a resolved-dependency advisory check.

New marketplace adapters have synthetic coverage; real merchant-account verification remains pending. This candidate is not a public stable release.

## 0.1.0-rc3 — local review candidate

* Introduced Crema branding and a configurable installation name.
* Preserved existing saved names and persistent instance keys.

## Earlier review candidates

* Prepared a source-only MIT edition with empty catalogs, optional fictional setup and Compose-based installation.
* Added persistent generated instance keys and inline HTTPS proxy configuration.
