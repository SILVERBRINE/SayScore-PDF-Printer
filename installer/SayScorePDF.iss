; SayScore PDF installer. Build: iscc /DAppVersion=1.2.3 /DStageDir=<staged release> installer\SayScorePDF.iss
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef StageDir
  #define StageDir "..\build\stage"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{5B7C2E0A-8F3D-4C1B-9A6E-2D4F8B1C3E70}
AppName=SayScore PDF
AppVersion={#AppVersion}
AppPublisher=SayScore PDF contributors
AppPublisherURL=https://github.com/SILVERBRINE/SayScore-PDF-Printer
AppSupportURL=https://github.com/SILVERBRINE/SayScore-PDF-Printer/issues
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\SayScore PDF
DefaultGroupName=SayScore PDF
DisableProgramGroupPage=yes
LicenseFile={#StageDir}\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=SayScorePDF-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
; One installer for x64 and ARM64 Windows 11 (the bundled runtime is x64, emulated on ARM64).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
SetupIconFile={#StageDir}\easy_output\assets\sayscore.ico
UninstallDisplayIcon={app}\SayScorePDF.exe
UninstallDisplayName=SayScore PDF
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "Windows 로그인 시 SayScore PDF 자동 시작 (재부팅 후에도 인쇄 가능)"; Flags: checkedonce
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: checkedonce

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Excludes: "data\*,준비 상태 확인.cmd"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SayScore PDF"; Filename: "{app}\SayScorePDF.exe"
Name: "{group}\SayScore PDF 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SayScore PDF"; Filename: "{app}\SayScorePDF.exe"; Tasks: desktopicon
Name: "{commonstartup}\SayScore PDF"; Filename: "{app}\SayScorePDF.exe"; Tasks: autostart

[Run]
Filename: "{app}\SayScorePDF.exe"; Description: "SayScore PDF 실행"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\Uninstall-SayScore.ps1"" -InstallDirectory ""{app}"""; \
  Flags: runhidden waituntilterminated; RunOnceId: "RemoveSayScore"
