[CmdletBinding()]
param([string]$Destination)

# Recreates vendor\drivers from Samsung's official archives listed in
# vendor-sources\drivers-SOURCES.md. Each archive is pinned by SHA-256 and each
# driver catalog must carry a valid Microsoft WHQL signature.

$ErrorActionPreference = 'Stop'
if (-not $Destination) { $Destination = Join-Path (Split-Path -Parent $PSScriptRoot) 'vendor\drivers' }
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$sources = @(
    @{ Folder = 'samsung-x4305-x64'; Inf = 'us015.inf'; Catalog = 'us015.cat'; ExtraFile = 'VERSION.VER'
       Url = 'https://downloadcenter.samsung.com/content/DR/202108/20210812095017792/X4305_Series_WIN_Printer_V3.00.15.00.01_CDV1.05.zip'
       Sha256 = '751DF2D7AE5ED3BA5F671353F190A0DB648106BA249AE1CD9E9176A20CF4B45B' },
    @{ Folder = 'samsung-woa-arm64'; Inf = 'prnsacl1.inf'; Catalog = 'prnsacl1.cat'; ExtraFile = $null
       Url = 'https://downloadcenter.samsung.com/content/DR/202501/20250123084813115/Add_Driver_for_WOA.zip'
       Sha256 = '085866343BD717816E54847E9089A4D241B96A7C39C04B0B7DC1D500F4D06042' }
)

$Destination = [IO.Path]::GetFullPath($Destination)
$work = Join-Path ([IO.Path]::GetTempPath()) ('sayscore-drivers-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Destination, $work | Out-Null
try {
    foreach ($source in $sources) {
        $archive = Join-Path $work ($source.Folder + '.zip')
        Invoke-WebRequest -Uri $source.Url -OutFile $archive -UseBasicParsing
        $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
        if ($hash -ne $source.Sha256) { throw "$($source.Folder): SHA-256 mismatch ($hash)" }
        $unpacked = Join-Path $work $source.Folder
        Expand-Archive -LiteralPath $archive -DestinationPath $unpacked

        # The driver folder is the one holding the INF; the x64 kit also needs
        # VERSION.VER from the folder above it (Printer\UPD + Printer\VERSION.VER).
        $inf = @(Get-ChildItem -LiteralPath $unpacked -Recurse -File -Filter $source.Inf)
        if ($inf.Count -ne 1) { throw "$($source.Folder): expected one $($source.Inf), found $($inf.Count)" }
        $driverRoot = $inf[0].DirectoryName
        $target = Join-Path $Destination $source.Folder
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
        Copy-Item -LiteralPath $driverRoot -Destination $target -Recurse
        if ($source.ExtraFile) {
            $extra = Join-Path (Split-Path -Parent $driverRoot) $source.ExtraFile
            Copy-Item -LiteralPath $extra -Destination $target
        }
        $signature = Get-AuthenticodeSignature -LiteralPath (Join-Path $target $source.Catalog)
        if ($signature.Status -ne 'Valid' -or
            $signature.SignerCertificate.Subject -notmatch 'Microsoft Windows Hardware Compatibility Publisher') {
            throw "$($source.Folder): catalog signature is not a valid WHQL signature ($($signature.Status))"
        }
        Write-Host "$($source.Folder): $((Get-ChildItem -LiteralPath $target -Recurse -File).Count) files"
    }
    Copy-Item -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'vendor-sources\drivers-SOURCES.md') `
        -Destination (Join-Path $Destination 'SOURCES.md')
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
