[CmdletBinding()]
param([string]$InstallDirectory)

# Removes only what SayScore PDF created: its printer queues and their now-unused
# ports, and the SayScore-Relay WSL distribution. Printer drivers stay installed
# (other queues may use them) and converted PDFs in the user's folder are kept.

$ErrorActionPreference = 'Continue'
if (-not $InstallDirectory) { $InstallDirectory = Split-Path -Parent $PSScriptRoot }
$ownerComment = 'SayScore PDF local capture queue; created by Install-LocalPrinter.ps1 v2'
$distribution = 'SayScore-Relay'
$env:WSL_UTF8 = '1'

$root = [IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\') + '\'
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
    $registered = @(& wsl.exe --list --quiet 2>$null | ForEach-Object { $_.Trim([char]0, ' ') }) -contains $distribution
    if ($registered) {
        $version = (& wsl.exe -d $distribution --exec cat /etc/sayscore-relay-version 2>$null | Out-String).Trim()
        if ($version -match '^\d+-wsl$') {
            & wsl.exe --terminate $distribution 2>$null | Out-Null
            & wsl.exe --unregister $distribution 2>$null | Out-Null
        }
    }
}
$relayDirectory = Join-Path $env:LOCALAPPDATA 'SayScore PDF\relay-wsl'
if (Test-Path -LiteralPath $relayDirectory) { Remove-Item -LiteralPath $relayDirectory -Recurse -Force -ErrorAction SilentlyContinue }

$owned = @(Get-Printer -ErrorAction SilentlyContinue | Where-Object Comment -eq $ownerComment)
$ports = @($owned | ForEach-Object PortName | Sort-Object -Unique)
foreach ($queue in $owned) { Remove-Printer -Name $queue.Name -Confirm:$false -ErrorAction SilentlyContinue }
$inUse = @(Get-Printer -ErrorAction SilentlyContinue | ForEach-Object PortName)
foreach ($port in $ports) {
    $address = $null
    if ($port -notin $inUse -and [Net.IPAddress]::TryParse($port, [ref]$address)) {
        Remove-PrinterPort -Name $port -Confirm:$false -ErrorAction SilentlyContinue
    }
}
exit 0
