# Pre-beta independent security review

This document scopes a review. It is not evidence that an independent review has occurred. Automated regressions, dependency queries and maintainer inspection are supporting evidence only. Keep findings and any operational evidence private until disclosure is appropriate.

## Review target and boundaries

Record the exact commit, image digest/ID, deployed configuration, architecture, dependency inventory and test date. Use a separate disposable installation with fictional accounts, orders, files and store credentials. Never probe a customer deployment, third-party store, real roaster or backup service without separate authorization for that target and activity.

Supported deployment boundary: one roastery per installation/database behind a trusted HTTPS reverse proxy, private backend ports, distinct instance keys, non-root application container and persistent database/keys. Shared-database tenancy is not implemented. Staff have broad operational access; payroll-rate authority is separately granted. Granular production roles and MFA are roadmap items, not current guarantees.

Reviewers should understand these sensitive assets:

* Account sessions, passwords, administrator privileges and payroll/rate records.
* Customer identities/orders, recipes, suppliers, costs, production history and uploaded artwork/profiles/photos.
* Encrypted store credentials, OAuth/session state, webhooks and outbound integration requests.
* Database backups, original instance keys, confidential exports and recovery access.
* Inventory movement correctness and operator-facing roast instructions. File preparation is not authorization to operate hardware.

## Required review areas

| Area | Review questions / test evidence |
|---|---|
| Installation and proxy | Are HTTPS and secure cookies enforced in production? Can untrusted forwarding headers or direct backend access bypass the intended boundary? Are domain/Host/CSRF origins configured deliberately? Are app/database ports private? |
| Authentication | Password validation, login/admin throttling across workers, session expiry/rotation/logout, recovery process and brute-force behavior. Test proxy-shared clients and concurrent attempts. Document the current absence of MFA. |
| Authorization | Exercise anonymous, ordinary authenticated, staff, payroll-authorized and superuser requests directly against reads, writes and exports. Include guessed identifiers and forbidden object access. Hidden navigation is not access control. |
| Request integrity | CSRF failures, stale forms, replayed POSTs, parallel users/tabs and partial failures. Verify no duplicate stock deductions, payment records, imports or production results. |
| Templates and browser boundaries | User-controlled text/filenames in HTML, scripts, attributes, CSV/PDF/download headers and error pages. Review CSP nonces, caching, framing, file content types and cross-origin behavior. |
| Uploaded/exported files | Bounded image/CSV/Artisan parsing, decompression and image dimensions, malformed formats, path handling, filenames, generated PDFs and original-file access. Use fictional malformed files; do not distribute private originals as fixtures. |
| Store connections | OAuth state/redirect handling, token encryption/key ownership, scope checks, webhook authentication, retry/deduplication and cancellation/change holds. Check outbound URL validation, redirects, DNS/IP boundary handling and timeouts. Avoid live third-party requests during attack tests. |
| Background work | Leases/locks, bounded pagination/retries, authentication failures, crash/restart recovery, retained dismissal/order identities and credential-free errors/logs. |
| Inventory and production | Correctness under replay, timeout and concurrent writes; measured ingredient snapshots, reversals, substitutions, merged/removed batches and reserved versus actually used bulk. Safety limits remain enforced even when availability checks are skipped. |
| Payroll and exports | Separate rate authority, actor/time audit, edit/delete/payment correction and private export boundaries. Do not describe the feature as statutory payroll compliance. |
| Backup and recovery | Who can export/download backups? Are database and matching keys/assets recoverable? Review encrypted transport/storage, retention and restoration against a disposable target. Verify later writes are not silently discarded by a recovery procedure. |
| Image and dependency supply chain | Build context, source/file identities, known advisories, vendored libraries, component notices, base/proxy/database images, runtime privileges and tamper/release controls. Labels alone are not provenance verification. |

## Evidence packet

Provide a clean source checkout, exact image identity, resolved component inventory, sanitized deployment definition, supported-version matrix, CI run and affected test output. Existing useful checks include `tools/test_release.py`, `tools/privacy_check.py`, `tools/audit_dependencies.py`, `tools/test_initializer.py` and `tools/verify_image.py`.

For each finding record: affected version/route/component, necessary permissions, expected/observed result, confidential minimal reproduction, potential impact, severity rationale, proposed fix, regression and retest evidence. Label untested assumptions. Do not put credentials, private customer fixtures or exploit-ready operational details in public issue text.

The review must also inspect gaps in automated coverage. Passing the listed tools does not close this review by itself. A reviewer should be independent of the implementation being assessed; this packet does not appoint or contact one.

## Exit and follow-up

* Identify and resolve release-blocking authorization, data-loss, credential-exposure and production-correctness findings; obtain independent retest where appropriate.
* Record remaining limitations with impact, owner and planned treatment. Do not quietly label an untested area passed.
* Recheck the exact release artifact and documented deployment boundary after material fixes.
* Publish a truthful security/compatibility statement and private reporting route before a public beta. Do not claim certification, compliance, penetration testing or 24/7 response without evidence and an operating arrangement.
* Paid hosting requires an additional service review: cross-customer isolation, support access, per-customer restore/export/deletion, quotas, incident response and service/privacy terms. A self-hosted review does not establish those controls.
