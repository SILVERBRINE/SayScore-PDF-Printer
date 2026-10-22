[CmdletBinding()]
param([string]$Output)

$ErrorActionPreference = 'Stop'
if (-not $Output) { $Output = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'SayScorePDF.exe' }
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
& $csc /nologo /target:winexe /platform:anycpu /optimize+ /codepage:65001 `
    /reference:System.Windows.Forms.dll "/out:$Output" `
    "/win32icon:$(Join-Path $PSScriptRoot '..\..\easy_output\assets\sayscore.ico')" (Join-Path $PSScriptRoot 'SayScoreLauncher.cs')
if ($LASTEXITCODE -ne 0) { throw "csc failed ($LASTEXITCODE)" }
$Output
