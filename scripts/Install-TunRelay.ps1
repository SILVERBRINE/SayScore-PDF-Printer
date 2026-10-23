[CmdletBinding()]
param()

# Registers and starts the simple-mode relay (easy_output.tunrelay) as a SYSTEM
# scheduled task that also starts with Windows. Needs administrator rights.
# Only an installed copy (under Program Files) is accepted, because SYSTEM must
# not run code from a folder that ordinary users can change.

$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$task = 'SayScore PDF Relay'
# Wintun's kernel driver must match Windows, so ARM64 PCs run the relay on the
# bundled native ARM64 Python (the app itself stays on x64 Python).
$arm64 = [int](Get-CimInstance Win32_Processor | Select-Object -First 1).Architecture -eq 12
$arch = if ($arm64) { 'arm64' } else { 'amd64' }
$python = Join-Path $project ("vendor\python-{0}\3.13.9\pythonw.exe" -f $(if ($arm64) { 'arm64' } else { 'x64' }))

$protected = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ } |
    Where-Object { $project.StartsWith($_.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) }
if (-not $protected) { throw '가상 어댑터 방식은 설치 프로그램으로 설치한 SayScore PDF에서만 사용할 수 있습니다.' }
if (-not (Test-Path -LiteralPath $python)) { throw "Python 런타임이 없습니다: $python" }
if (-not (Test-Path -LiteralPath (Join-Path $project "vendor\wintun\$arch\wintun.dll"))) {
    throw 'wintun.dll이 없습니다. SayScore PDF를 다시 설치하세요.'
}

$action = New-ScheduledTaskAction -Execute $python -Argument '-m easy_output.tunrelay' -WorkingDirectory $project
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description 'SayScore PDF simple-mode printer relay' -Force | Out-Null
Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $task
