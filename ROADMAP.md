# Roadmap

The first beta prioritizes a reliable received-order → planning → roasting → packing workflow, repeatable installation, protected business records and tested recovery. Release readiness is determined by verification, not by completing every feature below.

## Current candidate

* Configurable roastery catalog, machine capacities and branding.
* Stock-first roast planning and recorded-versus-reserved finished coverage.
* Shopify's existing read-only workflow; new experimental store-specific adapters for Shopify, WooCommerce, Wix and Squarespace; general mapped CSV preview/import.
* Manual bulk counts, measured green deductions, recipes, supplier receipts and tastings.
* Packing/grind instructions, user-supplied labels, profiles and optional photos.
* Time records, payment tracking, supplies, maintenance and forecasts.

## Release gates

Privacy/secret review of the full publication set; fresh PostgreSQL installation; synthetic workflow regressions; dependency/security review; tested upgrades and restore; operational pilot; accurate documentation and known limitations. Experimental marketplace adapters need real authorized account validation before being called fully verified.

## Subsequent work

* Packaged finished inventory and deeper lot-to-order traceability.
* Full per-bag/order costing with explicit unknown costs.
* Scan-to-check packing.
* Wholesale customer reorder workflow.
* Deadline-aware production planning.
* Granular roles and multifactor authentication.
* Additional merchant-account tests and platform-specific import refinements.

Features are not promises of a release date. Changes must preserve actual production history, avoid duplicate demand and distinguish stock reservations from physical usage.
