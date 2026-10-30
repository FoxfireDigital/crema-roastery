param([switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'

function Read-ArtisanPackage([string]$Folder) {
    $packageRoot = [IO.Path]::GetFullPath($Folder)
    $manifestPath = Join-Path $packageRoot 'manifest.json'
    if ((Get-Item -LiteralPath $manifestPath).Length -gt 65536) { throw 'The manifest is too large.' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.format -ne 1 -or $manifest.roaster -isnot [string] -or [string]::IsNullOrWhiteSpace($manifest.roaster) -or $manifest.roaster.Length -gt 40 -or $manifest.roaster -match '[\x00-\x1f\x7f]' -or $manifest.mode -notin @('first','second')) { throw 'Unsupported preparation package.' }
    if ($manifest.profile_format -ne 'artisan-python-literal') { throw 'This preparation uses an older file format. Download and extract a fresh package from the portal.' }
    $fileNames = @('reference.alog','alarms.alrm')
    if ($null -ne $manifest.roast_title) {
        if ($manifest.roast_title -isnot [string] -or [string]::IsNullOrWhiteSpace($manifest.roast_title) -or $manifest.roast_title.Length -gt 300 -or $manifest.roast_title -match '[\x00-\x1f\x7f]') { throw 'Invalid roast title.' }
        $fileNames += 'roast-title.txt'
    }
    foreach ($fileName in $fileNames) {
        $expected = $manifest.files.$fileName
        $target = Join-Path $packageRoot $fileName
        if ($expected -notmatch '^[a-f0-9]{64}$' -or (Get-Item -LiteralPath $target).Length -gt 2000000) { throw 'Invalid preparation file.' }
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try { $actual = [BitConverter]::ToString($algorithm.ComputeHash([IO.File]::ReadAllBytes($target))).Replace('-','').ToLowerInvariant() } finally { $algorithm.Dispose() }
        if ($actual -ne $expected) { throw "Checksum mismatch: $fileName. Prepare the load again." }
    }
    if ($null -ne $manifest.roast_title -and ([IO.File]::ReadAllText((Join-Path $packageRoot 'roast-title.txt'),[Text.Encoding]::UTF8).TrimEnd("`r","`n")) -cne $manifest.roast_title) { throw 'The title and manifest disagree.' }
    $alarms = Get-Content -LiteralPath (Join-Path $packageRoot 'alarms.alrm') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (($alarms.alarmactions -join ',') -ne '16,13,15' -or ($alarms.alarmguards -join ',') -ne '-1,0,1' -or ($alarms.alarmtimes -join ',') -ne '-1,0,6') { throw 'Unexpected alarm sequence.' }
    $culture = [Globalization.CultureInfo]::InvariantCulture
    $charge = [decimal]::Parse([string]$manifest.charge,$culture)
    $drop = [decimal]::Parse([string]$manifest.drop,$culture)
    $off = [decimal]::Parse([string]$manifest.off,$culture)
    if ($charge -lt 32 -or $drop -le $charge -or $off -ne ($drop + [decimal]0.1) -or $off -gt 600) { throw 'Invalid alarm temperatures.' }
    if ([decimal]$alarms.alarmtemperatures[0] -ne $charge -or [decimal]$alarms.alarmtemperatures[1] -ne $drop -or [decimal]$alarms.alarmtemperatures[2] -ne $off) { throw 'Manifest and alarms disagree.' }
    return $manifest
}

function Connect-ArtisanMain([string]$PipeName = '9068bd2fa8e54945a6be1f1a0a589e92') {
    # Artisan 3.1.0 appGuid; deliberately never use its viewer pipe.
    $stream = [IO.Pipes.NamedPipeClientStream]::new('.', $PipeName, [IO.Pipes.PipeDirection]::Out)
    try { $stream.Connect(450); return $stream } catch { $stream.Dispose(); return $null }
}

function Send-ArtisanFile($Stream, [string]$FilePath, [switch]$Background) {
    $fileUri = ([Uri][IO.Path]::GetFullPath($FilePath)).AbsoluteUri
    if ($Background) { $fileUri += '?template' }
    # QtSingleApplication reads one UTF-8 URL per newline, with no response/ack.
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($fileUri + "`n")
    $Stream.Write($bytes,0,$bytes.Length)
    $Stream.Flush()
}

try {
    $manifest = Read-ArtisanPackage $PSScriptRoot
    if ($ValidateOnly) {
        [pscustomobject]@{valid=$true;roaster=$manifest.roaster;mode=$manifest.mode;charge=$manifest.charge;drop=$manifest.drop;off=$manifest.off;preparation=$manifest.preparation_id} | ConvertTo-Json -Compress
        exit 0
    }
    Add-Type -AssemblyName System.Windows.Forms
    $title = 'Crema - Prepare in Artisan'
    $mutex = [Threading.Mutex]::new($false,'Local\CremaArtisanPrepare')
    if (-not $mutex.WaitOne(0)) { throw 'Another preparation is already open. Finish or cancel it first.' }
    $pipe = $null
    try {
        $age = [DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse($manifest.created_utc)
        if ($age.TotalHours -gt 24 -or $age.TotalMinutes -lt -5) { throw 'This download is old or its date is invalid. Prepare the load again in the portal.' }
        $summary = "Plan #$($manifest.plan_id), roast #$($manifest.planned_batch_id)`n$($manifest.coffee) - $($manifest.roast_level)`nRoaster: $($manifest.roaster) | Green: $($manifest.green_oz) oz`nSession: $($manifest.mode)`nTitle: $($manifest.roast_title)`nProfile: $($manifest.name), revision $($manifest.revision)`nBT Charge $($manifest.charge) F / Drop $($manifest.drop) F / Off $($manifest.off) F"
        $question = "$summary`n`nConfirm the correct USB roaster is connected. First means this machine has been idle at least 10 minutes; Second means continuing warm roasting.`n`nArtisan must be idle, with monitoring OFF, no recording in progress, and any previous roast saved. Close comparison/designer views. Has the plan/profile remained unchanged since downloading, and is it ready to prepare?"
        if ([Windows.Forms.MessageBox]::Show($question,$title,'YesNo','Question') -ne 'Yes') { return }
        $pipe = Connect-ArtisanMain
        if ($null -eq $pipe) {
            # A running process without the expected pipe is not permission to open another.
            if (Get-Process -Name artisan -ErrorAction SilentlyContinue) { throw 'Artisan is running but its main window is not reachable. Do not open a second copy. Check its version and finish any startup dialog, then retry.' }
            $picker = [Windows.Forms.OpenFileDialog]::new()
            $picker.Title = 'Choose artisan.exe on this roasting computer'
            $picker.Filter = 'Artisan program (artisan.exe)|artisan.exe'
            if ($picker.ShowDialog() -ne 'OK') { return }
            if ([IO.Path]::GetFileName($picker.FileName) -ine 'artisan.exe') { throw 'Choose artisan.exe.' }
            # Interactive app explicitly requested by the operator; no roast/control arguments.
            Start-Process -FilePath $picker.FileName | Out-Null
            $deadline = [DateTime]::UtcNow.AddSeconds(45)
            do { Start-Sleep -Milliseconds 300; $pipe = Connect-ArtisanMain } while ($null -eq $pipe -and [DateTime]::UtcNow -lt $deadline)
            if ($null -eq $pipe) { throw 'Artisan did not expose its main window. Nothing was sent. Finish startup and retry.' }
            if ([Windows.Forms.MessageBox]::Show('Artisan is open. Finish any startup dialogs and confirm monitoring is OFF and the correct USB roaster is connected. Ready to load the reference?',$title,'YesNo','Question') -ne 'Yes') { return }
        }
        Send-ArtisanFile $pipe (Join-Path $PSScriptRoot 'reference.alog') -Background
        $verify = "Reference request sent to the existing main Artisan window. This is not an acknowledgement that it loaded.`n`nVerify the expected background curve is visible, monitoring is still OFF, and no viewer window opened. If Artisan was monitoring or did not load it, choose No and retry only when idle.`n`nIs the correct background now loaded and Artisan still idle?"
        if ([Windows.Forms.MessageBox]::Show($verify,$title,'YesNo','Question') -ne 'Yes') { return }
        Send-ArtisanFile $pipe (Join-Path $PSScriptRoot 'alarms.alrm')
        if ($manifest.roast_title) {
            if ([Windows.Forms.MessageBox]::Show("Roast title: $($manifest.roast_title)`n`nBackground loading does not change Artisan's active roast title. Copy this title to your clipboard? This replaces the current clipboard text. Then open Roast > Properties, paste into Title and confirm before roasting. Artisan's own autosave settings remain unchanged.",$title,'YesNo','Question') -eq 'Yes') {
                [Windows.Forms.Clipboard]::SetText($manifest.roast_title)
            }
        }
        [Windows.Forms.MessageBox]::Show("Alarm request sent.`n`nOpen Config > Alarms and verify Charge $($manifest.charge) F, Drop $($manifest.drop) F, Off $($manifest.off) F. Drop follows Charge; Off waits for the Drop event. All use BT rising above the threshold. Enable Load from background for embedded alarms.`n`nOff is Artisan monitoring OFF, not a guaranteed physical heater shutdown. No monitoring or roast was started by this helper. Portal production boxes and weights are unchanged.",$title,'OK','Information') | Out-Null
    } finally {
        if ($null -ne $pipe) { $pipe.Dispose() }
        $mutex.ReleaseMutex();$mutex.Dispose()
    }
} catch {
    if ($ValidateOnly) { Write-Error $_; exit 1 }
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show($_.Exception.Message,'Crema - Preparation stopped','OK','Error') | Out-Null
    exit 1
}
