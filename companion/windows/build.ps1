param([Parameter(Mandatory=$true)][string]$OutputDirectory,[string]$Dotnet='dotnet',[string]$PackageCache='')
$ErrorActionPreference='Stop'
$project=Join-Path $PSScriptRoot 'CremaCompanion.csproj'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$output=[IO.Path]::GetFullPath($OutputDirectory)
if($output.StartsWith($repo+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or $output -eq $repo){throw 'Keep compiled output outside the source repository.'}
New-Item -ItemType Directory -Path $output -Force|Out-Null
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1';$env:DOTNET_NOLOGO='1'
$env:DOTNET_CLI_HOME=Join-Path $output 'cli-home';$env:NUGET_PACKAGES=if($PackageCache){[IO.Path]::GetFullPath($PackageCache)}else{Join-Path $output 'packages'}
& $Dotnet publish $project -c Release -r win-x64 --self-contained true -p:RestoreLockedMode=true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:DebugType=None -p:DebugSymbols=false "-p:BaseOutputPath=$output/bin/" "-p:BaseIntermediateOutputPath=$output/obj/" "-p:MSBuildProjectExtensionsPath=$output/obj/" -o (Join-Path $output 'app')
if($LASTEXITCODE -ne 0){throw 'Companion build failed.'}
Copy-Item -LiteralPath (Join-Path $repo 'LICENSE') -Destination (Join-Path $output 'app/LICENSE-CREMA.txt')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README.md') -Destination (Join-Path $output 'app/START-HERE.md')
$noticeRoot=Join-Path $output 'app/runtime-notices';New-Item -ItemType Directory -Path $noticeRoot -Force|Out-Null
foreach($package in @('microsoft.netcore.app.runtime.win-x64','microsoft.windowsdesktop.app.runtime.win-x64')){
  $packageRoot=Join-Path $env:NUGET_PACKAGES $package
  $notices=Get-ChildItem -LiteralPath $packageRoot -Recurse -File | Where-Object {$_.Name -match '^(LICENSE|THIRD[-_]?PARTY|THIRDPARTY)' -and $_.Extension -in @('','.txt','.TXT','.md')}
  if(-not $notices){throw "Runtime notices were not found: $package"}
  $dest=Join-Path $noticeRoot $package;New-Item -ItemType Directory -Path $dest -Force|Out-Null
  foreach($file in $notices){Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $dest $file.Name)}
}
Get-FileHash -LiteralPath (Join-Path $output 'app/CremaCompanion.exe') -Algorithm SHA256 | Select-Object Hash
$webview=Join-Path $env:NUGET_PACKAGES 'microsoft.web.webview2/1.0.4314.35'
$webviewNotices=Join-Path $noticeRoot 'microsoft.web.webview2';New-Item -ItemType Directory -Path $webviewNotices -Force|Out-Null
foreach($name in @('LICENSE.txt','NOTICE.txt')){Copy-Item -LiteralPath (Join-Path $webview $name) -Destination (Join-Path $webviewNotices $name)}
