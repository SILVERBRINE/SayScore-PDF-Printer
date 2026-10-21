[CmdletBinding()]
param([switch]$Check, [switch]$NoShortcut)

$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$entry = Join-Path $project 'start.pyw'

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
    if (-not $Check) {
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
    $relay = & (Join-Path $PSScriptRoot 'Ensure-SayScoreRelay.ps1') -DataDirectory $data
    if (-not $relay -or -not $relay.RelayAddress) {
        throw '프린터 네트워크 중계기를 준비하지 못했습니다.'
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
    Start-Process -FilePath $pythonw -ArgumentList ('"' + $entry + '" --data "' + $data.TrimEnd('\') + '"') `
        -WorkingDirectory $project -ErrorAction Stop
} catch {
    Show-Error ('SayScore PDF를 시작하지 못했습니다.' + "`n`n" + $_.Exception.Message)
    exit 1
}
