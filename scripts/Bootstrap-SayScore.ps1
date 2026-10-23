[CmdletBinding()]
param([switch]$NoShortcut, [switch]$InstallWsl)

# Starts the app with the printer relay the user chose. Either way the printer
# targets an address Windows does not own, so it is not seen as a virtual printer.
# - default ('simple' in mode.txt): a Wintun adapter (easy_output.tunrelay);
#   no restart or virtualization needed;
# - WSL ('wsl', chosen with the app's toggle): a WSL 2 relay. The WSL 2 feature
#   is installed the first time it is chosen (needs a restart).
# -InstallWsl is the elevated half of that install.

$ErrorActionPreference = 'Stop'
$modeFile = Join-Path $env:LOCALAPPDATA 'SayScore PDF\mode.txt'
# Tells SayScorePDF.exe's startup window what is happening (no-op without it).
function Set-StartupStatus([string]$Text) {
    if ($env:SAYSCORE_PROGRESS) { try { [IO.File]::WriteAllText($env:SAYSCORE_PROGRESS, $Text) } catch { } }
}

function Show-Notice([string]$Message, [string]$Icon = 'Information', [string]$Buttons = 'OK') {
    Add-Type -AssemblyName System.Windows.Forms
    return [Windows.Forms.MessageBox]::Show($Message, 'SayScore PDF', $Buttons, $Icon)
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-WslReady {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Test-WslReady.ps1')
    return $LASTEXITCODE -eq 0
}

# Returns why WSL 2 cannot be installed on this PC, or '' when it can.
function Get-WslBlocker {
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    if ([int]$os.BuildNumber -lt 19045 -or [int]$cpu.Architecture -notin @(9, 12)) {
        return '64비트 Windows 10 22H2(build 19045) 이상 또는 Windows 11이 필요합니다.'
    }
    $hypervisor = (Get-CimInstance Win32_ComputerSystem).HypervisorPresent
    if (-not $hypervisor -and (-not $cpu.VirtualizationFirmwareEnabled -or
            -not $cpu.SecondLevelAddressTranslationExtensions)) {
        return 'BIOS/UEFI에서 하드웨어 가상화가 꺼져 있습니다.'
    }
    return ''
}

function Install-WslFeature {
    Save-Mode 'wsl'
    if (-not (Test-Administrator)) {
        $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-InstallWsl')
        $process = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -Wait -PassThru
        exit $process.ExitCode
    }
    $blocker = Get-WslBlocker
    if ($blocker) { throw $blocker }
    # Only the Windows feature: no Linux distribution is installed here.
    & wsl.exe --install --no-distribution --web-download
    if ($LASTEXITCODE -ne 0) {
        # Older inbox wsl.exe builds lack --no-distribution; enable the features directly.
        & dism.exe /Online /Enable-Feature /FeatureName:Microsoft-Windows-Subsystem-Linux /All /NoRestart
        if ($LASTEXITCODE -notin @(0, 3010)) { throw "WSL 기능을 켜지 못했습니다 (코드 $LASTEXITCODE)." }
        & dism.exe /Online /Enable-Feature /FeatureName:VirtualMachinePlatform /All /NoRestart
        if ($LASTEXITCODE -notin @(0, 3010)) { throw "가상 머신 플랫폼을 켜지 못했습니다 (코드 $LASTEXITCODE)." }
        & wsl.exe --update --web-download
    }
    [void](Show-Notice "WSL 방식에 필요한 Windows 기능(WSL 2)을 설치했습니다.`n`nWindows를 재부팅한 뒤 SayScore PDF를 다시 실행하세요.")
    exit 3010
}

function Start-App([switch]$Simple) {
    & (Join-Path $PSScriptRoot 'Start-SayScore.ps1') -NoShortcut:$NoShortcut -Simple:$Simple
    exit $LASTEXITCODE
}

function Save-Mode([string]$Mode) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $modeFile) | Out-Null
    [IO.File]::WriteAllText($modeFile, $Mode)
}

try {
    if ($InstallWsl) { Install-WslFeature }
    # mode.txt holds the user's choice ('simple' or 'wsl'); the app's toggle writes it.
    $mode = if (Test-Path -LiteralPath $modeFile) { (Get-Content -LiteralPath $modeFile -Raw).Trim() } else { '' }
    # Up to v0.3.0 WSL was the default: keep PCs that already use the WSL relay on it.
    if (-not $mode -and (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'SayScore PDF\relay-wsl'))) { $mode = 'wsl' }
    if ($mode -ne 'wsl') { Start-App -Simple }

    Set-StartupStatus 'WSL 2를 확인하는 중…'
    if (Test-WslReady) { Start-App }
    # WSL was chosen but its Windows feature is missing: install it this once.
    $blocker = Get-WslBlocker
    if ($blocker) {
        [void](Show-Notice ("이 PC에서는 WSL 방식을 쓸 수 없어 기본 방식(가상 어댑터)으로 시작합니다.`n`n$blocker") 'Warning')
        Save-Mode 'simple'
        Start-App -Simple
    }
    $answer = Show-Notice ("WSL 방식에 필요한 Windows 기능(WSL 2)을 설치할까요?`n`n" +
        "인터넷 연결과 재부팅이 필요합니다. Linux 배포판이나 다른 프로그램은 설치하지 않습니다.`n`n" +
        "[아니요]를 누르면 기본 방식(가상 어댑터)으로 시작합니다.") 'Question' 'YesNo'
    if ($answer -eq 'Yes') { Install-WslFeature }
    Save-Mode 'simple'
    Start-App -Simple
} catch {
    [void](Show-Notice ("SayScore PDF를 준비하지 못했습니다.`n`n" + $_.Exception.Message) 'Error')
    exit 1
}
