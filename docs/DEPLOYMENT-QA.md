# Disposable installation and recovery trial

`tools/test_compose.py` runs on a Linux Docker host with Docker Compose, curl and Python 3.11+. It accepts an already built **generic** candidate image and a matching reviewed source checkout. It does not deploy a customer installation.

```sh
export CREMA_VERSION=0.1.0-rc21
export CREMA_REVISION=$(git rev-parse HEAD)
docker compose -f compose.yaml -f compose.build.yaml build --pull web postgres proxy
python tools/test_compose.py --image "crema:$CREMA_VERSION" \
  --revision "$CREMA_REVISION" --output /tmp/crema-deployment-review
```

The trial renders the canonical YAML as a generated configuration. It uses a unique project, volumes and temporary image alias; internal backend networking; limited memory/CPU; a separate proxy network; and only a dynamic loopback HTTPS port. It explicitly trusts the temporary public TLS authority for curl without disabling certificate checks or changing the host trust store. It never changes DNS, production listeners or existing application volumes. It removes its generated resources and image alias; it retains the supplied candidate image.

The normal trial checks empty installation, persistent generated keys, non-root image/source integrity, full PostgreSQL regressions in a separate QA database, HTTPS login/CSRF saves and restart persistence. It then stops only the fictional worker and rehearses recovery:

PostgreSQL readiness uses TCP rather than the temporary socket-only server used during initial setup. This prevents dependent services or restore commands starting against a server that is about to stop. [Official image entrypoint](https://github.com/docker-library/postgres/blob/master/docker-entrypoint.sh).

1. Seed an inactive fictional connection with an encrypted mock credential and a retained-original byte fixture. No real marketplace requests occur.
2. Capture a consistent custom-format PostgreSQL dump and matching instance-key archive. Check the dump list and reject an intentionally invalid dump.
3. Restore keys into a **new key volume**, start a separate PostgreSQL service with a **new database volume**, and restore with `--exit-on-error --no-owner`.
4. Add a later fictional write to the source database, start the restored app, and compare canonical serialized records against the pre-dump snapshot.
5. Verify the restored account can sign in, the matching key decrypts the mock credential, a deliberately wrong key is rejected, retained original bytes are intact and later source writes did not appear in the restore.
6. Remove only the generated QA services/volumes. Temporary dump/key material stays within the restricted disposable folder and is removed during cleanup; no secret content is written to the verification report.

The report is saved as `deployment-verification.json`; component metadata is saved separately as `components.json`. These are evidence of a synthetic same-version local restore, not an offsite download/decryption test, a physical Artisan/alarm test, proof of real customer stock or an independent security assessment. The original byte fixture checks database retention, not whether a real Artisan file is usable.

Backup completeness also requires the matching application image/source, configuration, deployment-specific keys/assets and any additional external storage used by a particular installation. Follow [BACKUPS.md](BACKUPS.md) for real backup handling. Test restores from the actual chosen encrypted offsite destination separately. A ZIP of business-record CSVs is not a full backup.

The QA script owns its generated `crematrial_` project. Do not adapt its cleanup commands to a valuable deployment or pass customer images/data to it. CI runs this trial against each review candidate; that does not authorize production recovery or public publication.
