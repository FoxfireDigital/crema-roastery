# Backups and recovery

No cloud account, destination or automatic schedule is preconfigured. The records ZIP is useful for inspection but is not a complete backup: it omits accounts/password hashes, credentials, image originals and other binary documentation.

Use PostgreSQL’s consistent custom-format dump, plus the matching application source/version, the deployed Compose definition and the instance_keys volume. Application images, uploaded labels, photos and profiles are stored in PostgreSQL; do not copy its live data directory as a substitute for pg_dump. The Django secret is also the credential encryption root. Losing or regenerating it makes saved Shopify credentials unreadable.

On a trusted Linux Docker host, restrict a temporary backup folder to its operator and run:

```sh
umask 077
mkdir -p backups/staging
docker compose exec -T postgres pg_dump -U coffee -d coffee -Fc > backups/staging/database.dump
docker compose exec -T web tar -C /run/roastery-secrets -cf - django postgres > backups/staging/instance-keys.tar
cp -R app backups/staging/app
cp compose.yaml backups/staging/
```

Check the dump command succeeded before continuing. Encrypt this folder with a maintained backup tool such as restic or age using a key retained separately. Upload only encrypted output to a private destination outside the host; Google Drive is suitable with an operator-controlled encrypted transport such as rclone crypt. Do not send plaintext staging data or recovery keys to a shared/public destination. Remove temporary plaintext only after verification. Set your own retention and schedule; never report an upload as a restore test.

## Restore rehearsal

1. Create an isolated Docker project with a separate database, instance-keys volume and domain/loopback proxy. Disable outbound Shopify work on that test instance until reviewed. Never point the test at production PostgreSQL.
2. Decrypt a downloaded off-host copy. Verify its file checksums from your backup tool.
3. Use pg_restore --list to inspect the dump, then restore to the isolated empty database with pg_restore --exit-on-error --no-owner. Restore matching source and instance secrets. Change only the local domain/proxy settings required for the rehearsal.
4. Start the restored app. Check account access, order counts, roast history, stock, hours, supplier/purchase records and sample original images/files. Export records and compare known totals.
5. Record the backup identifier, download, decrypt and restore result. Preserve current production data before any actual recovery cutover, including newer work absent from that backup.

The supplied app intentionally does not claim automatic backup success when these operator tasks have not been performed.

The Linux-only [disposable deployment/recovery trial](DEPLOYMENT-QA.md) exercises a consistent dump and matching keys restored into separate volumes with fictional data. It checks account access, encrypted mock credentials, original bytes, wrong-key rejection and exclusion of later source writes. It does not replace testing a download/decryption/restore from your actual offsite backup destination.
