# Generic application image review

The distribution candidate includes a restricted build context, source/version labels, Crema's MIT notice and a captured component inventory. These checks prepare an image for review. They do not authorize publication or certify legal/security compliance.

## Build and inspect

Run from a clean, reviewed source checkout on a Docker host:

```sh
export CREMA_VERSION=0.1.0-rc13
export CREMA_REVISION=$(git rev-parse HEAD)
docker compose -f compose.yaml -f compose.build.yaml build --pull web
python tools/verify_image.py --image "crema:$CREMA_VERSION" \
  --version "$CREMA_VERSION" --revision "$CREMA_REVISION" \
  --output ./image-review --test-context
```

The inspection does not run the application entrypoint or migrations, contact a database, mount instance keys or start a roaster. It runs Python in a network-disabled, read-only container with capabilities dropped. It checks:

* Version/revision labels, UID/GID 10001, required source hashes and no unexpected application files.
* Empty generic artwork/profile catalogs and an empty instance-key directory.
* No application source files writable by the runtime user.
* Integrity of captured notices and nonempty Python/Debian package inventories.
* With `--test-context`, an actual disposable second build containing eight fictional unwanted files. They must all be absent while required source files remain intact. Only that test image is removed afterward.

The Docker context starts excluded and allows only specified source files/types. Docker applies the last matching ignore rule, including exception rules; the actual-build test complements that configuration review. It cannot prove arbitrary admitted source text contains no secrets. Source/history/archive privacy checks still apply. [Docker build context documentation](https://docs.docker.com/build/building/context/).

Local builds without supplied identity arguments are labelled `development` / `unknown`; do not present those as a verified release revision. Labels identify a claim; byte comparison and CI establish the accompanying evidence. An image ID is not a registry manifest digest.

## Component declarations and notices

Inside the built image:

* `/srv/LICENSE`: Crema's own MIT notice.
* `/usr/share/crema/components.json`: installed Python and Debian package versions, Python license declarations/classifiers, source-package metadata, available notice hashes and native-library hashes.
* `/usr/share/crema/notices/`: available Python wheel license/notice files, Debian package copyright files and Crema's MIT notice.

The inspection writes `image-verification.json` and a copy of `components.json` into the chosen output directory. Keep generated review output outside source publication unless deliberately reviewed. These files contain component declarations, not application records or secrets. A later CI artifact-retention policy can retain this evidence; the current job's temporary output is not a durable downloadable artifact.

CI also submits the installed Python package versions from `components.json` to the advisory check, including image-provided Python tooling. This supplements the resolver-report check. Debian/native-library advisories and complete license obligations still require separate review; a Python-only advisory result is not an image-wide security assessment.

The build explicitly uses pinned pip26.2.2 to install requirements, then removes the installer and the bootstrap wheel from the runtime filesystem. This removes unnecessary installer-vendored dependencies; it does not clear operating-system or other native-library advisories. The image verifier rejects a remaining pip module or bootstrap wheel. Build/base/service references are pinned by digest for this review; refresh them through a deliberate tested candidate update. A successful advisory lookup means no known findings were returned for those versions at that time, not a guarantee against vulnerabilities.

This is a custom component inventory, not a claim of CycloneDX/SPDX conformance, complete source delivery or license compatibility. Review missing notice files, transitive and vendored native libraries, exact versions, distribution obligations and corresponding source requirements. Python metadata alone does not settle those questions. The proxy and PostgreSQL images need their own review. Do not describe every image component as MIT.

## Distribution gates still required

1. Review exact source/image publication rights and dependency/source obligations, including any missing notice evidence and bundled native libraries.
2. Complete independent security review and resolve release-blocking findings.
3. Verify the actual generic release image against a clean checkout and the same release checks; retain its source archive and evidence.
4. Choose and approve registry visibility; push only the generic image, record its registry digest and verify the intended anonymous pull/deployment path. No registry image is published by this tooling.
5. Test domain/TLS setup, persistent keys, normal workflow, upgrade and backup/recovery for the supported release.

Private installations can include non-redistributable profiles, artwork and old migration histories. Do not use them as the generic build input. Do not copy this generic allowlist blindly into a private installation build: preserve private assets through a separately reviewed private context and prove their hashes in an upgrade rehearsal. Those private images must remain private.
