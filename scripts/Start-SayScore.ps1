[CmdletBinding()]
param([switch]$Check, [switch]$NoShortcut, [switch]$Simple)

$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$entry = Join-Path $project 'start.pyw'

# Tells SayScorePDF.exe's startup window what is happening (no-op without it).
function Set-StartupStatus([string]$Text) {
    if ($env:SAYSCORE_PROGRESS) { try { [IO.File]::WriteAllText($env:SAYSCORE_PROGRESS, $Text) } catch { } }
}

function Show-Error([string]$Message) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [void][Windows.Forms.MessageBox]::Show($Message, 'SayScore PDF', 'OK', 'Error')
    } catch { Write-Host $Message -ForegroundColor Red }
}

function Test-PythonW([string]$Path) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $python = Join-Path (Split-Path -Parent $Path) 'python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { return $false }
    try {
        & $python -I -c 'import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

# Mirrors easy_output.app.default_data_dir: the app folder when writable (ZIP),
# otherwise the user's profile (installed under Program Files).
function Get-DataDirectory {
    $candidate = Join-Path $project 'data'
    try {
        New-Item -ItemType Directory -Force -Path $candidate -ErrorAction Stop | Out-Null
        $probe = Join-Path $candidate '.write-test'
        [IO.File]::WriteAllBytes($probe, [byte[]]@())
        Remove-Item -LiteralPath $probe -Force -ErrorAction Stop
        return $candidate
    } catch {
        $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { $env:USERPROFILE }
        return Join-Path $base 'SayScorePDF'
    }
}

function Find-PythonW {
    $bundled = Join-Path $project 'vendor\python-x64\3.13.9\pythonw.exe'
    if (Test-PythonW $bundled) { return $bundled }
    foreach ($name in @('pythonw.exe', 'pyw.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { continue }
        if ($name -eq 'pyw.exe') {
            $resolved = & (Join-Path (Split-Path -Parent $command.Source) 'py.exe') -3 -c 'import sys; print(sys.executable)' 2>$null
            if ($resolved) { $candidate = Join-Path (Split-Path -Parent $resolved) 'pythonw.exe' } else { continue }
        } else { $candidate = $command.Source }
        if ($candidate -notlike '*\WindowsApps\*' -and (Test-PythonW $candidate)) { return $candidate }
    }
    return $null
}

try {
    if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw "앱 시작 파일이 없습니다: $entry" }
    # Only the portable ZIP carries "downloaded from the internet" marks; the installed
    # copy has none, and scanning its ~2,500 files slowed every start.
    $installed = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ } |
        Where-Object { $project.StartsWith($_.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) }
    if (-not $Check -and -not $installed) {
        Set-StartupStatus '압축을 푼 파일을 확인하는 중…'
        Get-ChildItem -LiteralPath $project -Recurse -File -ErrorAction SilentlyContinue |
            Unblock-File -ErrorAction SilentlyContinue
    }
    $pythonw = Find-PythonW
    if (-not $pythonw) {
        throw ("실행에 필요한 Python 런타임을 찾지 못했습니다.`n`n" +
            "압축을 끝까지 풀었는지(vendor 폴더 포함) 확인하거나, python.org에서 Python 3.11 이상을 설치한 뒤 다시 실행하세요.")
    }
    if ($Check) {
        [pscustomobject]@{ PythonW = $pythonw; Entry = $entry; Started = $false }
        return
    }
    $data = Get-DataDirectory
    if (-not $Simple) {
        try {
            $relay = & (Join-Path $PSScriptRoot 'Ensure-SayScoreRelay.ps1') -DataDirectory $data
            if (-not $relay -or -not $relay.RelayAddress) { throw '프린터 네트워크 중계기를 준비하지 못했습니다.' }
        } catch {
            # Not saved as the user's choice: a pending restart or a BIOS change may fix this.
            Add-Type -AssemblyName System.Windows.Forms
            $answer = [Windows.Forms.MessageBox]::Show(
                ("WSL 방식을 시작하지 못했습니다.`n$($_.Exception.Message)`n`n" +
                 "이번에는 기본 방식(가상 어댑터)으로 시작할까요? 재부팅은 필요 없습니다."),
                'SayScore PDF', 'YesNo', 'Warning')
            if ($answer -ne 'Yes') { exit 2 }
            $Simple = $true
        }
    }
    if ($Simple) {
        # A Wintun adapter stands in for the WSL VM: the printer address is still not this PC's own.
        $relay = & (Join-Path $PSScriptRoot 'Ensure-TunRelay.ps1') -DataDirectory $data
        if (-not $relay -or -not $relay.RelayAddress) { throw '가상 어댑터 중계를 준비하지 못했습니다.' }
    }
    if (-not $NoShortcut) {
        try {
            $desktop = [Environment]::GetFolderPath('Desktop')
            $link = Join-Path $desktop 'SayScore PDF.lnk'
            if ($desktop) {
                $shell = New-Object -ComObject WScript.Shell
                $shortcut = $shell.CreateShortcut($link)
                $owned = -not (Test-Path -LiteralPath $link) -or
                    $shortcut.Description -eq 'SayScore PDF - 인쇄하면 PDF로 저장'
                if (-not $owned) { throw '같은 이름의 사용자 바로가기가 있어 변경하지 않았습니다.' }
                $shortcut.TargetPath = (Get-Command powershell.exe -ErrorAction Stop).Source
                $shortcut.Arguments = ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' +
                    (Join-Path $PSScriptRoot 'Start-SayScore.ps1') + '" -NoShortcut')
                $shortcut.WorkingDirectory = $project
                $shortcut.IconLocation = (Join-Path (Split-Path -Parent $pythonw) 'pythonw.exe') + ',0'
                $shortcut.Description = 'SayScore PDF - 인쇄하면 PDF로 저장'
                $shortcut.WindowStyle = 7
                $shortcut.Save()
            }
        } catch { }  # A missing shortcut never blocks the app.
    }
    Set-StartupStatus '앱 화면을 여는 중…'
    Start-Process -FilePath $pythonw -ArgumentList ('"' + $entry + '" --data "' + $data.TrimEnd('\') + '"') `
        -WorkingDirectory $project -ErrorAction Stop
} catch {
    Show-Error ('SayScore PDF를 시작하지 못했습니다.' + "`n`n" + $_.Exception.Message)
    exit 1
}
