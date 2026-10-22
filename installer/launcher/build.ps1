[CmdletBinding()]
param([string]$Output)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Output) { $Output = Join-Path $project 'SayScorePDF.exe' }
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }

# Stamp the exe's file properties with the app version from easy_output/__init__.py.
$version = (Select-String -LiteralPath (Join-Path $project 'easy_output\__init__.py') -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
$versionSource = Join-Path ([IO.Path]::GetTempPath()) "SayScoreLauncherVersion-$PID.cs"
[IO.File]::WriteAllText($versionSource, (
    "[assembly: System.Reflection.AssemblyVersion(`"$version`")]`n" +
    "[assembly: System.Reflection.AssemblyFileVersion(`"$version`")]`n" +
    "[assembly: System.Reflection.AssemblyInformationalVersion(`"$version`")]`n"))
try {
    & $csc /nologo /target:winexe /platform:anycpu /optimize+ /codepage:65001 `
        /reference:System.Windows.Forms.dll "/out:$Output" `
        "/win32icon:$(Join-Path $PSScriptRoot '..\..\easy_output\assets\sayscore.ico')" `
        (Join-Path $PSScriptRoot 'SayScoreLauncher.cs') $versionSource
    if ($LASTEXITCODE -ne 0) { throw "csc failed ($LASTEXITCODE)" }
} finally {
    Remove-Item -LiteralPath $versionSource -Force -ErrorAction SilentlyContinue
}
$Output
