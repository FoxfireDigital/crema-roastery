# Shared fictional-data demonstrations

Use an independent deployment with its own database, volume, secret keys and
fictional records. Never restore a customer database into a shared demonstration.
Set `PORTAL_DEMO_MODE=1` on both the web and worker services. It defaults off;
ordinary installations keep their account and connection administration.

Demo mode blocks live-store connections, recovery/backup exports, installation
settings and account administration at the application boundary, including direct
requests by a superuser. Django administration is limited to coffee, packaging-label
variants and roasters, still subject to each account's permissions. Menus hide
unavailable settings. Account creation and password rotation happen out of band.

Create a non-staff user for production checks, and a staff **non-superuser** for
planning, catalog and other staff workflows. Give that administrator only the
needed coffee, label-variant and roaster model permissions, never user, group,
connection or installation permissions. Generate unique strong passwords. Do not
embed passwords in source, images, public pages or production defaults.

Keep web, worker and database on an internal network with no published ports or
outbound network. Only the gateway joins the intended public proxy network. Enforce
the exact hostname, HTTPS, request-size limits, no-index headers and blocked private
routes there too. Do not mount host directories, Docker sockets or other apps'
files into the demo. Application demo mode is an extra boundary, not a substitute
for this isolation. Test both roles, CSRF, direct blocked requests and the network
configuration before sharing access.

Visitors share the fictional instance: one visitor's edits are visible to others.
Use no real customer, employee, payment or merchant information. Keep an independent
snapshot before upgrades, and make any reset policy explicit rather than silently
erasing a demonstration in progress.
