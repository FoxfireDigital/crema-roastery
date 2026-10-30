# Distribution review: dependency and source obligations

This is a review worksheet, not a legal clearance. Crema's application code uses MIT; that does not relicense dependencies, container operating-system packages, native libraries or customer assets. Keep the exact image, captured component inventory, notices and source archive together when reviewing a candidate.

## What the captured inventory establishes

The application image records installed Python/Debian package versions and available notice texts, plus hashes of native libraries listed in Python distribution metadata. It does not infer the license/version/source of every bundled library from its filename or establish that all applicable source-distribution requirements have been met.

The reviewed rc8 baseline contained 16 Python distributions, 105 Debian packages and 150 captured notice files. Its Python wheel inventory listed 47 native files across five distributions: cffi (1), charset-normalizer (2), cryptography (1), Pillow (26) and psycopg-binary (17). These counts describe that baseline image, not every future build or architecture.

## Prioritized worksheet

| Component / scope | Evidence to retain | Work still required before distribution clearance |
|---|---|---|
| Crema own code | MIT notice, source identity, reviewed history/archive | Confirm publication authority and provenance of included contributions. Customer data/artwork/profiles remain excluded. |
| psycopg / psycopg-binary | Exact 3.3.6 package metadata declares LGPL-3.0-only; captured package notices and native hashes | Review exact license texts and applicable source/replacement/relinking obligations for the way the library is distributed. Do not apply psycopg2-specific exceptions by assumption. Identify/source bundled libpq, OpenSSL, Kerberos, LDAP and other native libraries from build provenance rather than guessed filenames. |
| Pillow | Exact 13.0.0 package declaration, its full notice text and native hashes | Review bundled image/font/compression libraries and their notices/source obligations. MIT-CMU on the top-level package is not a blanket license for every binary in the wheel. |
| cryptography and cffi | Installed declarations, notices and native file hashes | Review bundled crypto/native dependencies and any separately applicable terms; establish versions from reliable build/source information. |
| Other Python packages | Exact metadata/classifiers and notice files | Where an SPDX expression is absent, read the actual notice. A BSD classifier or a notice file's existence is not a complete legal determination. Preserve required attribution. |
| Debian base packages | Binary/source package names and versions, package copyright files | Review source-delivery obligations and provenance for the actual distributed base image; separately assess relevant vulnerabilities using Debian version/backport information. |
| Python runtime, proxy and PostgreSQL images | Exact upstream image identities/digests and their notices/source arrangements | These extend beyond the application Python package inventory. Record the architecture and actual distribution method. |

Psycopg's upstream documentation confirms the binary installation bundles client libraries, while a local build links system libraries. The selected package's metadata explicitly declares LGPL-3.0-only. These are different packaging choices to review, not a reason to change database drivers without compatibility/performance testing. [Psycopg installation](https://www.psycopg.org/psycopg3/docs/basic/install.html), [3.3.6 metadata](https://pypi.org/project/psycopg/3.3.6/).

## Evidence that closes an item

For each distributed component, retain an exact version/hash, license and notice texts, provenance, corresponding source/build material or other compliant distribution mechanism where required, and a recorded reviewer disposition. Confirm replacement/relinking conditions where applicable. A link to a moving upstream branch is weaker than identifying the exact material used. Do not claim that a vendor's package metadata alone discharges the distributor's obligations.

Keep unknowns visible. If provenance or obligations cannot be established, keep the image private while resolving that component or evaluate a simpler packaging choice with full regression testing. No component switch, public image push or assertion that all dependencies are MIT is authorized by this worksheet.

An advisory result must distinguish application packages, operating-system packages, native vendored libraries and the other service images. Debian-specific status/backports do not automatically classify non-Debian libraries embedded in wheels. [Debian Security Team guidance](https://security-team.debian.org/security_tracker.html).

This worksheet and the captured inventory support a qualified independent review. They do not certify licensing, security, confidentiality or legal compliance.
