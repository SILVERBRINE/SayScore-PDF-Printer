[CmdletBinding()]
param([string]$Destination, [ValidateSet('amd64', 'arm64')][string]$Architecture = 'amd64')

# Recreates a bundled portable Python from python.org. The archive is the one
# the Python install manager uses; its binaries must carry a valid Python
# Software Foundation Authenticode signature.
# amd64 runs the app (with tkinter) on every PC; arm64 runs only the
# simple-mode relay on ARM64 PCs, whose Wintun driver must be native.

$ErrorActionPreference = 'Stop'
$folder = @{ amd64 = 'python-x64'; arm64 = 'python-arm64' }[$Architecture]
if (-not $Destination) { $Destination = Join-Path (Split-Path -Parent $PSScriptRoot) "vendor\$folder\3.13.9" }
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$url = "https://www.python.org/ftp/python/3.13.9/python-3.13.9-$Architecture.zip"

$Destination = [IO.Path]::GetFullPath($Destination)
$archive = Join-Path ([IO.Path]::GetTempPath()) ('python-' + [Guid]::NewGuid().ToString('N') + '.zip')
try {
    Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing
    Write-Host "python-3.13.9-$Architecture.zip SHA-256 $((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash)"
    if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Recurse -Force }
    Expand-Archive -LiteralPath $archive -DestinationPath $Destination
    foreach ($name in 'python.exe', 'pythonw.exe', 'python313.dll') {
        $signature = Get-AuthenticodeSignature -LiteralPath (Join-Path $Destination $name)
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            throw "$name is not signed by the Python Software Foundation ($($signature.Status))"
        }
    }
    $required = @('LICENSE.txt', 'DLLs\_ctypes.pyd')
    if ($Architecture -eq 'amd64') { $required += 'DLLs\_tkinter.pyd', 'Lib\tkinter\__init__.py' }
    foreach ($path in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $Destination $path))) { throw "Python runtime is missing $path" }
    }
} finally {
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
}
