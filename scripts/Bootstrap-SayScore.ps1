[CmdletBinding()]
param()

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

function Get-DockerDesktop {
    @((Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
      (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe')) |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
}

try {
    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    $desktop = Get-DockerDesktop
    $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if (-not ($docker -and $desktop -and $wsl)) {
        $os = Get-CimInstance Win32_OperatingSystem
        $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
        if ([int]$os.BuildNumber -lt 19045 -or [int]$cpu.Architecture -notin @(9, 12)) {
            throw '64비트 Windows 10 22H2(build 19045) 이상 또는 Windows 11이 필요합니다.'
        }
        if (-not $cpu.VirtualizationFirmwareEnabled -or
            -not $cpu.SecondLevelAddressTranslationExtensions) {
            throw 'BIOS/UEFI에서 하드웨어 가상화와 SLAT를 켜야 합니다.'
        }
        if (-not (Test-Administrator)) {
            $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
            $process = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -Wait -PassThru
            exit $process.ExitCode
        }
        Add-Type -AssemblyName System.Windows.Forms
        $answer = [Windows.Forms.MessageBox]::Show(
            "새 PC 준비를 위해 WSL 2와 Docker Desktop을 설치합니다.`n`n인터넷 연결과 재부팅이 필요할 수 있으며, Docker Desktop 사용 조건은 사용자/조직이 확인해야 합니다.`n`n계속할까요?",
            'SayScore PDF · 새 PC 준비', 'YesNo', 'Question')
        if ($answer -ne 'Yes') { exit 2 }

        if (-not $wsl) {
            & dism.exe /Online /Enable-Feature /FeatureName:Microsoft-Windows-Subsystem-Linux /All /NoRestart
            if ($LASTEXITCODE -notin @(0, 3010)) { throw "WSL 기능을 켜지 못했습니다 (코드 $LASTEXITCODE)." }
            & dism.exe /Online /Enable-Feature /FeatureName:VirtualMachinePlatform /All /NoRestart
            if ($LASTEXITCODE -notin @(0, 3010)) { throw "가상 머신 플랫폼을 켜지 못했습니다 (코드 $LASTEXITCODE)." }
        }
        if (-not (Get-DockerDesktop)) {
            $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
            if (-not $winget) {
                throw 'Docker Desktop 자동 설치에 필요한 Windows 앱 설치 관리자(winget)가 없습니다.'
            }
            & $winget.Source install --exact --id Docker.DockerDesktop --source winget `
                --accept-source-agreements --accept-package-agreements --silent
            if ($LASTEXITCODE -ne 0) { throw "Docker Desktop 설치에 실패했습니다 (코드 $LASTEXITCODE)." }
        }
        $desktop = Get-DockerDesktop
        if (-not $desktop) { throw 'Docker Desktop 설치 후 실행 파일을 찾지 못했습니다.' }
        Start-Process -FilePath $desktop -WindowStyle Hidden
    }

    try {
        & (Join-Path $PSScriptRoot 'Start-SayScore.ps1')
    } catch {
        Show-Notice ("필수 구성요소 설치 후 Windows를 재부팅하고 'SayScore PDF.cmd'를 다시 실행하세요.`n`n" +
                     $_.Exception.Message) 'Warning'
        exit 3010
    }
} catch {
    Show-Notice ("SayScore PDF를 준비하지 못했습니다.`n`n" + $_.Exception.Message) 'Error'
    exit 1
}
