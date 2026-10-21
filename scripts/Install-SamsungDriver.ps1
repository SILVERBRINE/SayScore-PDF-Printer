[CmdletBinding()]
param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))

function Get-NativeOSArchitecture {
    if (-not ('SayScoreDriver.NativeSystem' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace SayScoreDriver {
    public static class NativeSystem {
        [DllImport("kernel32.dll")]
        public static extern IntPtr GetCurrentProcess();
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool IsWow64Process2(IntPtr process, out ushort processMachine, out ushort nativeMachine);
        public static ushort Architecture() {
            ushort process, native;
            if (!IsWow64Process2(GetCurrentProcess(), out process, out native))
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            return native;
        }
    }
}
'@ -ErrorAction Stop
    }
    $machine = [SayScoreDriver.NativeSystem]::Architecture()
    if ($machine -eq 0x8664) { return 'X64' }
    if ($machine -eq 0xaa64) { return 'Arm64' }
    return "Other ($machine)"
}

$architecture = Get-NativeOSArchitecture
$package = switch ($architecture) {
    'X64' { @{ Name = 'Samsung X4305 Series'; Environment = 'Windows x64'; Version = 3
               Inf = 'vendor\drivers\samsung-x4305-x64\us015.inf'; Catalog = 'vendor\drivers\samsung-x4305-x64\us015.cat' } }
    'Arm64' { @{ Name = 'Samsung CLX-9252 9352 Series PCL6 Class Driver'; Environment = 'Windows ARM64'; Version = 4
                 Inf = 'vendor\drivers\samsung-woa-arm64\prnsacl1.inf'; Catalog = 'vendor\drivers\samsung-woa-arm64\prnsacl1.cat' } }
    default { throw "Samsung 드라이버를 지원하지 않는 Windows입니다: $architecture" }
}
$registryKey = "HKLM:\SYSTEM\CurrentControlSet\Control\Print\Environments\$($package.Environment)\Drivers\Version-$($package.Version)\$($package.Name)"
if (Test-Path -LiteralPath $registryKey) {
    Write-Host "Already registered: $($package.Name) ($($package.Environment))"
    Write-Output $package.Name
    return
}
$inf = Join-Path $project $package.Inf
$catalog = Join-Path $project $package.Catalog
if (-not (Test-Path -LiteralPath $inf -PathType Leaf) -or -not (Test-Path -LiteralPath $catalog -PathType Leaf)) {
    throw "동봉된 Samsung 드라이버 파일이 없습니다: $inf"
}
$signature = Get-AuthenticodeSignature -LiteralPath $catalog
if ($signature.Status -ne 'Valid' -or
    $signature.SignerCertificate.Subject -notlike 'CN=Microsoft Windows Hardware Compatibility Publisher,*') {
    throw "Samsung 드라이버 카탈로그 서명을 확인하지 못했습니다 ($($signature.Status)). 설치하지 않았습니다."
}
if (-not $Apply) {
    Write-Host "Dry run: would stage $inf and register $($package.Name) ($($package.Environment))."
    Write-Output $package.Name
    return
}
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw '-Apply requires an Administrator PowerShell window.'
}
$pnputil = Join-Path $env:windir 'System32\pnputil.exe'
if (-not (Test-Path -LiteralPath $pnputil)) { $pnputil = Join-Path $env:windir 'Sysnative\pnputil.exe' }
$log = & $pnputil /add-driver $inf 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 3010) {
    throw "pnputil이 Samsung 드라이버 패키지를 추가하지 못했습니다 (코드 $LASTEXITCODE).`n$log"
}
Import-Module PrintManagement -ErrorAction Stop
Add-PrinterDriver -Name $package.Name -PrinterEnvironment $package.Environment -ErrorAction Stop
if (-not (Test-Path -LiteralPath $registryKey)) { throw "드라이버 등록을 확인하지 못했습니다: $($package.Name)" }
Write-Host "Registered bundled Samsung driver: $($package.Name) ($($package.Environment)); no queue changed."
Write-Output $package.Name
