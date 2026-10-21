[CmdletBinding()]
param([string]$Destination)

# Recreates the bundled portable Python (with tkinter) from python.org. The
# archive is the one the Python install manager uses; its binaries must carry a
# valid Python Software Foundation Authenticode signature.

$ErrorActionPreference = 'Stop'
if (-not $Destination) { $Destination = Join-Path (Split-Path -Parent $PSScriptRoot) 'vendor\python-x64\3.13.9' }
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$url = 'https://www.python.org/ftp/python/3.13.9/python-3.13.9-amd64.zip'

$Destination = [IO.Path]::GetFullPath($Destination)
$archive = Join-Path ([IO.Path]::GetTempPath()) ('python-' + [Guid]::NewGuid().ToString('N') + '.zip')
try {
    Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing
    Write-Host "python-3.13.9-amd64.zip SHA-256 $((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash)"
    if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Recurse -Force }
    Expand-Archive -LiteralPath $archive -DestinationPath $Destination
    foreach ($name in 'python.exe', 'pythonw.exe', 'python313.dll') {
        $signature = Get-AuthenticodeSignature -LiteralPath (Join-Path $Destination $name)
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            throw "$name is not signed by the Python Software Foundation ($($signature.Status))"
        }
    }
    foreach ($required in 'LICENSE.txt', 'DLLs\_tkinter.pyd', 'Lib\tkinter\__init__.py') {
        if (-not (Test-Path -LiteralPath (Join-Path $Destination $required))) { throw "Python runtime is missing $required" }
    }
} finally {
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
}
