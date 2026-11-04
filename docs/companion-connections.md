# Connected Companion pilot

The Windows Companion prepares approved background curves and paired alarms in an operator-controlled Artisan window. It does not start or operate a roast. Photos and completed .alog uploads remain on the portal's batch controls.

## Server setup

Apply the normal migration chain, including `0009_companion_devices`, then set `PORTAL_COMPANION_ENABLED=1` for the web application. Connections are disabled by default. Use the same setting on all web workers. An upgrade of an older/private installation must add equivalent tables through that installation's existing migration chain; do not replace or fake its migrations with the fresh-install baseline.

Production requires a valid HTTPS portal origin and certificate. Companion accepts only an HTTPS origin without a page path. It does not follow redirects, borrow browser cookies, bypass certificate validation or store the portal password. No callback listener or extra inbound port is needed on the Windows PC.

Sign in as an active staff account. Open **More → Companion computers** to review and revoke that account's connected computers. Disabling the feature immediately blocks both pairing and API access; existing preparation ZIPs retain their offline limitations. Keep the previous server image and a consistent database backup during upgrade. The two added tables contain pairing and device authorization records; they do not alter roast, order, stock or payroll tables.

## First connection

Open **More → Install Companion** on the Artisan computer to download the server's reviewed Windows installer or portable ZIP. The page shows the exact version and SHA-256 checksums. Exit the running application through its tray menu before updating. Installation is a normal Windows action; there is no browser-triggered installation, remote desktop control or silent automatic update.

1. Install/open Companion, choose **Choose roast / connection**, and enter the portal's HTTPS address.
2. Choose **Connect to Crema**. The usual browser opens the portal's connection page.
3. Sign in normally. Enter the code displayed in Companion, review the named computer and approve only the connection you initiated.
4. Return to Companion. It displays the signed-in account, installation name and saved account palette.
5. Select an accepted, active, unroasted load; review the machine and green weight; choose First or Second and a matching approved profile.
6. Confirm the load and choose **Get current preparation**. This creates the same audited preparation snapshot as the portal and downloads it directly into this Windows account's local application data.
7. Check Artisan is idle, previous work saved and the correct USB machine connected. Send the background, inspect it, then send and inspect the paired alarms. The final status is explicitly **Verified by you**.

Companion checks the preparation against the server before both file sends and final verification. A network outage, revoked sign-in, changed plan/profile, removed row, finished roast, deleted or closed plan blocks a connected handoff. As with any network check, a later server change cannot recall a file already delivered to Artisan; coordinate edits during preparation.

**Refresh roasts & theme** retrieves current loads and the user's palette. Different users can keep different palettes. The UI is bundled locally; portal strings are rendered as text, and only fixed hexadecimal palette tokens are applied.

## Access and lifetime

This is a first-party device pairing protocol informed by RFC 8628, not a general-purpose OAuth authorization server. A random one-use code expires in ten minutes. Browser approval is session-authenticated, staff-only, CSRF-protected and rate-limited. Native polling is rate-limited and slows down when requested too frequently. There is no approval through a GET link.

The authorized capability is restricted to the dedicated Companion endpoints: account palette/branding, active load summaries, compatible profile choices, creating preparation snapshots and validating those snapshots. It does not authenticate general portal pages and cannot edit orders, measurements, inventory, hours or evidence. Customer/order names and connection credentials are not returned.

Access tokens expire after fifteen minutes. Refresh credentials rotate with each refresh, and a device has an absolute thirty-day lifetime. Revocation, account deactivation, removal of staff rights or a password change invalidates access. The database stores keyed hashes only. Windows stores the credentials with current-user DPAPI protection, bound to the chosen portal origin. The embedded browser receives no credentials and cannot issue network requests.

Use **Disconnect this computer** for normal sign-out. If the portal is unavailable, **Remove saved sign-in from this PC** removes the local credential; also revoke that computer from the portal when reachable. Uninstall preserves local preparation files/settings, so disconnect before handing a PC to someone else.

## Runtime and fallback

The new interface uses Microsoft WebView2. Its Runtime is a separate Microsoft component; the installer does not silently install it or accept its terms. If unavailable, the application offers Microsoft's official download page and the classic offline preparation window. The .NET runtime is included with the app. SDK/runtime notices are bundled; Microsoft's components retain their own licenses.

**Open preparation ZIP** remains an explicitly offline fallback. It validates archive contents, hashes, targets and age, extracts only data and never executes bundled scripts. An offline ZIP cannot detect later portal edits. Compare it with the live plan before use. Do not use offline fallback to continue a connected preparation that the server rejected.

## Validation and rollout

Run `python tools/companion_checks.py` for the fictional in-memory server suite and the normal `tools/test_release.py` regression. The Windows executable's `--self-test` checks use fictional archives, protected temporary credentials, a fake HTTP transport and a random test-only pipe. They do not access a real account or Artisan endpoint. Native UI inspection, a valid-HTTPS server connection and the roasting-PC operator trial are separate release gates. Build with the locked Microsoft package versions and retain the supplied licenses.

Deploy first to an isolated fictional demo with a verified backup, inspect connection/revocation and theme matching, then rehearse the private installation upgrade before promotion. Keep the previous Companion and offline workflow available throughout the pilot.

## Compact view and tray

The main preparation window has one roast card. The chooser holds accepted loads and connection settings. Quick view gives a compact summary and preparation details. X and Hide to tray keep the application running; the coffee tray menu offers Quick view, Open Companion and Exit Companion. Reopening the desktop shortcut restores that same process. Use Exit Companion before updating or uninstalling. No hide, restore or view action loads anything into Artisan.

## Publishing a reviewed desktop package on your portal

Desktop binaries are built and reviewed separately from the server source. They are not committed into this repository. Stage immutable files and `release.json` in an administrator-controlled directory, readable by the web container. Mount it read-only at `/var/lib/crema-companion` using the optional `compose.companion.yaml` override. An alternative absolute location can be set through `PORTAL_COMPANION_DOWNLOAD_ROOT`. Never mount a folder containing credentials, customer records or unrelated downloads. Keep older releases in separate directories for recovery, and switch the mount only after verifying every artifact against its build receipt.

The manifest has format `crema-companion-release-v1`, a `version` string, a truthful `signed` boolean and an `artifacts` object. Required keys are `installer` and `portable`; `source` is optional. Each entry contains `filename`, `bytes` and lowercase hexadecimal `sha256`. Filenames must begin `CremaCompanion-` and end in `.exe` for the installer or `.zip` for the archives. Example metadata (replace the zero digest and size with the reviewed file's actual values):

```json
{"format":"crema-companion-release-v1","version":"0.2.0-preview.2","signed":false,"artifacts":{"installer":{"filename":"CremaCompanion-Setup-0.2.0-preview2-win-x64.exe","bytes":1,"sha256":"0000000000000000000000000000000000000000000000000000000000000000"},"portable":{"filename":"CremaCompanion-Pilot-0.2.0-preview2-win-x64.zip","bytes":1,"sha256":"0000000000000000000000000000000000000000000000000000000000000000"}}}
```

Downloads require a staff session and enabled Companion access. The server checks file size and the complete SHA-256 digest on the same open file it streams; missing, corrupt, oversized, symlinked or unlisted files are refused. Packages are attachments with private/no-store caching. A missing release produces a helpful installation page without affecting existing pairing or offline preparation. The checksum establishes consistency with the administrator's release receipt; it is not a code-signing certificate. Do not describe an unsigned pilot as signed or verified by Microsoft.
