[CmdletBinding()]
param([string]$Destination)

# Fetches wintun.dll (the WireGuard project's signed layer-3 TUN driver) for the
# relay used in simple mode. The archive is pinned by SHA-256 and each DLL must
# carry a valid WireGuard LLC signature. Only unmodified files are shipped,
# as the Wintun prebuilt-binaries license requires.

$ErrorActionPreference = 'Stop'
if (-not $Destination) { $Destination = Join-Path (Split-Path -Parent $PSScriptRoot) 'vendor\wintun' }
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$url = 'https://www.wintun.net/builds/wintun-0.14.1.zip'
$sha256 = '07C256185D6EE3652E09FA55C0B673E2624B565E02C4B9091C79CA7D2F24EF51'

$Destination = [IO.Path]::GetFullPath($Destination)
$work = Join-Path ([IO.Path]::GetTempPath()) ('sayscore-wintun-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Destination, $work | Out-Null
try {
    $archive = Join-Path $work 'wintun.zip'
    Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    if ($hash -ne $sha256) { throw "wintun: SHA-256 mismatch ($hash)" }
    Expand-Archive -LiteralPath $archive -DestinationPath $work
    foreach ($arch in 'amd64', 'arm64') {
        $target = Join-Path $Destination $arch
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        $dll = Join-Path $target 'wintun.dll'
        Copy-Item -LiteralPath (Join-Path $work "wintun\bin\$arch\wintun.dll") -Destination $dll -Force
        $signature = Get-AuthenticodeSignature -LiteralPath $dll
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'WireGuard LLC') {
            throw "wintun ${arch}: not validly signed by WireGuard LLC ($($signature.Status))"
        }
    }
    Copy-Item -LiteralPath (Join-Path $work 'wintun\LICENSE.txt') -Destination (Join-Path $Destination 'LICENSE.txt') -Force
    Write-Host "wintun 0.14.1: amd64, arm64"
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
