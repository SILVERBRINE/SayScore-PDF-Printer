[CmdletBinding()]
param(
    [string]$Destination = (Join-Path (Split-Path -Parent $PSScriptRoot) 'vendor')
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # The Windows PowerShell 5.1 progress bar slows downloads a lot.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$release = 'ghostpcl-10.08.0-win64'
$archiveName = "$release.zip"
$expectedHash = 'e3950c0b21ed687f0609ac5a6ec0da57ecb5160fb2f68832e3e9309a0b3491c7'
$downloadUrl = "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/$archiveName"
$Destination = [IO.Path]::GetFullPath($Destination)
[void][IO.Directory]::CreateDirectory($Destination)
$archive = Join-Path $Destination $archiveName
$target = Join-Path $Destination $release
$staging = Join-Path $Destination ('.ghostpcl-' + [Guid]::NewGuid().ToString('N'))

try {
    [void][IO.Directory]::CreateDirectory($staging)
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
        $download = Join-Path $staging $archiveName
        Write-Host "Downloading official Artifex GhostPCL 10.08.0 portable archive..."
        Invoke-WebRequest -Uri $downloadUrl -OutFile $download -UseBasicParsing
        if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
            throw 'Downloaded archive SHA-256 does not match the pinned release. No executable was installed.'
        }
        Move-Item -LiteralPath $download -Destination $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
        throw "Existing archive is unverified. It was preserved: $archive"
    }

    Expand-Archive -LiteralPath $archive -DestinationPath $staging
    $unpacked = Join-Path $staging $release
    foreach ($required in @('gpcl6win64.exe', 'gpcl6dll64.dll', 'LICENSE', 'COPYING', 'COPYING.AFPL', 'README.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $unpacked $required) -PathType Leaf)) {
            throw "Verified archive has an unexpected layout: missing $required"
        }
    }
    if (Test-Path -LiteralPath $target) {
        foreach ($file in (Get-ChildItem -LiteralPath $unpacked -File -Recurse)) {
            $relative = $file.FullName.Substring($unpacked.Length + 1)
            $existing = Join-Path $target $relative
            if (-not (Test-Path -LiteralPath $existing -PathType Leaf)) {
                throw "Existing distribution is incomplete; it was preserved: $existing"
            }
            if ((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ne
                (Get-FileHash -LiteralPath $existing -Algorithm SHA256).Hash) {
                throw "Existing distribution contains an unverified file; it was preserved: $existing"
            }
        }
        Write-Host 'Existing portable distribution matches the verified official archive.'
    } else {
        Move-Item -LiteralPath $unpacked -Destination $target
    }
    Write-Host 'Upstream LICENSE, COPYING, and COPYING.AFPL are preserved. Review them before redistribution or commercial font use.'
    Write-Output (Join-Path $target 'gpcl6win64.exe')
} finally {
    $resolvedStaging = [IO.Path]::GetFullPath($staging)
    if ((Split-Path -Parent $resolvedStaging) -eq $Destination -and
        (Split-Path -Leaf $resolvedStaging) -match '^\.ghostpcl-[0-9a-f]{32}$' -and
        (Test-Path -LiteralPath $resolvedStaging)) {
        Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
    }
}
