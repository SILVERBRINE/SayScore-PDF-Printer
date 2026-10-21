[CmdletBinding()]
param()

$ErrorActionPreference = 'SilentlyContinue'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$rows = [Collections.Generic.List[object]]::new()
function Add-Check([string]$Name, [bool]$Ok, [string]$Detail) {
    $rows.Add([pscustomobject]@{ Item = $Name; Ready = $Ok; Detail = $Detail })
}

$os = Get-CimInstance Win32_OperatingSystem
$build = [int]$os.BuildNumber
$windowsReady = $build -ge 19045
Add-Check 'Windows' $windowsReady "$($os.Caption), build $build (minimum supported baseline: 19045)"

$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$architecture = switch ([int]$cpu.Architecture) { 9 { 'amd64' } 12 { 'arm64' } default { 'unsupported' } }
Add-Check 'CPU architecture' ($architecture -ne 'unsupported') $architecture
Add-Check 'Memory' ([math]::Round($os.TotalVisibleMemorySize / 1MB, 1) -ge 8) `
    ("{0:N1} GiB (Docker Desktop baseline: 8 GiB)" -f ($os.TotalVisibleMemorySize / 1MB))

$computer = Get-CimInstance Win32_ComputerSystem
$virtualization = [bool]($computer.HypervisorPresent -or
    ($cpu.VirtualizationFirmwareEnabled -and $cpu.SecondLevelAddressTranslationExtensions))
Add-Check 'Hardware virtualization' $virtualization $(if ($virtualization) { 'available' } else { 'not detected; enable virtualization in BIOS/UEFI' })

$wsl = Get-Command wsl.exe
$wslReady = $false
if ($wsl) {
    & wsl.exe --version 2>$null | Out-Null
    $wslReady = $LASTEXITCODE -eq 0
}
Add-Check 'WSL 2' $wslReady $(if ($wslReady) { 'installed' } else { 'not installed or too old' })

$docker = Get-Command docker.exe
$desktopCandidates = @(
    (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe')
)
$desktop = $desktopCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
Add-Check 'Docker Desktop' ([bool]($docker -and $desktop)) $(if ($desktop) { $desktop } else { 'not installed' })

$engineArchitecture = if ($docker) { (& docker info --format '{{.Architecture}}' 2>$null | Out-String).Trim().ToLowerInvariant() } else { '' }
$engineArchitecture = switch ($engineArchitecture) {
    'x86_64' { 'amd64' }
    'aarch64' { 'arm64' }
    default { $engineArchitecture }
}
Add-Check 'Docker Linux engine' ($engineArchitecture -in @('amd64', 'arm64')) `
    $(if ($engineArchitecture) { $engineArchitecture } else { 'not running; first-run setup/license acceptance may be required' })

$runtime = Join-Path $project 'vendor\python-x64\3.13.9\pythonw.exe'
$relayArchive = if ($architecture -ne 'unsupported') {
    Join-Path $project "vendor\relay-images\sayscore-network-relay-$architecture.tar"
} else { '' }
Add-Check 'Bundled app runtime' (Test-Path -LiteralPath $runtime -PathType Leaf) $runtime
Add-Check 'Bundled offline relay image' ($relayArchive -and (Test-Path -LiteralPath $relayArchive -PathType Leaf)) $relayArchive

$rows | Format-Table -AutoSize
if (@($rows | Where-Object { -not $_.Ready }).Count) { exit 1 }
