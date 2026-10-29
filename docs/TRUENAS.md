# TrueNAS deployment

The main format is Docker Compose YAML. Use a dedicated Custom App name and separate persistent storage for each roastery. The initial release candidate image must first be built from this source on the host; no public image registry location is advertised yet. A public release will replace the temporary image reference with a tested published version/digest.

TrueNAS provides an Install via YAML path for Custom Apps; see the [official installation guide](https://apps.truenas.com/managing-apps/installing-custom-apps/). Its production guidance recommends dataset bind mounts rather than relying solely on Docker-managed volumes. Adapt the storage deliberately for a NAS deployment while keeping the portable Compose definition as the main distribution format.

Before installing, review the top of compose.yaml: application image, domain, HTTPS origin and time zone. Inline proxy configuration requires Compose 2.23.1 or later. TrueNAS Custom Apps can add platform-specific validation; verify the definition with your installed version before installing it. The release was exercised with Compose on the NAS, separately from existing apps; it was not installed through the Custom App form.

## Existing reverse proxy

The supplied proxy owns host ports 80 and 443. Many NAS installations already use those ports. In that case remove the proxy service and its configs declaration from your reviewed copy. Connect web:8000 to your existing proxy through a private Docker network, or publish a deliberately chosen backend address/port reachable only by that proxy. Preserve Host and set X-Forwarded-Proto to https at the trusted proxy. Do not expose a plain-HTTP app bypass to the Internet.

No NAS interface or alias is added. The YAML does not claim an unused LAN address or change DNS. Set the actual HTTPS origin used by your existing proxy; it controls login redirects, CSRF checks and Shopify callback URLs.

## Persistent data

The database and instance_keys named volumes are a matched recovery pair. Retain them when recreating/updating the application. TrueNAS-managed volume lifetime can differ from a manual Compose project: do not select data/volume deletion when uninstalling an application you intend to recover.

If substituting dataset bind mounts, explicitly prepare a separate secret directory writable by application UID 10001 and readable by PostgreSQL, and a suitable PostgreSQL data directory. Do not reuse production data to test an install. An initializer with insufficient permissions must stop; it must never change existing dataset ownership recursively.

Create the first administrator through the web container's shell using `python manage.py createsuperuser`. No default password is included. Configure and rehearse encrypted off-host backups using docs/BACKUPS.md before relying on the installation.
