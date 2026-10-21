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
Add-Check 'Memory' ([math]::Round($os.TotalVisibleMemorySize / 1MB, 1) -ge 4) `
    ("{0:N1} GiB (minimum: 4 GiB)" -f ($os.TotalVisibleMemorySize / 1MB))

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

$wslConfig = Join-Path $env:USERPROFILE '.wslconfig'
$mirrored = (Test-Path -LiteralPath $wslConfig) -and
    [bool](Select-String -LiteralPath $wslConfig -Pattern '^\s*networkingMode\s*=\s*mirrored' -Quiet)
Add-Check 'WSL NAT networking' (-not $mirrored) $(if ($mirrored) { "networkingMode=mirrored in $wslConfig; the relay needs nat" } else { 'nat (default)' })

$runtime = Join-Path $project 'vendor\python-x64\3.13.9\pythonw.exe'
$relayArchive = if ($architecture -ne 'unsupported') {
    Join-Path $project "vendor\relay-rootfs\sayscore-relay-$architecture.tar.gz"
} else { '' }
Add-Check 'Bundled app runtime' (Test-Path -LiteralPath $runtime -PathType Leaf) $runtime
Add-Check 'Bundled offline relay' ($relayArchive -and (Test-Path -LiteralPath $relayArchive -PathType Leaf)) $relayArchive

$rows | Format-Table -AutoSize
if (@($rows | Where-Object { -not $_.Ready }).Count) { exit 1 }
