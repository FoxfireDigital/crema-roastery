# Crema Companion — portable Windows pilot

This is an optional pilot for Windows x64 and reviewed Artisan 3.1.0 and 4.0.2 handoffs. The selected installed version is displayed, and the connected main-window process is checked for a reviewed version and the same Windows session. Operator validation on the roasting computer is required before relying on it. The existing portal ZIP/CMD workflow remains the fallback. Crema server installation and production data are unchanged.

## Roast-day use

1. Run the per-user setup and use the **Crema Companion** desktop or Start menu shortcut. A portable ZIP is also available: keep its entire folder, including the runtime notices, and open CremaCompanion.exe. The build includes its runtime; no service, scheduled task, sign-in, port, startup registration or administrator account is required.
2. In Crema, prepare the accepted, unroasted load using the correct machine, First/Second schedule and targets. Download a fresh preparation ZIP. Changed plans or profiles require a new preparation.
3. Choose **Open preparation**, drop the ZIP onto the window, or paste its local path under **Help & settings** and press Enter. Open always offers a new file selection. Review the roast card, machine, green weight, First/Second schedule and three large temperature targets. The four-step strip shows where you are. Manual extraction is unnecessary; included CMD/PowerShell files never execute.
4. Review the coffee, green ounces, machine, session, title and Fahrenheit targets against the current portal. Check that the correct USB roaster is connected, previous work saved, and Artisan idle with monitoring OFF. Check readiness and choose **Load background**.
5. The normal Program Files installation is detected automatically. **Choose Artisan** under **Help & settings** selects another supported installation. If Artisan is closed, its selected artisan.exe opens when requested, without control arguments. Finish startup dialogs, confirm monitoring OFF, check readiness again and load the background. A running but unreachable instance is an error, not permission to launch a second copy.
6. Verify the expected background curve is visible and monitoring remains OFF. Check the inline confirmation, then choose **Load paired alarms**. Verify Charge / Drop / Off targets under **Config → Alarms**. Artisan 4 Production mode hides this menu: use **Config → Mode → Standard** to inspect it, and return to Production afterward if desired; enable Load from background for embedded alarms. No successful send is described as a verified load.
7. After checking all three targets in Artisan, check the final inline confirmation and choose **Finish preparation**. **Verified by you** is your confirmation, not a hardware acknowledgement. Choose **Copy title**, then paste into **Roast → Properties → Title**; copying replaces clipboard text. The active title is not set automatically. **Open next preparation** starts a fresh review.
8. Operate the roast manually. Record finished weight/cooling in Crema and upload the saved foreground .alog using its existing review workflow. This pilot does not watch folders or upload files.

First means cold or this particular machine idle for at least ten minutes; Second is continuing warm work. The companion cannot measure machine heat, identify the attached USB roaster, detect an active roast, or verify that Artisan accepted a load. Off is Artisan monitoring OFF, not a guaranteed physical heater shutdown.

## Boundaries and recovery

- This build has no portal connection. Included checksums detect inconsistent files, not a trusted publisher. Only open fresh packages from your own known Crema portal. The readiness check includes confirmation against the live plan. Packages older than 24 hours or more than five minutes in the future are rejected; this is not a substitute for live freshness checks.
- A malformed, oversized, duplicate, nested or escaping archive is rejected. Only reference.alog, alarms.alrm and roast-title.txt are materialized. ZIP-supplied scripts are never run. The paired alarm sequence/targets must match the manifest exactly.
- It sends reference and alarm file URLs to Artisan's existing main connection only, after deliberate operator actions. It does not start monitoring, recording, heating, roasting or mark any portal production steps.
- Before sending, Windows resolves each saved file through its open handle. This preserves the real location when a packaged launcher redirects AppData; Artisan receives the actual local file path. Network destinations are refused.
- Repeated sends are gated. A delivery error after an attempted send locks the attempt: inspect Artisan and reopen a fresh preparation to retry. No automatic retries or background loading occur.
- If anything differs from the expected screen, stop using the pilot, inspect Artisan and use the existing downloaded ZIP/CMD method. Do not run both preparation tools at once.
- The portable pilot is unsigned. Windows may show a publisher warning. Broad distribution needs a reviewed signing/update process. Do not disable Windows protections to install it.
- Settings and the three prepared data files are kept under your Windows user's LocalApplicationData/CremaCompanionPilot. Close Artisan before clearing those cached files. Windows may redirect AppData for packaged launchers; sent paths resolve the actual files. Setup installs under LocalAppData/Programs/Crema Companion for your account. Use Windows Installed apps or the Start menu uninstaller to remove its program files and shortcuts. Settings/preparations and unrelated files are retained. A portable copy can simply be removed after closing it.
- Artisan **File → New** starts its monitoring/recording workflow. Do not use New to clear a profile during an idle preparation test. RESET clears disposable test work without starting a new roast. Companion never sends either operation.

## Development checks

Build from the canonical source using .NET 10 SDK and build.ps1 with an output directory outside the repository. The script creates a self-contained Windows-x64 executable and copies Crema/runtime notices; all compiled/cache files stay outside the source tree. No third-party NuGet libraries are added.

Run `CremaCompanion.exe --self-test <absolute-report-path>` in a task-owned folder. Tests generate fictional preparations, reject invalid/stale/tampered archives, verify data-only extraction and exercise exact background/alarm messages against a random test-only named pipe. They never connect to the real Artisan endpoint, launch Artisan or use production data. Native GUI inspection and a real idle-Artisan operator trial are separate checks.

Build the optional installer with build-installer.ps1 and the checksum-pinned NSIS archive identified in build-installer.json. The script verifies the vendor hash before extraction/compilation. Installer checks cover a running-instance guard, installed-payload hashes, desktop/Start menu shortcuts, per-user registration, upgrade, all installed runtime checks and uninstall preserving unrelated files/settings. No recursive removal of an installation folder or user-data folder is used.

Before wider use: trusted package delivery/current-preparation checks, publisher signing and signed updates, live operator validation, supported Windows/Artisan matrix and independent review remain open. This pilot does not clear Crema's public-release gates.

## Exact 4.0.2 source review

Artisan v4.0.2 commit 1f678a8336c28c4dc0ac08b9a28eccbc361130e5 retains main GUID 9068bd2fa8e54945a6be1f1a0a589e92, line-delimited file URLs, `?template` for background loading, and `.alrm` for alarm loading. [Official source](https://github.com/artisan-roaster-scope/artisan/tree/1f678a8336c28c4dc0ac08b9a28eccbc361130e5). This is independent client interoperability; no Artisan code or application binary is bundled. Other Artisan versions are held for review rather than assumed compatible. Source inspection is distinct from a real idle-application trial.

Photos and completed .alog uploads belong in Crema using the direct controls below each batch. This Companion remains a preparation utility, with no portal credentials, folder watching, camera access or automatic uploads.
