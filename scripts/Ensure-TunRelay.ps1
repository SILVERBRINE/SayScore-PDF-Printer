[CmdletBinding()]
param([Parameter(Mandatory)][string]$DataDirectory)

# Simple mode: makes sure the Wintun relay (easy_output.tunrelay) is running,
# starting it with an administrator prompt when it is not, and hands its
# addresses to the app through relay-runtime.json.

$ErrorActionPreference = 'Stop'
$stateFile = Join-Path $env:ProgramData 'SayScorePDF\tun-relay.json'

function Get-RelayState {
    try { $state = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
    # The relay rewrites this file every 10 seconds once its adapter is up. A test
    # connection would not work here: before the app listens, Windows Firewall's
    # stealth mode drops the connection instead of refusing it.
    $age = [DateTimeOffset]::Now.ToUnixTimeSeconds() - [int64]$state.updated
    if ($age -gt 30 -or -not $state.relay_address -or -not $state.capture_address) { return $null }
    $process = Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue
    if (-not $process -or $process.ProcessName -notlike 'python*') { return $null }
    return $state
}

$state = Get-RelayState
if (-not $state) {
    $install = Join-Path $PSScriptRoot 'Install-TunRelay.ps1'
    $process = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$install`"")
    if ($process.ExitCode -ne 0) { throw "간편 모드 중계를 설치하지 못했습니다 (코드 $($process.ExitCode))." }
    for ($attempt = 0; $attempt -lt 60 -and -not $state; $attempt++) {
        Start-Sleep -Seconds 1
        $state = Get-RelayState
    }
    if (-not $state) {
        $log = Join-Path $env:ProgramData 'SayScorePDF\tun-relay.log'
        $tail = if (Test-Path -LiteralPath $log) { (Get-Content -LiteralPath $log -Tail 5 -Encoding UTF8) -join "`n" }
                else { '중계 기록이 없습니다: 예약 작업 "SayScore PDF Relay"가 실행되지 않았습니다.' }
        throw "간편 모드 중계가 시작되지 않았습니다.`n`n$tail"
    }
}

$runtime = [ordered]@{ schema = 3; mode = 'tun'; capture_address = $state.capture_address
    relay_address = $state.relay_address; peer_address = $state.peer_address
    capture_raw_port = 19100; capture_snmp_port = 1161
    updated = [DateTimeOffset]::Now.ToUnixTimeSeconds() }
New-Item -ItemType Directory -Force -Path $DataDirectory | Out-Null
$path = Join-Path $DataDirectory 'relay-runtime.json'
[IO.File]::WriteAllText($path + '.tmp', ($runtime | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath ($path + '.tmp') -Destination $path -Force
[pscustomobject]@{ CaptureAddress = $state.capture_address; RelayAddress = $state.relay_address; Mode = 'tun' }
