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
# wsl --exec runs without a shell or login PATH, so call busybox applets directly.
$busybox = '/bin/busybox'
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
    # WSL_UTF8 makes wsl.exe print UTF-8; decode it as such, not the console code page.
    $previousEncoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
        $output = & wsl.exe @Arguments 2>&1 | Out-String
    } finally {
        [Console]::OutputEncoding = $previousEncoding
        $ErrorActionPreference = $previousPreference
    }
    $code = $LASTEXITCODE
    if ($code -ne 0 -and $output -match 'WSL_E_WSL_OPTIONAL_COMPONENT_REQUIRED|HCS_E_HYPERV_NOT_INSTALLED') {
        throw ('WSL 2에 필요한 Windows 기능이 아직 켜지지 않았습니다. ' +
               'Windows를 재부팅한 뒤 SayScore PDF를 다시 실행하세요. ' +
               '재부팅 후에도 같으면 BIOS/UEFI에서 가상화가 켜져 있는지 확인하세요.')
    }
    if ($code -ne 0 -and -not $AllowFailure) {
        throw "WSL 명령 실패 (코드 $code): wsl $($Arguments -join ' ')`n$($output.Trim())"
    }
    return [pscustomobject]@{ Code = $code; Output = $output.Trim() }
}

function Get-RelayArchitecture {
    # WMI reports the real CPU. RuntimeInformation.OSArchitecture and
    # PROCESSOR_ARCHITECTURE report X64 when this process runs under x64
    # emulation on ARM64 Windows, which would import the wrong root filesystem.
    $cpu = Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1
    switch ([int]$cpu.Architecture) {
        9 { return 'amd64' }
        12 { return 'arm64' }
        default { throw "지원하지 않는 CPU 아키텍처입니다: $($cpu.Architecture)" }
    }
}

# Returns $null when not registered, otherwise whether SayScore registered it
# (identified by its install folder, which works even if it cannot start).
function Get-DistributionOwnership {
    $root = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
    if (-not (Test-Path -LiteralPath $root)) { return $null }
    foreach ($key in Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue) {
        $entry = Get-ItemProperty -LiteralPath $key.PSPath -ErrorAction SilentlyContinue
        if ($entry.DistributionName -cne $distribution) { continue }
        $base = ([string]$entry.BasePath) -replace '^\\\\\?\\', ''
        return [string]::Equals($base.TrimEnd('\'), $installDirectory.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)
    }
    return $null
}

function Test-DistributionCurrent([string]$Machine) {
    $installed = Invoke-Wsl @('-d', $distribution, '--exec', $busybox, 'cat', '/etc/sayscore-relay-version') -AllowFailure
    if ($installed.Code -ne 0 -or $installed.Output -cne $relayVersion) { return $false }
    $uname = Invoke-Wsl @('-d', $distribution, '--exec', $busybox, 'uname', '-m') -AllowFailure
    return $uname.Code -eq 0 -and $uname.Output -ceq $Machine
}

function Install-RelayDistribution {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        throw 'WSL 2가 설치되어 있지 않습니다. SayScore PDF를 다시 실행해 필요한 Windows 기능을 설치하세요.'
    }
    $architecture = Get-RelayArchitecture
    $machine = @{ amd64 = 'x86_64'; arm64 = 'aarch64' }[$architecture]
    $rootfs = Join-Path $project "vendor\relay-rootfs\sayscore-relay-$architecture.tar.gz"
    if (-not (Test-Path -LiteralPath $rootfs -PathType Leaf)) { throw "동봉된 중계 파일이 없습니다: $rootfs" }

    $owned = Get-DistributionOwnership
    if ($owned -eq $false) {
        throw "같은 이름의 다른 WSL 배포판이 있어 변경하지 않았습니다: $distribution"
    }
    if ($owned) {
        if (Test-DistributionCurrent $machine) { return }
        # Outdated or built for the other CPU architecture: replace it.
        Invoke-Wsl @('--terminate', $distribution) -AllowFailure | Out-Null
        Invoke-Wsl @('--unregister', $distribution) | Out-Null
    }
    New-Item -ItemType Directory -Force -Path $installDirectory | Out-Null
    Invoke-Wsl @('--import', $distribution, $installDirectory, $rootfs, '--version', '2') | Out-Null
    if (-not (Test-DistributionCurrent $machine)) { throw '설치된 중계 배포판의 버전 또는 CPU 아키텍처 검증에 실패했습니다.' }
}

function Start-Relay([string]$Target) {
    # pgrep -f matches the full command line as a regex; '.' stands in for spaces.
    $pattern = "$([regex]::Escape($relayScript)).--target-host.$([regex]::Escape($Target)).--target-raw-port.$captureRawPort.--target-snmp-port.$captureSnmpPort`$"
    $running = Invoke-Wsl @('-d', $distribution, '-u', 'root', '--exec', $busybox, 'pgrep', '-f', $pattern) -AllowFailure
    if ($running.Code -eq 0) { return }
    Invoke-Wsl @('-d', $distribution, '-u', 'root', '--exec', $busybox, 'pkill', '-f', $relayScript) -AllowFailure | Out-Null
    # This wsl.exe stays open for the relay's lifetime and keeps the WSL VM running.
    Start-Process -FilePath 'wsl.exe' -WindowStyle Hidden -ArgumentList @(
        '-d', $distribution, '-u', 'root', '--exec', $python, $relayScript,
        '--target-host', $Target, '--target-raw-port', "$captureRawPort", '--target-snmp-port', "$captureSnmpPort")
}

function Get-RelayAddress([string[]]$LocalAddresses) {
    $text = (Invoke-Wsl @('-d', $distribution, '--exec', $busybox, 'ip', '-4', '-o', 'addr', 'show', 'eth0')).Output
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
