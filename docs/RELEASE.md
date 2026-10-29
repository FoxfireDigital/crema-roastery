# Release candidate and launch checklist

0.1.0-rc4 is being prepared privately for review. A public repository or download has not been published. The selected name is Crema. Domain, registry and name availability have not been cleared for public launch.

The primary installation artifact is compose.yaml. It generates its own persistent instance keys and embeds the proxy config. The application image is currently built locally using compose.build.yaml. A public YAML-only release needs an approved published image reference/digest and pull policy; no registry has been published yet. A review install and a rerun/restart were tested against an isolated PostgreSQL stack, including nonempty-database and partial-key recovery guards.

Earlier rc1 review installations used host secret files. Preserve those originals; adopting rc2 requires deliberately migrating the same keys into the instance_keys volume. Never allow new keys to replace an existing database’s originals. The live private portal keeps its existing installation and migration history.

Release gates: clean fresh-history repository; MIT license; no private seed/history/assets; generated schema-only initial migration; empty-install smoke tests; optional fictional demo; PostgreSQL container tests; privacy scan of source and final ZIP; TLS/proxy check; dependency advisory review; tested backup/recovery; independent security review and a small pilot with another roastery.

Do not migrate an existing operational database by pointing it at this new migration baseline. Upgrades from older private editions must preserve their migration history, apply a reviewed schema/configuration bridge, and be rehearsed against a restored copy first. Product features belong in Crema; installation data and compatibility migrations remain private deployment material.

The multistore changes have local synthetic coverage and an isolated PostgreSQL/Compose check. Before the next candidate, repeat isolated PostgreSQL/container checks, dependency review, source and archive scans, and browser checks. New platform adapters must remain labelled experimental until tested with authorized merchant accounts. A passing fixture is not proof of live API entitlement or end-to-end account compatibility.

Public launch is staged: clean private repository; repeatable CI and installation; restored-copy upgrade rehearsal; operational pilot; then a tagged public beta with a versioned image/digest and documented limitations. An expanding feature wishlist must not postpone release indefinitely. Packaged inventory, further lot traceability, scan checks, customer self-service and granular roles/MFA are separate roadmap work unless verified in the candidate.

For a paid service, offer setup, imported catalog/artwork configuration, isolated hosting, backups, updates and support. Do not promise shared tenancy, payroll compliance, automatic roaster operation or Shopify App Store approval. Keep customer data and commercial operating credentials out of the public source tree.
