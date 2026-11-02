# Release artifacts and registry installation rehearsal

The candidate remains private. A public registry hostname/image is not advertised until its exact artifacts and visibility have been approved. The primary installation format is Compose YAML. Local source builds use all three images:

```sh
export CREMA_VERSION=0.1.0-rc20
export CREMA_REVISION=$(git rev-parse HEAD)
docker compose -f compose.yaml -f compose.build.yaml build --pull web postgres proxy
```

## Checked offline image bundle

A release-artifact directory contains release-manifest.json and one compressed Docker image archive for each of the application, proxy and database. The manifest records source revision, image/config identities, complete artifact hashes and sizes, registry manifest digests, and the platform. Only the platform actually tested is covered; the initial rehearsal is Linux amd64.

From the corresponding reviewed source checkout, verify and load a supplied artifact directory:

```sh
python tools/load_release.py /path/to/release-artifacts --verify-only
python tools/load_release.py /path/to/release-artifacts
```

The loader verifies all artifacts before loading any, rejects paths outside the directory, extra archive members/tags and duplicate names, and refuses to overwrite an existing release tag that points at different content. It checks loaded image identities and source/version labels. It starts no services and touches no instance keys or database volumes. Hashes establish consistency with the manifest, not publisher authentication; obtain the manifest/checksums through the approved release channel. Publisher signing is a separate release decision.

After loading, edit the domain, matching HTTPS origin and timezone in compose.yaml, then follow the owner-account and startup instructions in README. The candidate YAML's local-image pull policy is deliberate. Do not replace the keys of an existing installation or attach an operational database to the generic fresh-install migration baseline.

## Digest-pinned registry YAML

Once approved images actually exist in a registry, supply their complete immutable references in a JSON object with application, database and proxy keys. Render an installation YAML:

```sh
python tools/render_registry_yaml.py approved-image-map.json compose.install.yaml
```

This changes only image references and their pull policy; it does not push/publish images, contact a registry or guess unavailable public image URLs. Edit domain/origin/timezone before starting it. Do not distribute a local rehearsal's temporary loopback references as a public installer.

## What the registry rehearsal verifies

tools/test_registry_install.py uses a pinned official registry image on a random loopback-only port and its own labelled temporary storage. It verifies the generic source images first, uses an empty Docker client configuration for pushes/pulls, and separately downloads every image blob with an anonymous HTTP client into a fresh directory. It verifies registry/config digests, compressed blobs and uncompressed layer identities, constructs checked offline archives, and exercises their loader. Tampered checksums and escaping paths must fail before loading.

It also pulls by immutable digest without saved registry credentials, renders that exact registry YAML, and runs the complete isolated Compose, HTTPS/login/CSRF, generated-key, PostgreSQL regression, restart and database/key restoration trial. The test variant uses a unique project, local CA, loopback HTTPS, resource limits and separate volumes. Shared engine layers are not erased; the fresh client downloads provide the complete-transport evidence. Only test registry/volumes/references are removed. The actual generic images, source artifacts and production installations are preserved.

The rehearsal does not establish Internet registry availability, real public DNS/CA issuance, an outside-roastery pilot, older private migration compatibility, independent security review or license clearance. Those gates remain explicit. A same-version fictional restore is not an offsite recovery test.
