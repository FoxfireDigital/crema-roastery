# Crema Companion — portable Windows pilot

This is an optional pilot for Windows x64 and Artisan 3.1.0. Operator validation on the roasting computer is required before relying on it. The existing portal ZIP/CMD workflow remains the fallback. Crema server installation and production data are unchanged.

## Roast-day use

1. Keep the pilot folder, including the runtime notices. Open CremaCompanion.exe as your normal Windows user. The self-contained build includes its runtime; there is no service, scheduled task, sign-in, port, startup registration or administrator requirement.
2. In Crema, prepare the accepted, unroasted load using the correct machine, First/Second schedule and targets. Download a fresh preparation ZIP. Changed plans or profiles require a new preparation.
3. In the companion, choose **Open preparation ZIP**, drag that ZIP onto its window, or paste its local path and press Enter. Open always offers a new file selection, even after a previous preparation was loaded. Manual extraction is unnecessary. The program reads data files only; included CMD/PowerShell files are never extracted or executed.
4. Review the coffee, green ounces, machine, session, title and Fahrenheit targets against the current portal. Check that the correct USB roaster is connected, previous work saved, and Artisan idle with monitoring OFF. Check readiness and choose **Load background**.
5. If Artisan is closed, choose its installed artisan.exe when asked. The companion opens it without control arguments. Finish startup dialogs, confirm monitoring OFF, check readiness again and load the background. A running but unreachable Artisan instance is an error, not permission to launch a second copy.
6. Verify the expected background curve is visible and monitoring remains OFF. Check the inline confirmation, then choose **Load paired alarms**. Verify Charge / Drop / Off targets under **Config → Alarms**; enable Load from background for embedded alarms. No successful send is described as a verified load.
7. Choose **Copy roast title**, then paste into **Roast → Properties → Title**. Copying replaces the current clipboard text. The active foreground title is not set automatically.
8. Operate the roast manually. Record finished weight/cooling in Crema and upload the saved foreground .alog using its existing review workflow. This pilot does not watch folders or upload files.

First means cold or this particular machine idle for at least ten minutes; Second is continuing warm work. The companion cannot measure machine heat, identify the attached USB roaster, detect an active roast, or verify that Artisan accepted a load. Off is Artisan monitoring OFF, not a guaranteed physical heater shutdown.

## Boundaries and recovery

- This build has no portal connection. Included checksums detect inconsistent files, not a trusted publisher. Only open fresh packages from your own known Crema portal. The readiness check includes confirmation against the live plan. Packages older than 24 hours or more than five minutes in the future are rejected; this is not a substitute for live freshness checks.
- A malformed, oversized, duplicate, nested or escaping archive is rejected. Only reference.alog, alarms.alrm and roast-title.txt are materialized. ZIP-supplied scripts are never run. The paired alarm sequence/targets must match the manifest exactly.
- It sends reference and alarm file URLs to Artisan's existing main connection only, after deliberate operator actions. It does not start monitoring, recording, heating, roasting or mark any portal production steps.
- Repeated sends are gated. A delivery error after an attempted send locks the attempt: inspect Artisan and reopen a fresh preparation to retry. No automatic retries or background loading occur.
- If anything differs from the expected screen, stop using the pilot, inspect Artisan and use the existing downloaded ZIP/CMD method. Do not run both preparation tools at once.
- The portable pilot is unsigned. Windows may show a publisher warning. Broad distribution needs a reviewed signing/update process. Do not disable Windows protections to install it.
- Settings and the three prepared data files are kept under your Windows user's LocalApplicationData/CremaCompanionPilot. Close Artisan before clearing those cached preparation files. Removing the portable folder removes the program; no machine-wide associations or services need uninstalling.

## Development checks

Build from the canonical source using .NET 10 SDK and build.ps1 with an output directory outside the repository. The script creates a self-contained Windows-x64 executable and copies Crema/runtime notices; all compiled/cache files stay outside the source tree. No third-party NuGet libraries are added.

Run `CremaCompanion.exe --self-test <absolute-report-path>` in a task-owned folder. Tests generate fictional preparations, reject invalid/stale/tampered archives, verify data-only extraction and exercise exact background/alarm messages against a random test-only named pipe. They never connect to the real Artisan endpoint, launch Artisan or use production data. Native GUI inspection and a real idle-Artisan operator trial are separate checks.

Before wider use: trusted package delivery/current-preparation checks, installer and signed update design, live operator validation, supported Windows/Artisan matrix, and independent review remain open. This pilot does not clear Crema's public-release gates.
