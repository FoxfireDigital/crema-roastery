Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
Name "Crema Companion Pilot"
OutFile "${InstallerOutput}"
InstallDir "$LOCALAPPDATA\Programs\Crema Companion"
RequestExecutionLevel user
SetCompressor /SOLID zlib
SetOverwrite on
BrandingText "Crema · Artisan preparation"
VIProductVersion "0.2.0.2"
VIAddVersionKey "ProductName" "Crema Companion Pilot"
VIAddVersionKey "FileDescription" "Crema Companion per-user installer"
VIAddVersionKey "FileVersion" "0.2.0-preview.2"
VIAddVersionKey "LegalCopyright" "Crema contributors · MIT"
Var CompanionMutex
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Set up Crema Companion"
!define MUI_WELCOMEPAGE_TEXT "Prepare your next roast in Artisan with a clear roast summary and guided background/alarm handoff.$\r$\n$\r$\nInstalls for your Windows account and adds desktop and Start menu shortcuts. No administrator account or background service is required.$\r$\n$\r$\nChoose Exit Companion from the coffee tray menu before installing. Artisan can stay open."
!define MUI_FINISHPAGE_RUN "$INSTDIR\CremaCompanion.exe"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!define MUI_FINISHPAGE_RUN_TEXT "Open Crema Companion"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

!macro GuardCompanion
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "Local\CremaCompanionPilot") p .r0 ?e'
  Pop $1
  StrCpy $CompanionMutex $0
  ${If} $1 = 183
    System::Call 'kernel32::CloseHandle(p r0)'
    MessageBox MB_OK|MB_ICONINFORMATION "Choose Exit Companion from the coffee tray menu, then run setup or uninstall again." /SD IDOK
    SetErrorLevel 4
    Abort
  ${EndIf}
!macroend

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "This build requires 64-bit Windows." /SD IDOK
    SetErrorLevel 5
    Abort
  ${EndIf}
  SetShellVarContext current
  !insertmacro GuardCompanion
FunctionEnd

Function un.onInit
  SetShellVarContext current
  !insertmacro GuardCompanion
FunctionEnd

Section "Crema Companion"
  SetOutPath "$INSTDIR"
  File "${PayloadDir}\CremaCompanion.exe"
  File "${PayloadDir}\LICENSE-CREMA.txt"
  File "${PayloadDir}\START-HERE.md"
  File "${PayloadDir}\INSTALLER-NOTICE.txt"
  File /r "${PayloadDir}\runtime-notices"
  CreateDirectory "$SMPROGRAMS\Crema Companion"
  CreateShortcut "$DESKTOP\Crema Companion.lnk" "$INSTDIR\CremaCompanion.exe" "" "$INSTDIR\CremaCompanion.exe"
  CreateShortcut "$SMPROGRAMS\Crema Companion\Crema Companion.lnk" "$INSTDIR\CremaCompanion.exe" "" "$INSTDIR\CremaCompanion.exe"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateShortcut "$SMPROGRAMS\Crema Companion\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CremaCompanionPilot" "DisplayName" "Crema Companion Pilot"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CremaCompanionPilot" "DisplayVersion" "0.2.0-preview.2"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CremaCompanionPilot" "Publisher" "Crema contributors"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CremaCompanionPilot" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CremaCompanionPilot" "DisplayIcon" "$INSTDIR\CremaCompanion.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CremaCompanionPilot" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CremaCompanionPilot" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CremaCompanionPilot" "NoRepair" 1
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\Crema Companion.lnk"
  Delete "$SMPROGRAMS\Crema Companion\Crema Companion.lnk"
  Delete "$SMPROGRAMS\Crema Companion\Uninstall.lnk"
  RMDir "$SMPROGRAMS\Crema Companion"
  Delete "$INSTDIR\CremaCompanion.exe"
  Delete "$INSTDIR\LICENSE-CREMA.txt"
  Delete "$INSTDIR\START-HERE.md"
  Delete "$INSTDIR\INSTALLER-NOTICE.txt"
  Delete "$INSTDIR\runtime-notices\microsoft.netcore.app.runtime.win-x64\LICENSE.TXT"
  Delete "$INSTDIR\runtime-notices\microsoft.netcore.app.runtime.win-x64\THIRD-PARTY-NOTICES.TXT"
  Delete "$INSTDIR\runtime-notices\microsoft.windowsdesktop.app.runtime.win-x64\LICENSE"
  Delete "$INSTDIR\runtime-notices\microsoft.web.webview2\LICENSE.txt"
  Delete "$INSTDIR\runtime-notices\microsoft.web.webview2\NOTICE.txt"
  RMDir "$INSTDIR\runtime-notices\microsoft.web.webview2"
  RMDir "$INSTDIR\runtime-notices\microsoft.netcore.app.runtime.win-x64"
  RMDir "$INSTDIR\runtime-notices\microsoft.windowsdesktop.app.runtime.win-x64"
  RMDir "$INSTDIR\runtime-notices"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CremaCompanionPilot"
  DetailPrint "Preparation files and settings kept in your local application data."
SectionEnd
