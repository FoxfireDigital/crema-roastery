param([Parameter(Mandatory=$true)][string]$Installer,[Parameter(Mandatory=$true)][string]$AppDirectory,[Parameter(Mandatory=$true)][string]$TrialDirectory,[Parameter(Mandatory=$true)][string]$ReportPath)
$ErrorActionPreference='Stop'
$trial=[IO.Path]::GetFullPath($TrialDirectory)
if([IO.Path]::GetFileName($trial) -cne 'companion-install-trial' -or $trial.StartsWith('\\')){throw 'Use the named local companion-install-trial directory.'}
$registry='HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall/CremaCompanionPilot'
$desktop=Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'Crema Companion.lnk'
$menu=Join-Path ([Environment]::GetFolderPath('Programs')) 'Crema Companion'
if((Test-Path -LiteralPath $registry) -or (Test-Path -LiteralPath $desktop) -or (Test-Path -LiteralPath $menu)){throw 'Existing installation or shortcuts found; no trial changes made.'}
$installed=Join-Path $trial 'CremaCompanion.exe'
if(Test-Path -LiteralPath $installed){throw 'Existing trial installation found.'}
$settings=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CremaCompanionPilot/settings.json'
$settingsHash=if(Test-Path -LiteralPath $settings){(Get-FileHash -LiteralPath $settings).Hash}else{$null}
$checks=[Collections.Generic.List[string]]::new()
function Run([string]$File,[string[]]$Arguments){$process=Start-Process -FilePath $File -ArgumentList $Arguments -WindowStyle Hidden -Wait -PassThru;return $process.ExitCode}
function Check([bool]$Passed,[string]$Name){if(-not $Passed){throw "Installer check failed: $Name"};$checks.Add($Name)}
try{
    $created=$false;$mutex=[Threading.Mutex]::new($false,'Local\CremaCompanionPilot',[ref]$created)
    try{if(-not $created){throw 'Close Companion before the installer trial.'};$code=Run $Installer @('/S',('/D='+$trial));Check ($code -eq 4 -and -not (Test-Path -LiteralPath $installed)) 'running-companion-refuses-install-before-writing'}finally{$mutex.Dispose()}
    Check ((Run $Installer @('/S',('/D='+$trial))) -eq 0) 'per-user-silent-install'
    $expected=(Get-FileHash -LiteralPath (Join-Path $AppDirectory 'CremaCompanion.exe')).Hash
    Check ((Get-FileHash -LiteralPath $installed).Hash -eq $expected) 'installed-executable-matches-reviewed-payload'
    Check ((Test-Path -LiteralPath $desktop) -and (Test-Path -LiteralPath (Join-Path $menu 'Crema Companion.lnk'))) 'desktop-and-start-menu-shortcuts'
    $shell=New-Object -ComObject WScript.Shell
    try{Check ($shell.CreateShortcut($desktop).TargetPath -eq $installed) 'desktop-shortcut-target'}finally{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)}
    $registration=Get-ItemProperty -LiteralPath $registry
    Check ($registration.DisplayVersion -eq '0.2.0-preview.1' -and $registration.InstallLocation -eq $trial) 'current-user-uninstall-registration'
    Check ($registration.UninstallString -eq ('"'+(Join-Path $trial 'Uninstall.exe')+'"')) 'quoted-windows-uninstall-command'
    $sentinel=Join-Path $trial 'keep-me.txt';if(Test-Path -LiteralPath $sentinel){if([IO.File]::ReadAllText($sentinel) -ne 'unrelated-file-must-survive'){throw 'Unexpected trial sentinel'}}else{[IO.File]::WriteAllText($sentinel,'unrelated-file-must-survive')}
    Check ((Run $Installer @('/S',('/D='+$trial))) -eq 0 -and [IO.File]::ReadAllText($sentinel) -eq 'unrelated-file-must-survive') 'upgrade-preserves-unrelated-file'
    $installedReport=Join-Path ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($ReportPath))) 'installed-companion-checks.json'
    Check ((Run $installed @('--self-test',('"'+$installedReport+'"'))) -eq 0) 'installed-runtime-self-test-exits-successfully'
    $result=Get-Content -LiteralPath $installedReport -Raw|ConvertFrom-Json
    Check ($result.result -eq 'passed' -and $result.count -ge 64 -and -not $result.realArtisanTouched -and -not $result.serverChanged) 'installed-preparation-connection-and-credential-checks'
    Check ((Run (Join-Path $trial 'Uninstall.exe') @('/S')) -eq 0) 'silent-uninstall'
    Check (-not (Test-Path -LiteralPath $installed) -and -not (Test-Path -LiteralPath $registry) -and -not (Test-Path -LiteralPath $desktop) -and -not (Test-Path -LiteralPath $menu)) 'program-registration-and-shortcuts-removed'
    Check ([IO.File]::ReadAllText($sentinel) -eq 'unrelated-file-must-survive') 'uninstall-preserves-unrelated-file'
    $afterHash=if(Test-Path -LiteralPath $settings){(Get-FileHash -LiteralPath $settings).Hash}else{$null}
    Check ($settingsHash -eq $afterHash) 'existing-companion-settings-unchanged'
    @{result='passed';count=$checks.Count;checks=$checks.ToArray();installerSHA256=(Get-FileHash -LiteralPath $Installer).Hash.ToLowerInvariant();installedExecutableSHA256=$expected.ToLowerInvariant();serverChanged=$false;realArtisanTouched=$false}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $ReportPath
}catch{
    @{result='failed';checks=$checks.ToArray();error=$_.Exception.Message;trialDirectory=$trial}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $ReportPath
    throw
}
