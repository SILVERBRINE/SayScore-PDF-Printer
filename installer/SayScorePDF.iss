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
Filename: "{app}\SayScorePDF.exe"; Description: "SayScore PDF 실행"; Flags: postinstall nowait skipifsilent runasoriginaluser; Check: not WslRestartPending

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\Uninstall-SayScore.ps1"" -InstallDirectory ""{app}"""; \
  Flags: runhidden waituntilterminated; RunOnceId: "RemoveSayScore"

[Code]
var
  RestartForWsl: Boolean;

function RunHidden(const FileName, Params: String): Integer;
var
  Code: Integer;
begin
  if Exec(FileName, Params, '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Result := Code
  else
    Result := -1;
end;

function WslReady: Boolean;
begin
  // Checks wsl.exe and that both WSL optional components are enabled.
  Result := RunHidden(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{app}\scripts\Test-WslReady.ps1') + '"') = 0;
end;

function WslRestartPending: Boolean;
begin
  Result := RestartForWsl;
end;

procedure InstallWsl;
var
  Dism, Code: Integer;
begin
  WizardForm.StatusLabel.Caption := '프린터 중계에 필요한 Windows 기능(WSL 2)을 설치하는 중입니다...';
  // Only the Windows feature: no Linux distribution is installed here.
  Code := RunHidden(ExpandConstant('{sys}\wsl.exe'), '--install --no-distribution --web-download');
  if Code <> 0 then
  begin
    // Older inbox wsl.exe builds lack --no-distribution; enable the features directly.
    Dism := RunHidden(ExpandConstant('{sys}\dism.exe'),
      '/Online /Enable-Feature /FeatureName:Microsoft-Windows-Subsystem-Linux /All /NoRestart');
    if (Dism = 0) or (Dism = 3010) then
      Dism := RunHidden(ExpandConstant('{sys}\dism.exe'),
        '/Online /Enable-Feature /FeatureName:VirtualMachinePlatform /All /NoRestart');
    if (Dism <> 0) and (Dism <> 3010) then
      MsgBox('WSL 2 기능을 켜지 못했습니다 (코드 ' + IntToStr(Dism) + ').' + #13#10 +
             'BIOS/UEFI 가상화 설정 또는 조직 정책을 확인한 뒤 SayScore PDF를 다시 실행하세요.', mbError, MB_OK);
    RunHidden(ExpandConstant('{sys}\wsl.exe'), '--update --web-download');
  end;
  RestartForWsl := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not WslReady then
    InstallWsl;
end;

function NeedRestart: Boolean;
begin
  Result := RestartForWsl;
end;
