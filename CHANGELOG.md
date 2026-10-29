# Changelog

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
