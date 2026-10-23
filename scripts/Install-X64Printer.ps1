[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param([switch]$Apply, [string]$CaptureAddress, [string]$PrinterAddress,
    [ValidateSet('Samsung X4305 Series')][string]$DriverName = 'Samsung X4305 Series',
    [string]$QueueName = 'SayScore PDF', [string]$PreviousQueueName, [switch]$Bidirectional)
$ErrorActionPreference = 'Stop'
function Test-QueueName([string]$Name) {
    return -not ([string]::IsNullOrWhiteSpace($Name) -or $Name.Length -gt 220 -or $Name -match '[!,\\/]')
}
if (-not (Test-QueueName $QueueName)) { throw 'QueueName must be a valid Windows printer name (no ! , \ / and not empty).' }
$queueName = $QueueName
$sourceQueueName = if (-not [string]::IsNullOrWhiteSpace($PreviousQueueName)) { $PreviousQueueName } else { $QueueName }
if (-not (Test-QueueName $sourceQueueName)) { throw 'PreviousQueueName is not a valid printer name.' }
$renameQueue = $sourceQueueName -cne $queueName
$ownerComment = 'SayScore PDF local capture queue; created by Install-LocalPrinter.ps1 v2'
$printRoot = 'HKLM:\SYSTEM\CurrentControlSet\Control\Print'
$queueKey = "$printRoot\Printers\$queueName"
$sourceQueueKey = "$printRoot\Printers\$sourceQueueName"
$driverKey = "$printRoot\Environments\Windows x64\Drivers\Version-3\$driverName"

function Get-NativeOSArchitecture {
    if (-not ('SayScoreX64.NativeSystem' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace SayScoreX64 {
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
    $architecture = [SayScoreX64.NativeSystem]::Architecture()
    if ($architecture -eq 0x8664) { return 'X64' }
    if ($architecture -eq 0xaa64) { return 'Arm64' }
    return "Other ($architecture)"
}

function Assert-NativeX64([string]$Architecture) {
    if ($Architecture -cne 'X64') {
        throw "이 설치는 Intel/AMD x64 Windows 전용입니다. 실제 OS: $Architecture. ARM PC에서 x64 앱을 실행해도 x64 프린터 드라이버를 사용할 수 없습니다."
    }
}

function Read-Value([object]$Item, [string]$Name) {
    if ($null -ne $Item -and $null -ne $Item.PSObject.Properties[$Name]) { return $Item.PSObject.Properties[$Name].Value }
    return $null
}

function Test-PrivateIPv4([string]$Address) {
    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($Address, [ref]$parsed) -or
        $parsed.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or $parsed.ToString() -cne $Address) { return $false }
    $bytes = $parsed.GetAddressBytes()
    return ($bytes[0] -eq 10 -or ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
        ($bytes[0] -eq 192 -and $bytes[1] -eq 168))
}

function Resolve-CaptureAddress([string]$Requested) {
    if ($Requested -and -not (Test-PrivateIPv4 $Requested)) { throw 'CaptureAddress must be a canonical RFC1918 IPv4 address.' }
    $adapters = @(Get-NetAdapter -ErrorAction Stop | Where-Object { $_.Status -eq 'Up' })
    $eligible = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | Where-Object {
        $entry = $_
        (Test-PrivateIPv4 $entry.IPAddress) -and $entry.AddressState -eq 'Preferred' -and
        @($adapters | Where-Object { $_.ifIndex -eq $entry.InterfaceIndex -and
            $_.Name -notmatch 'Loopback' -and $_.InterfaceDescription -notmatch 'Loopback' }).Count -eq 1
    })
    if ($Requested) { $eligible = @($eligible | Where-Object { $_.IPAddress -ceq $Requested }) }
    if ($eligible.Count -ne 1) { throw "Exactly one assigned, Preferred private IPv4 on an Up adapter is required (found $($eligible.Count)); specify -CaptureAddress." }
    return $eligible[0]
}

function Assert-Driver {
    if (-not (Test-Path -LiteralPath $driverKey)) {
        throw "실제 Windows x64 v3 드라이버 '$driverName'가 등록되어 있지 않습니다. 먼저 Samsung/HP 공식 x64 패키지로 이 정확한 드라이버를 설치한 뒤 다시 실행하세요. 이 스크립트는 드라이버를 설치하거나 이름을 바꾸지 않습니다."
    }
    $driver = Get-ItemProperty -LiteralPath $driverKey -ErrorAction Stop
    if ((Read-Value $driver 'Version') -ne 3 -or -not (Read-Value $driver 'Driver')) {
        throw 'Registered driver is not the exact usable Windows x64 version-3 Samsung driver.'
    }
}

function Assert-Port([string]$Name, [string]$Address) {
    $port = Get-ItemProperty -LiteralPath "$printRoot\Monitors\Standard TCP/IP Port\Ports\$Name" -ErrorAction Stop
    $hostValue = Read-Value $port 'HostName'
    $ip = Read-Value $port 'IPAddress'
    if (-not $hostValue) { $hostValue = $ip }
    if ($Name -cne $Address -or $hostValue -cne $Address -or ($ip -and $ip -cne $Address) -or
        (Read-Value $port 'PortNumber') -ne 9100 -or (Read-Value $port 'Protocol') -ne 1) {
        throw 'Port collision or unexpected numeric-IP RAW 9100 settings.'
    }
}

function Get-PortSnmpEnabled([string]$Name) {
    $port = Get-ItemProperty -LiteralPath "$printRoot\Monitors\Standard TCP/IP Port\Ports\$Name" -ErrorAction Stop
    return [int]((Read-Value $port 'SNMP Enabled')) -ne 0
}

function Set-OwnedPortBidirectional([string]$Name, [bool]$Enabled) {
    $key = "$printRoot\Monitors\Standard TCP/IP Port\Ports\$Name"
    Set-ItemProperty -LiteralPath $key -Name 'SNMP Enabled' -Value ([int][bool]$Enabled) -Type DWord -ErrorAction Stop
    if ($Enabled) {
        Set-ItemProperty -LiteralPath $key -Name 'SNMP Community' -Value 'public' -Type String -ErrorAction Stop
        Set-ItemProperty -LiteralPath $key -Name 'SNMP Index' -Value 1 -Type DWord -ErrorAction Stop
    }
    Restart-Service -Name Spooler -Force -ErrorAction Stop
}

function Assert-Queue([string]$Port, [string]$Key = $queueKey) {
    $queue = Get-ItemProperty -LiteralPath $Key -ErrorAction Stop
    if ((Read-Value $queue 'Printer Driver') -cne $driverName -or
        (Read-Value $queue 'Port') -cne $Port -or (Read-Value $queue 'Description') -cne $ownerComment) {
        throw 'Queue collision: exact Samsung driver, port, and v2 ownership marker are required.'
    }
}

Assert-NativeX64 (Get-NativeOSArchitecture)
Assert-Driver
$endpoint = Resolve-CaptureAddress $CaptureAddress
$captureHost = $endpoint.IPAddress
if ($PrinterAddress -and -not (Test-PrivateIPv4 $PrinterAddress)) { throw 'PrinterAddress must be a canonical RFC1918 IPv4 address.' }
$hostAddress = if ($PrinterAddress) { $PrinterAddress } else { $captureHost }
if ($PrinterAddress -and $hostAddress -ceq $captureHost) { throw 'PrinterAddress must use the separate relay network address, not CaptureAddress.' }
$portName = $hostAddress
$portKey = "$printRoot\Monitors\Standard TCP/IP Port\Ports\$portName"
$queueExists = Test-Path -LiteralPath $sourceQueueKey
$portExists = Test-Path -LiteralPath $portKey
if ($renameQueue -and $queueExists -and (Test-Path -LiteralPath $queueKey)) {
    throw "The target queue name '$queueName' already exists; refusing to rename onto it."
}
if ($renameQueue -and -not $queueExists) { throw "No owned queue named '$sourceQueueName' was found to rename." }
$previousPort = $null
$adoptPort = $false
if ($queueExists) {
    $previousPort = Read-Value (Get-ItemProperty -LiteralPath $sourceQueueKey -ErrorAction Stop) 'Port'
    Assert-Queue $previousPort $sourceQueueKey
    if (-not (Test-PrivateIPv4 $previousPort)) { throw 'Owned queue has an unexpected port identity.' }
    Assert-Port $previousPort $previousPort
    if ($previousPort -cne $portName -and $portExists) {
        # Switching relay modes back and forth leaves the earlier port behind (old
        # ports are preserved). Reuse it only if it is exactly what this script
        # would create and no other printer uses it.
        Assert-Port $portName $hostAddress
        if (@(Get-Printer -ErrorAction Stop | Where-Object { $_.PortName -ceq $portName }).Count) {
            throw 'Target numeric port already exists and is used by another printer; refusing adoption.'
        }
        $adoptPort = $true
    }
} elseif ($portExists) { Assert-Port $portName $hostAddress; $adoptPort = $true }
$migrate = $queueExists -and $previousPort -cne $portName
$changeBidi = ($queueExists -and -not $migrate -and ((Get-PortSnmpEnabled $previousPort) -ne [bool]$Bidirectional)) -or
    ($adoptPort -and ((Get-PortSnmpEnabled $portName) -ne [bool]$Bidirectional))
$plan = [pscustomobject]@{
    Mode = $(if ($Apply -and -not $WhatIfPreference) { 'Apply requested' } else { 'Dry run; no changes' })
    NativeOS = 'Intel/AMD Windows x64'; Queue = $queueName; Driver = $driverName
    DriverEnvironment = 'Windows x64'; DriverVersion = 3; DriverRegistration = 'Already registered; no installation'
    CaptureAddress = $captureHost; PortName = $portName; HostAddress = $hostAddress; PortNumber = 9100; Protocol = 'RAW'; SNMPEnabled = [bool]$Bidirectional
    OwnershipComment = $ownerComment; PreviousPort = $previousPort
    RenameFrom = $(if ($renameQueue) { $sourceQueueName } else { $null })
    Action = $(if ($renameQueue -and $migrate) { "Rename owned queue '$sourceQueueName' to '$queueName' and move to new port" } elseif ($renameQueue) { "Rename only the owned queue '$sourceQueueName' to '$queueName'" } elseif ($migrate -and $adoptPort) { 'Move only owned queue onto the matching unused port; preserve old port' } elseif ($migrate) { 'Create new port; update only owned queue; preserve old port' } elseif ($adoptPort) { 'Adopt the matching existing port and create the owned queue on it' } elseif ($changeBidi) { "Update only the owned port's SNMP/bidirectional setting" } elseif ($queueExists) { 'Already matching; no changes' } else { 'Create separate port and queue' })
    WebsiteValidation = 'Unverified; genuine driver registration is not proof of site support'
}
$plan | Format-List | Out-Host
if (-not $Apply -or $WhatIfPreference) {
    $printerArgument = $(if ($PrinterAddress) { " -PrinterAddress $hostAddress" } else { '' })
    Write-Host "적용: 관리자 PowerShell에서 .\scripts\Install-X64Printer.ps1 -CaptureAddress $captureHost$printerArgument -Apply"
    return
}
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw '-Apply requires an Administrator PowerShell window.' }
Import-Module PrintManagement -ErrorAction Stop
Assert-NativeX64 (Get-NativeOSArchitecture)
Assert-Driver
$currentEndpoint = Resolve-CaptureAddress $captureHost
if ($currentEndpoint.InterfaceIndex -ne $endpoint.InterfaceIndex) { throw 'Address moved to another adapter; review a fresh plan.' }
$liveDrivers = @(Get-PrinterDriver -ErrorAction Stop | Where-Object { $_.Name -ceq $driverName -and $_.PrinterEnvironment -ceq 'Windows x64' -and $_.MajorVersion -eq 3 })
if ($liveDrivers.Count -ne 1) { throw 'Exact live Windows x64 v3 Samsung driver was not found.' }
$liveQueues = @(Get-Printer -ErrorAction Stop | Where-Object { $_.Name -ceq $sourceQueueName })
$livePorts = @(Get-PrinterPort -ErrorAction Stop | Where-Object { $_.Name -ceq $portName })
if ($queueExists) {
    Assert-Queue $previousPort $sourceQueueKey
    Assert-Port $previousPort $previousPort
    if ($liveQueues.Count -ne 1 -or $liveQueues[0].DriverName -cne $driverName -or
        $liveQueues[0].PortName -cne $previousPort -or $liveQueues[0].Comment -cne $ownerComment) { throw 'Live owned queue differs from plan.' }
    if ($renameQueue -and @(Get-Printer -ErrorAction Stop | Where-Object { $_.Name -ceq $queueName }).Count) {
        throw "The target queue name '$queueName' became occupied. No changes made."
    }
    if (-not $migrate -and -not $renameQueue -and -not $changeBidi) { return }
} elseif ($liveQueues.Count -or (Test-Path -LiteralPath $queueKey)) { throw 'Queue name became occupied.' }
$needNewPort = -not $adoptPort -and (-not $queueExists -or $migrate)
if ($needNewPort -and ($livePorts.Count -or (Test-Path -LiteralPath $portKey))) { throw 'Port name became occupied; no existing port will be adopted.' }
if (-not $PSCmdlet.ShouldProcess("$queueName using genuine $driverName at RAW ${hostAddress}:9100", $plan.Action)) { return }
$createdPort = $false
try {
    if ($needNewPort) {
        if ($Bidirectional) {
            Add-PrinterPort -Name $portName -PrinterHostAddress $hostAddress -PortNumber 9100 -SNMP 1 -SNMPCommunity 'public' -Confirm:$false -ErrorAction Stop
        } else {
            Add-PrinterPort -Name $portName -PrinterHostAddress $hostAddress -PortNumber 9100 -Confirm:$false -ErrorAction Stop
        }
        $createdPort = $true
        Assert-Port $portName $hostAddress
    }
    if ($queueExists) {
        Assert-Queue $previousPort $sourceQueueKey
        if ($renameQueue) { Rename-Printer -Name $sourceQueueName -NewName $queueName -Confirm:$false -ErrorAction Stop }
        Set-Printer -Name $queueName -PortName $portName -Confirm:$false -ErrorAction Stop
    } else {
        Add-Printer -Name $queueName -DriverName $driverName -PortName $portName -Comment $ownerComment -Confirm:$false -ErrorAction Stop
    }
    if ($changeBidi -and (($queueExists -and -not $migrate) -or $adoptPort)) {
        Set-OwnedPortBidirectional $portName ([bool]$Bidirectional)
    }
    Assert-Queue $portName
    Write-Host "SayScore PDF 준비 완료 · RAW ${hostAddress}:9100 · 사이트 지원 여부는 별도 확인"
} catch {
    $failure = $_
    if ($createdPort) {
        try {
            if (@(Get-Printer -ErrorAction Stop | Where-Object { $_.PortName -ceq $portName }).Count -eq 0) {
                Assert-Port $portName $hostAddress
                Remove-PrinterPort -Name $portName -Confirm:$false -ErrorAction Stop
            }
        } catch { Write-Warning "New port was preserved because safe rollback could not be verified: $_" }
    }
    throw $failure
}
