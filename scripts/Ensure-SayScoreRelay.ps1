[CmdletBinding()]
param([switch]$Check, [string]$DataDirectory)

# The relay runs in a dedicated, minimal WSL 2 distribution. Its address lives
# in the WSL VM and is never assigned to Windows, so the printer port still
# targets a separate network host. No Docker Desktop or general-purpose Linux
# distribution is installed.

$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $DataDirectory) { $DataDirectory = Join-Path $project 'data' }
$statePath = Join-Path $DataDirectory 'relay-runtime.json'
$distribution = 'SayScore-Relay'
$installDirectory = Join-Path $env:LOCALAPPDATA 'SayScore PDF\relay-wsl'
$relayVersion = '6-wsl'
$python = '/usr/local/bin/python3'
$relayScript = '/relay/network_relay.py'
$captureRawPort = 19100
$captureSnmpPort = 1161
$env:WSL_UTF8 = '1'

function Test-PrivateIPv4([string]$Value) {
    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($Value, [ref]$parsed) -or
        $parsed.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
        $parsed.ToString() -cne $Value) { return $false }
    $bytes = $parsed.GetAddressBytes()
    return $bytes[0] -eq 10 -or ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
        ($bytes[0] -eq 192 -and $bytes[1] -eq 168)
}

function Get-CaptureAddress {
    $routes = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
        Where-Object State -eq 'Alive' | Sort-Object @{ Expression = { $_.RouteMetric + $_.InterfaceMetric } })
    foreach ($route in $routes) {
        $adapter = Get-NetAdapter -InterfaceIndex $route.InterfaceIndex -ErrorAction SilentlyContinue
        if (-not $adapter -or $adapter.Status -ne 'Up' -or
            $adapter.InterfaceDescription -match 'Loopback|Hyper-V|WSL|Docker' -or
            $adapter.Name -match 'Loopback|vEthernet|WSL|Docker') { continue }
        $address = Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.AddressState -eq 'Preferred' -and (Test-PrivateIPv4 $_.IPAddress) } |
            Select-Object -First 1
        if ($address) { return $address.IPAddress }
    }
    throw '인터넷 경로가 있는 Wi-Fi/유선 어댑터의 사설 IPv4 주소를 찾지 못했습니다.'
}

function Invoke-Wsl([string[]]$Arguments, [switch]$AllowFailure) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $output = & wsl.exe @Arguments 2>&1 | Out-String }
    finally { $ErrorActionPreference = $previousPreference }
    $code = $LASTEXITCODE
    if ($code -ne 0 -and -not $AllowFailure) {
        throw "WSL 명령 실패 (코드 $code): wsl $($Arguments -join ' ')`n$($output.Trim())"
    }
    return [pscustomobject]@{ Code = $code; Output = $output.Trim() }
}

function Get-RelayArchitecture {
    switch ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()) {
        'X64' { return 'amd64' }
        'Arm64' { return 'arm64' }
        default { throw "지원하지 않는 Windows 아키텍처입니다: $_" }
    }
}

function Test-DistributionRegistered {
    $list = Invoke-Wsl @('--list', '--quiet') -AllowFailure
    if ($list.Code -ne 0) { return $false }
    return @($list.Output -split "`r?`n" | ForEach-Object { $_.Trim([char]0, ' ') }) -contains $distribution
}

function Install-RelayDistribution {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        throw 'WSL 2가 설치되어 있지 않습니다. "SayScore PDF.cmd"를 다시 실행해 필요한 Windows 기능을 설치하세요.'
    }
    $architecture = Get-RelayArchitecture
    $rootfs = Join-Path $project "vendor\relay-rootfs\sayscore-relay-$architecture.tar.gz"
    if (-not (Test-Path -LiteralPath $rootfs -PathType Leaf)) { throw "동봉된 중계 파일이 없습니다: $rootfs" }

    if (Test-DistributionRegistered) {
        $installed = Invoke-Wsl @('-d', $distribution, '--exec', 'cat', '/etc/sayscore-relay-version') -AllowFailure
        if ($installed.Code -ne 0 -or $installed.Output -notmatch '^\d+-wsl$') {
            throw "같은 이름의 다른 WSL 배포판이 있어 변경하지 않았습니다: $distribution"
        }
        if ($installed.Output -ceq $relayVersion) { return }
        Invoke-Wsl @('--terminate', $distribution) -AllowFailure | Out-Null
        Invoke-Wsl @('--unregister', $distribution) | Out-Null
    }
    New-Item -ItemType Directory -Force -Path $installDirectory | Out-Null
    Invoke-Wsl @('--import', $distribution, $installDirectory, $rootfs, '--version', '2') | Out-Null
    $installed = Invoke-Wsl @('-d', $distribution, '--exec', 'cat', '/etc/sayscore-relay-version')
    if ($installed.Output -cne $relayVersion) { throw '설치된 중계 배포판의 버전 검증에 실패했습니다.' }
}

function Start-Relay([string]$Target) {
    # pgrep -f matches the full command line as a regex; '.' stands in for spaces.
    $pattern = "$([regex]::Escape($relayScript)).--target-host.$([regex]::Escape($Target)).--target-raw-port.$captureRawPort.--target-snmp-port.$captureSnmpPort`$"
    $running = Invoke-Wsl @('-d', $distribution, '-u', 'root', '--exec', 'pgrep', '-f', $pattern) -AllowFailure
    if ($running.Code -eq 0) { return }
    Invoke-Wsl @('-d', $distribution, '-u', 'root', '--exec', 'pkill', '-f', $relayScript) -AllowFailure | Out-Null
    # This wsl.exe stays open for the relay's lifetime and keeps the WSL VM running.
    Start-Process -FilePath 'wsl.exe' -WindowStyle Hidden -ArgumentList @(
        '-d', $distribution, '-u', 'root', '--exec', $python, $relayScript,
        '--target-host', $Target, '--target-raw-port', "$captureRawPort", '--target-snmp-port', "$captureSnmpPort")
}

function Get-RelayAddress([string[]]$LocalAddresses) {
    $text = (Invoke-Wsl @('-d', $distribution, '--exec', 'ip', '-4', '-o', 'addr', 'show', 'eth0')).Output
    $choices = @([regex]::Matches($text, 'inet\s+(?<ip>\d+\.\d+\.\d+\.\d+)') |
        ForEach-Object { $_.Groups['ip'].Value } | Where-Object {
        $_ -and (Test-PrivateIPv4 $_) -and $_ -notin $LocalAddresses
    })
    if ($choices.Count -lt 1) {
        throw ('Windows와 분리된 WSL 2 사설 IPv4 주소를 찾지 못했습니다.' +
            ' .wslconfig에서 networkingMode=mirrored를 사용 중이면 nat로 바꿔야 합니다.')
    }
    return $choices[0]
}

$captureAddress = Get-CaptureAddress
if ($Check) {
    [pscustomobject]@{ CaptureAddress = $captureAddress; StatePath = $statePath; Mutated = $false }
    return
}

Install-RelayDistribution
Start-Relay $captureAddress

$localAddresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | ForEach-Object IPAddress)
$relayAddress = Get-RelayAddress $localAddresses
$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $client = [Net.Sockets.TcpClient]::new()
        $task = $client.ConnectAsync($relayAddress, 9100)
        if ($task.Wait(1000) -and $client.Connected) { $ready = $true; $client.Dispose(); break }
        $client.Dispose()
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw "프린터 중계 주소 ${relayAddress}:9100에 연결할 수 없습니다." }

$state = [ordered]@{ schema = 3; capture_address = $captureAddress; relay_address = $relayAddress
    capture_raw_port = $captureRawPort; capture_snmp_port = $captureSnmpPort
    distribution = $distribution; relay_version = $relayVersion
    updated = [DateTimeOffset]::Now.ToUnixTimeSeconds() }
$directory = Split-Path -Parent $statePath
New-Item -ItemType Directory -Force $directory | Out-Null
$temporary = $statePath + '.tmp'
[IO.File]::WriteAllText($temporary, ($state | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temporary -Destination $statePath -Force
[pscustomobject]@{ CaptureAddress = $captureAddress; RelayAddress = $relayAddress
    Distribution = $distribution; StatePath = $statePath; Mutated = $true }
