[CmdletBinding()]
param([switch]$NoShortcut)

$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))

function Show-Notice([string]$Message, [string]$Icon = 'Information') {
    Add-Type -AssemblyName System.Windows.Forms
    [void][Windows.Forms.MessageBox]::Show(
        $Message, 'SayScore PDF', 'OK', $Icon)
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-WslReady {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { return $false }
    # The inbox stub on PCs without WSL does not support --version.
    & wsl.exe --version 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

try {
    if (-not (Test-WslReady)) {
        $os = Get-CimInstance Win32_OperatingSystem
        $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
        if ([int]$os.BuildNumber -lt 19045 -or [int]$cpu.Architecture -notin @(9, 12)) {
            throw '64비트 Windows 10 22H2(build 19045) 이상 또는 Windows 11이 필요합니다.'
        }
        $hypervisor = (Get-CimInstance Win32_ComputerSystem).HypervisorPresent
        if (-not $hypervisor -and (-not $cpu.VirtualizationFirmwareEnabled -or
                -not $cpu.SecondLevelAddressTranslationExtensions)) {
            throw 'BIOS/UEFI에서 하드웨어 가상화와 SLAT를 켜야 합니다.'
        }
        if (-not (Test-Administrator)) {
            $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
            $process = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -Wait -PassThru
            exit $process.ExitCode
        }
        Add-Type -AssemblyName System.Windows.Forms
        $answer = [Windows.Forms.MessageBox]::Show(
            "프린터 중계에 필요한 Windows 기능(WSL 2)을 설치합니다.`n`nLinux 배포판이나 다른 프로그램은 설치하지 않습니다. 인터넷 연결이 필요하며, 설치 후 재부팅해야 할 수 있습니다.`n`n계속할까요?",
            'SayScore PDF · 새 PC 준비', 'YesNo', 'Question')
        if ($answer -ne 'Yes') { exit 2 }

        & wsl.exe --install --no-distribution --web-download
        if ($LASTEXITCODE -ne 0) {
            # Older inbox wsl.exe builds lack --no-distribution; enable the features directly.
            & dism.exe /Online /Enable-Feature /FeatureName:Microsoft-Windows-Subsystem-Linux /All /NoRestart
            if ($LASTEXITCODE -notin @(0, 3010)) { throw "WSL 기능을 켜지 못했습니다 (코드 $LASTEXITCODE)." }
            & dism.exe /Online /Enable-Feature /FeatureName:VirtualMachinePlatform /All /NoRestart
            if ($LASTEXITCODE -notin @(0, 3010)) { throw "가상 머신 플랫폼을 켜지 못했습니다 (코드 $LASTEXITCODE)." }
            & wsl.exe --update --web-download
        }
        Show-Notice "WSL 2 기능을 설치했습니다.`n`nWindows를 재부팅한 뒤 SayScore PDF를 다시 실행하세요."
        exit 3010
    }

    try {
        & (Join-Path $PSScriptRoot 'Start-SayScore.ps1') -NoShortcut:$NoShortcut
    } catch {
        Show-Notice ("필수 구성요소 설치 후 Windows를 재부팅하고 SayScore PDF를 다시 실행하세요.`n`n" +
                     $_.Exception.Message) 'Warning'
        exit 3010
    }
} catch {
    Show-Notice ("SayScore PDF를 준비하지 못했습니다.`n`n" + $_.Exception.Message) 'Error'
    exit 1
}
