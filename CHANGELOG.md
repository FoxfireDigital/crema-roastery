# Changelog

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
