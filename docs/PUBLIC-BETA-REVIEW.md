# Exact-candidate public beta review

This is a release procedure, not evidence of independent audit or legal clearance. Public MIT source, prebuilt images/installers and managed hosting are separate stages. Source publication checks cover the exact source, all exposed history/refs, public metadata and automated behavior. Independent assessment, outside pilots and native-image distribution review remain goals for broader distribution and hosting; they are not claims made by this source beta. A source or dependency change invalidates the affected evidence.

| Gate | Evidence required | Decision owner |
| --- | --- | --- |
| Source and archive | Clean candidate, manifest/file agreement, source privacy scan, bounded HEAD-history review, human review of examples/assets | Maintainer |
| Publication surfaces | Explicit list of branch/tag refs, commit identities, Actions histories/logs, draft/release assets and notices to expose | Maintainer and owner |
| Automated behavior | Exact-commit SQLite/PostgreSQL, permission/CSRF/stale/replay, empty installation, Windows Companion and dependency checks | Maintainer |
| Exact service images | Three image identities, inventories, notices, current advisory DB timestamp, raw unfiltered findings and documented dispositions | Maintainer; independent assessment for unresolved risk |
| License/source material | Exact dependency/source correspondence, notices, native/base-layer obligations and authenticated source provenance | Qualified reviewer |
| Deployment and recovery | Exact YAML/images, private backend/TLS/keys, restart and isolated restore, old-version compatibility if upgrading | Maintainer |
| Operational pilot | Another operator's test results and known limitations on a separate installation | Pilot tester and maintainer |
| Security assessment | Written independent findings covering the current candidate and agreed scope; blocking findings resolved | Independent reviewer |
| Publication | Owner approval of the exact repository/ref/image/artifact set, then anonymous public installation and access checks | Owner and maintainer |

## Repeatable source evidence

After committing and packaging the candidate:

```sh
python tools/privacy_check.py
python tools/release_review.py --archive ../crema-CANDIDATE.zip --output ../candidate-source-review.json
```

The second command refuses a dirty checkout, mismatched manifest/archive, unexpected source types, known private markers and non-noreply commit email identities. It checks the bounded ancestry of HEAD, including historical source blobs and messages. Store the resulting private receipt outside the product tree. It does not certify that no private information exists and does not scan other refs or remote Actions/release assets. Explicitly review those before changing visibility. GitHub explains that public visibility exposes Actions histories/logs and permits forks: [repository visibility](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility).

## Advisory and dependency review

Refresh the vulnerability database, record its update timestamp and scan the exact image bytes. Retain every finding and distinguish vendor/backport status, affected runtime paths, fixed versions, unresolved items and the reviewer's decision. Do not silently reuse an older release's clean result, suppress all unfixed findings, or call raw package counts confirmed exploits. Trivy documents database updates and offline reuse: [database configuration](https://trivy.dev/docs/v0.67/guide/configuration/db/).

Python advisory checks cover resolved package versions, not all operating-system/native service dependencies. Run the framework's deployment checks against a synthetic production configuration as well: [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/). Preserve existing application keys and private upgrade migration chains in operational installations.

Crema's MIT license covers its own code. Third-party components retain their licenses. Technical source/notice collection is evidence for qualified review, not a legal clearance. Independently assess the chosen binary-image and source-delivery mechanism before public distribution; see DEPENDENCY-PACKET.md, DISTRIBUTION-REVIEW.md and SECURITY-REVIEW.md.

## Reviewer and tester handoff

Provide the exact commit/archive hash, installation/recovery instructions, synthetic accounts and fixture data, threat model, component inventories, unfiltered advisory results, disposition worksheet and a findings template. Do not include production dumps, real merchant credentials, customer artwork, payroll or instance keys. Collect defect severity, reproducible steps, expected/actual behavior and affected version privately. Do not contact reviewers or testers or create third-party accounts as an automatic release step.

Publish source only after the owner authorizes it and the source/publication-surface checks pass. Do not publish unreviewed binary assets alongside it. Record remaining assessments as limitations. Image publication, paid hosting and deployment to an operational roastery have separate authorization and verification boundaries.
