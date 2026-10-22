[CmdletBinding()]
param([Parameter(Mandatory)][string]$DataDirectory)

# Simple mode: makes sure the Wintun relay (easy_output.tunrelay) is running,
# starting it with an administrator prompt when it is not, and hands its
# addresses to the app through relay-runtime.json.

$ErrorActionPreference = 'Stop'
$stateFile = Join-Path $env:ProgramData 'SayScorePDF\tun-relay.json'

function Get-RelayState {
    try { $state = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
    $age = [DateTimeOffset]::Now.ToUnixTimeSeconds() - [int64]$state.updated
    if ($age -gt 60 -or -not $state.relay_address -or -not $state.capture_address) { return $null }
    # The relay turns a connection to the printer address into one to the app's
    # port, so even "refused" (app not started yet) proves the relay is working.
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync([string]$state.relay_address, 9100)
        try { [void]$task.Wait(2000) } catch { }
        $refused = $task.Exception -and ($task.Exception.InnerException -is [Net.Sockets.SocketException]) -and
            $task.Exception.InnerException.SocketErrorCode -eq 'ConnectionRefused'
        if ($client.Connected -or $refused) { return $state }
    } finally { $client.Dispose() }
    return $null
}

$state = Get-RelayState
if (-not $state) {
    $install = Join-Path $PSScriptRoot 'Install-TunRelay.ps1'
    $process = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$install`"")
    if ($process.ExitCode -ne 0) { throw "간편 모드 중계를 설치하지 못했습니다 (코드 $($process.ExitCode))." }
    for ($attempt = 0; $attempt -lt 30 -and -not $state; $attempt++) {
        Start-Sleep -Seconds 1
        $state = Get-RelayState
    }
    if (-not $state) {
        $log = Join-Path $env:ProgramData 'SayScorePDF\tun-relay.log'
        $tail = if (Test-Path -LiteralPath $log) { (Get-Content -LiteralPath $log -Tail 3) -join "`n" } else { '' }
        throw "간편 모드 중계가 시작되지 않았습니다.`n$tail"
    }
}

$runtime = [ordered]@{ schema = 3; mode = 'tun'; capture_address = $state.capture_address
    relay_address = $state.relay_address; capture_raw_port = 19100; capture_snmp_port = 1161
    updated = [DateTimeOffset]::Now.ToUnixTimeSeconds() }
New-Item -ItemType Directory -Force -Path $DataDirectory | Out-Null
$path = Join-Path $DataDirectory 'relay-runtime.json'
[IO.File]::WriteAllText($path + '.tmp', ($runtime | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath ($path + '.tmp') -Destination $path -Force
[pscustomobject]@{ CaptureAddress = $state.capture_address; RelayAddress = $state.relay_address; Mode = 'tun' }
