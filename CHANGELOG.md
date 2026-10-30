# Changelog

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
