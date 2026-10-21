[CmdletBinding()]
param([switch]$Check)

$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$statePath = Join-Path $project 'data\relay-runtime.json'
$containerName = 'sayscore-network-relay'
$imageName = 'sayscore-network-relay:local'
$relayVersion = '5'
$captureRawPort = 19100
$captureSnmpPort = 1161

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

function Invoke-Docker([string[]]$Arguments) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $output = & docker @Arguments 2>&1 | Out-String }
    finally { $ErrorActionPreference = $previousPreference }
    if ($LASTEXITCODE -ne 0) { throw "Docker 명령 실패: docker $($Arguments -join ' ')`n$output" }
    return $output.Trim()
}

function Wait-Docker {
    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if (-not $docker) { throw 'Docker Desktop이 필요합니다. Docker Desktop을 설치한 뒤 다시 실행하세요.' }
    & docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { return }
    $desktop = @((Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe')) |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $desktop) { throw 'Docker Desktop 엔진이 실행 중이 아닙니다.' }
    Start-Process -FilePath $desktop -WindowStyle Hidden
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Seconds 2
        & docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return }
    }
    throw 'Docker Desktop 준비 시간이 초과되었습니다.'
}

function Get-RelayAddress([string[]]$LocalAddresses) {
    $text = & wsl.exe -d docker-desktop sh -lc 'ifconfig eth0' 2>$null | Out-String
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop WSL 네트워크 주소를 읽지 못했습니다.' }
    $choices = @([regex]::Matches($text, '(?:inet addr:|inet\s+)(?<ip>\d+\.\d+\.\d+\.\d+)') |
        ForEach-Object { $_.Groups['ip'].Value } | Where-Object {
        $_ -and (Test-PrivateIPv4 $_) -and $_ -notin $LocalAddresses
    })
    if ($choices.Count -lt 1) { throw 'Windows와 분리된 Docker Desktop 사설 IPv4 주소를 찾지 못했습니다.' }
    return $choices[0]
}

$captureAddress = Get-CaptureAddress
if ($Check) {
    [pscustomobject]@{ CaptureAddress = $captureAddress; StatePath = $statePath; Mutated = $false }
    return
}

Wait-Docker
$dockerArchitecture = (& docker info --format '{{.Architecture}}' 2>$null | Out-String).Trim().ToLowerInvariant()
$dockerArchitecture = switch ($dockerArchitecture) {
    'x86_64' { 'amd64' }
    'aarch64' { 'arm64' }
    default { $dockerArchitecture }
}
if ($dockerArchitecture -notin @('amd64', 'arm64')) {
    throw "지원하지 않는 Docker Linux 엔진 아키텍처입니다: $dockerArchitecture"
}
$bundledTag = "sayscore-network-relay:$dockerArchitecture"
$bundledImage = Join-Path $project "vendor\relay-images\sayscore-network-relay-$dockerArchitecture.tar"
$imageId = (& docker image ls -q $imageName 2>$null | Out-String).Trim()
$imageJson = if ($imageId) { & docker image inspect $imageName 2>$null | Out-String } else { '' }
$imageInfo = if ($imageJson) { @($imageJson | ConvertFrom-Json)[0] } else { $null }
$imageVersion = if ($imageInfo) { $imageInfo.Config.Labels.'sayscore.relay.version' } else { '' }
$imageArchitecture = if ($imageInfo) { [string]$imageInfo.Architecture } else { '' }
if ($imageVersion -cne $relayVersion -or $imageArchitecture -cne $dockerArchitecture) {
    if (Test-Path -LiteralPath $bundledImage -PathType Leaf) {
        Invoke-Docker @('load', '-i', $bundledImage) | Out-Null
        Invoke-Docker @('tag', $bundledTag, $imageName) | Out-Null
    } else {
        throw "이 PC용 오프라인 중계 이미지가 없습니다: $bundledImage"
    }
    $loaded = @((& docker image inspect $imageName 2>$null | Out-String) | ConvertFrom-Json)[0]
    if ($loaded.Architecture -cne $dockerArchitecture -or
        $loaded.Config.Labels.'sayscore.relay.version' -cne $relayVersion) {
        throw '동봉된 중계 이미지의 아키텍처 또는 버전 검증에 실패했습니다.'
    }
}

$containerNames = @(& docker ps -a --filter "name=$containerName" --format '{{.Names}}' 2>$null)
$containerExists = $containerName -in $containerNames
$containerJson = if ($containerExists) { & docker inspect $containerName 2>$null | Out-String } else { '' }
$containerInfo = if ($containerJson) { @($containerJson | ConvertFrom-Json)[0] } else { $null }
if ($containerInfo) {
    $owner = $containerInfo.Config.Labels.'sayscore.relay.owner'
    if ($owner -cne 'SayScore-PDF') { throw "동일한 Docker 컨테이너 이름이 다른 용도로 사용 중입니다: $containerName" }
    $target = $containerInfo.Config.Labels.'sayscore.relay.target'
    $version = $containerInfo.Config.Labels.'sayscore.relay.version'
    if ($target -cne $captureAddress -or $version -cne $relayVersion) {
        Invoke-Docker @('rm', '-f', $containerName) | Out-Null
        $containerInfo = $null
    }
}
if (-not $containerInfo) {
    Invoke-Docker @('run', '-d', '--restart', 'unless-stopped', '--name', $containerName,
        '--label', 'sayscore.relay.owner=SayScore-PDF', '--label', "sayscore.relay.target=$captureAddress",
        '--label', "sayscore.relay.version=$relayVersion", '-p', '9100:9100', '-p', '161:161/udp',
        $imageName, '--target-host', $captureAddress,
        '--target-raw-port', "$captureRawPort", '--target-snmp-port', "$captureSnmpPort") | Out-Null
} else {
    if (-not $containerInfo.State.Running) { Invoke-Docker @('start', $containerName) | Out-Null }
}

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

$state = [ordered]@{ schema = 2; capture_address = $captureAddress; relay_address = $relayAddress
    capture_raw_port = $captureRawPort; capture_snmp_port = $captureSnmpPort
    container = $containerName; image = $imageName; updated = [DateTimeOffset]::Now.ToUnixTimeSeconds() }
$directory = Split-Path -Parent $statePath
New-Item -ItemType Directory -Force $directory | Out-Null
$temporary = $statePath + '.tmp'
[IO.File]::WriteAllText($temporary, ($state | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temporary -Destination $statePath -Force
[pscustomobject]@{ CaptureAddress = $captureAddress; RelayAddress = $relayAddress
    Container = $containerName; StatePath = $statePath; Mutated = $true }
