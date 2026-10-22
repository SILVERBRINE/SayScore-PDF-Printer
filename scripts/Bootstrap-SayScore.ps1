[CmdletBinding()]
param([switch]$NoShortcut, [switch]$InstallWsl)

# Picks how the printer reaches the app, then starts it:
# - recommended mode: a WSL 2 relay, so the printer targets an address Windows
#   does not own (needs the WSL 2 feature, virtualization and one restart);
# - simple mode: a Wintun adapter (easy_output.tunrelay) plays the same role
#   without a VM, so no restart or virtualization is needed.
# -InstallWsl (also used by the app's menu) installs the WSL 2 feature only.

$ErrorActionPreference = 'Stop'
$modeFile = Join-Path $env:LOCALAPPDATA 'SayScore PDF\mode.txt'
$simpleNote = '앱 전용 가상 네트워크 어댑터(Wintun)를 추가합니다. 관리자 확인이 필요하며, 재부팅은 필요 없습니다.'

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
    Remove-Item -LiteralPath $modeFile -Force -ErrorAction SilentlyContinue
    [void](Show-Notice "권장 모드에 필요한 Windows 기능(WSL 2)을 설치했습니다.`n`nWindows를 재부팅한 뒤 SayScore PDF를 다시 실행하세요.")
    exit 3010
}

function Start-App([switch]$Simple) {
    & (Join-Path $PSScriptRoot 'Start-SayScore.ps1') -NoShortcut:$NoShortcut -Simple:$Simple
    exit $LASTEXITCODE
}

function Save-SimpleMode {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $modeFile) | Out-Null
    [IO.File]::WriteAllText($modeFile, 'simple')
}

try {
    if ($InstallWsl) { Install-WslFeature }
    # mode.txt holds the user's choice ('simple' or 'wsl'); the app's mode toggle writes it too.
    $mode = if (Test-Path -LiteralPath $modeFile) { (Get-Content -LiteralPath $modeFile -Raw).Trim() } else { '' }
    if ($mode -eq 'simple') { Start-App -Simple }
    if (Test-WslReady) { Start-App }

    $blocker = Get-WslBlocker
    if ($blocker) {
        $answer = Show-Notice ("이 PC에서는 권장 모드(WSL 2)를 쓸 수 없습니다.`n$blocker`n`n" +
            "대신 간편 모드로 바로 사용할까요?`n`n$simpleNote") 'Warning' 'YesNo'
        if ($answer -ne 'Yes') { exit 2 }
        Save-SimpleMode
        Start-App -Simple
    }

    $answer = Show-Notice ("SayScore PDF를 어떤 방식으로 사용할까요?`n`n" +
        "[예] 권장 모드`nWindows 기능(WSL 2)을 설치합니다. 가상 프린터로 인식될 가능성이 가장 낮지만, " +
        "인터넷 연결과 재부팅이 필요합니다. Linux 배포판이나 다른 프로그램은 설치하지 않습니다.`n`n" +
        "[아니요] 간편 모드 (시험 기능)`n재부팅 없이 바로 사용합니다. $simpleNote`n`n" +
        "PC방처럼 재부팅하면 초기화되는 PC에서는 간편 모드를 고르세요.") 'Question' 'YesNoCancel'
    if ($answer -eq 'Yes') { Install-WslFeature }
    if ($answer -eq 'No') {
        Save-SimpleMode
        Start-App -Simple
    }
    exit 2
} catch {
    [void](Show-Notice ("SayScore PDF를 준비하지 못했습니다.`n`n" + $_.Exception.Message) 'Error')
    exit 1
}
