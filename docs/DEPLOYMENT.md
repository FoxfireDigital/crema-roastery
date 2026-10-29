# Deployment notes

The supplied Caddy proxy terminates TLS, forwards to web:8000 and supplies the trusted HTTPS header. The application trusts X-Forwarded-Proto, so keep web:8000 inaccessible to untrusted clients. PostgreSQL has no host port. Do not place the production service behind a public plain-HTTP bypass.

Edit the image anchor, domain anchor, PORTAL_BASE_URL and PORTAL_TIME_ZONE at the top of compose.yaml. The domain anchor supplies PORTAL_DOMAIN to the proxy; the base URL is the exact HTTPS origin, and the time zone is an IANA zone. If using an existing proxy, remove the proxy service and unused configs from a reviewed copy of the YAML and connect it to web through a private Docker network. Forward the original Host and set X-Forwarded-Proto yourself. Do not pass arbitrary client forwarding headers. Test login, CSRF-protected saves, redirects, uploads and health checks before use.

The initialize service creates unique keys inside the persistent instance_keys volume, then PostgreSQL and the app start in dependency order. No Python runtime, .env or secret-generation script is required on the host. Keep the instance_keys volume together with the database when backing up or moving an installation. These are Docker-managed secret files, not an encrypted-at-rest secret vault; only explicitly granted containers should mount them. The initializer refuses partial keys or a nonempty database without its original keys.

The candidate's application image uses pull_policy: never and is built locally using compose.build.yaml. A published image release must set an approved registry reference/digest and permit pulling it. No public registry repository has been chosen or published yet.

The embedded proxy configuration uses Compose configs.content, which requires 2.23.1+. See the [Docker Compose specification](https://docs.docker.com/compose/intro/compose-application-model/) and [inline config reference](https://docs.docker.com/reference/compose-file/configs/). YAML and YML are supported file extensions for the same deployment specification.

PORTAL_LOCAL_DEVELOPMENT=1 explicitly permits local HTTP and SQLite for developer tests only. It is absent from production Compose. Production settings reject short secret keys, plain-HTTP origins and a missing PostgreSQL host.

Set safe machine capacities before accepting a plan. System weights are ounces, displayed in tenths; receipts accept pounds as well. Standard custom-roast eligibility is 80 finished ounces for a single-origin order line. Retail layouts support 16 oz, 5 lb and fracs; wholesale supports 12 oz, 5 lb and fracs. Artisan targets are Fahrenheit. These defaults are documented limits of this release.

Use only your own brand and artwork. The empty install is intentional. Review all imported CSV mappings; a storefront title is not authority to change a roast standard.

Suggested hosting service: one Compose project, database, secret set and backup destination per customer; separate domain; encrypted offsite copy; tested restoration; scheduled updates; explicit operator access. Shared-tenancy isolation, subscription billing, email password reset, MFA and a public self-registration flow are outside this release.
