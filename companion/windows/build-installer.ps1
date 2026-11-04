param([Parameter(Mandatory=$true)][string]$AppDirectory,[Parameter(Mandatory=$true)][string]$OutputDirectory,[Parameter(Mandatory=$true)][string]$CompilerArchive)
$ErrorActionPreference='Stop'
$app=[IO.Path]::GetFullPath($AppDirectory)
$output=[IO.Path]::GetFullPath($OutputDirectory)
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if($output.StartsWith($repo+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or $output -eq $repo){throw 'Keep installer output outside the source repository.'}
$pin=Get-Content (Join-Path $PSScriptRoot 'build-installer.json') -Raw | ConvertFrom-Json
if((Get-FileHash -LiteralPath $CompilerArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pin.sha256){throw 'Installer compiler checksum mismatch.'}
if(-not (Test-Path -LiteralPath (Join-Path $app 'CremaCompanion.exe'))){throw 'Build the companion first.'}
New-Item -ItemType Directory -Path $output -Force | Out-Null
$toolRoot=Join-Path $output 'compiler'
New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip=[IO.Compression.ZipFile]::OpenRead([IO.Path]::GetFullPath($CompilerArchive))
try{foreach($entry in $zip.Entries){$target=[IO.Path]::GetFullPath((Join-Path $toolRoot $entry.FullName));if(-not $target.StartsWith($toolRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe compiler archive path.'}}}finally{$zip.Dispose()}
[IO.Compression.ZipFile]::ExtractToDirectory([IO.Path]::GetFullPath($CompilerArchive),$toolRoot,$true)
$compiler=Join-Path $toolRoot "nsis-$($pin.version)/makensis.exe"
Copy-Item -LiteralPath (Join-Path $toolRoot "nsis-$($pin.version)/COPYING") -Destination (Join-Path $app 'INSTALLER-NOTICE.txt')
$installer=Join-Path $output 'CremaCompanion-Setup-0.1.0-preview4-win-x64.exe'
& $compiler '/V2' "/DPayloadDir=$app" "/DInstallerOutput=$installer" (Join-Path $PSScriptRoot 'installer.nsi')
if($LASTEXITCODE -ne 0){throw 'Installer build failed.'}
Get-FileHash -LiteralPath $installer -Algorithm SHA256 | Select-Object Hash
