[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [switch]$Apply,
    [string]$CaptureAddress,
    [string]$PrinterAddress,
    [ValidateSet('HP Universal Printing PCL 6', 'Microsoft PCL6 Class Driver', 'Microsoft PS Class Driver',
        'Samsung CLX-9252 9352 Series PCL6 Class Driver')]
    [string]$DriverName = 'Microsoft PCL6 Class Driver',
    [string]$DriverInfPath,
    [string]$QueueName = 'SayScore PDF',
    [string]$PreviousQueueName,
    [switch]$Bidirectional
)

$ErrorActionPreference = 'Stop'

function Test-QueueName([string]$Name) {
    return -not ([string]::IsNullOrWhiteSpace($Name) -or $Name.Length -gt 220 -or $Name -match '[!,\\/]')
}
if (-not (Test-QueueName $QueueName)) {
    throw 'QueueName must be a valid Windows printer name (not empty, no ! , \ / characters).'
}
$queueName = $QueueName
$sourceQueueName = if (-not [string]::IsNullOrWhiteSpace($PreviousQueueName)) { $PreviousQueueName } else { $QueueName }
if (-not (Test-QueueName $sourceQueueName)) { throw 'PreviousQueueName is not a valid printer name.' }
$renameQueue = $sourceQueueName -cne $queueName
$driverVersion = $(if ($DriverName -eq 'HP Universal Printing PCL 6') { 3 } else { 4 })
$portNumber = 9100
$ownerComment = 'SayScore PDF local capture queue; created by Install-LocalPrinter.ps1 v2'
$printRoot = 'HKLM:\SYSTEM\CurrentControlSet\Control\Print'
$queueKey = "$printRoot\Printers\$queueName"
$sourceQueueKey = "$printRoot\Printers\$sourceQueueName"

function Get-NativeOSArchitecture {
    if (-not ('SayScoreLocal.NativeSystem' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace SayScoreLocal {
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
    $machine = [SayScoreLocal.NativeSystem]::Architecture()
    if ($machine -eq 0xaa64) { return 'Arm64' }
    if ($machine -eq 0x8664) { return 'X64' }
    return "Other ($machine)"
}

$architecture = Get-NativeOSArchitecture
if ($architecture -ceq 'Arm64') {
    $printerEnvironment = 'Windows ARM64'; $infArch = 'arm64'; $archLabel = 'ARM64'
} elseif ($architecture -ceq 'X64') {
    $printerEnvironment = 'Windows x64'; $infArch = 'amd64'; $archLabel = 'x64'
} else {
    throw "This setup requires native ARM64 or x64 Windows; detected $architecture."
}
$driverKey = "$printRoot\Environments\$printerEnvironment\Drivers\Version-$driverVersion\$DriverName"

function Test-PrivateIPv4([string]$Address) {
    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($Address, [ref]$parsed) -or
        $parsed.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
        $parsed.ToString() -cne $Address) { return $false }
    $bytes = $parsed.GetAddressBytes()
    return ($bytes[0] -eq 10 -or
        ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
        ($bytes[0] -eq 192 -and $bytes[1] -eq 168))
}

function Get-EligibleCaptureAddresses {
    $adapters = @(Get-NetAdapter -ErrorAction Stop | Where-Object { $_.Status -eq 'Up' })
    $addresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop)
    return @($addresses | Where-Object {
        $address = $_
        (Test-PrivateIPv4 $address.IPAddress) -and
        $address.AddressState -eq 'Preferred' -and
        @($adapters | Where-Object {
            $_.ifIndex -eq $address.InterfaceIndex -and
            $_.InterfaceDescription -notmatch 'Loopback' -and $_.Name -notmatch 'Loopback'
        }).Count -eq 1
    } | Sort-Object IPAddress, InterfaceIndex)
}

function Resolve-CaptureAddress([string]$RequestedAddress) {
    if (-not [string]::IsNullOrEmpty($RequestedAddress) -and
        -not (Test-PrivateIPv4 $RequestedAddress)) {
        throw 'CaptureAddress must be a canonical, non-loopback private IPv4 address.'
    }
    $eligible = @(Get-EligibleCaptureAddresses)
    if (-not [string]::IsNullOrEmpty($RequestedAddress)) {
        $matches = @($eligible | Where-Object { $_.IPAddress -ceq $RequestedAddress })
        if ($matches.Count -ne 1) {
            throw "CaptureAddress $RequestedAddress is not a Preferred address assigned to an Up non-loopback adapter."
        }
        return $matches[0]
    }
    if ($eligible.Count -ne 1) {
        $choices = @($eligible | ForEach-Object { "$($_.IPAddress) [$($_.InterfaceAlias)]" }) -join ', '
        throw "Exactly one eligible private IPv4 address is required for automatic selection. Found $($eligible.Count): $choices. Specify -CaptureAddress with the intended assigned address."
    }
    return $eligible[0]
}

$captureEndpoint = Resolve-CaptureAddress $CaptureAddress
$captureHost = $captureEndpoint.IPAddress
if (-not [string]::IsNullOrEmpty($PrinterAddress) -and -not (Test-PrivateIPv4 $PrinterAddress)) {
    throw 'PrinterAddress must be a canonical, non-loopback private IPv4 address.'
}
$hostAddress = $(if ($PrinterAddress) { $PrinterAddress } else { $captureHost })
if ($PrinterAddress -and $hostAddress -eq $captureHost) {
    throw 'PrinterAddress must use the separate relay network address, not CaptureAddress.'
}
$portName = $hostAddress
$portKey = "$printRoot\Monitors\Standard TCP/IP Port\Ports\$portName"

function Read-OptionalRegistryValue([object]$Item, [string]$Name) {
    if ($null -ne $Item -and $null -ne $Item.PSObject.Properties[$Name]) {
        return $Item.PSObject.Properties[$Name].Value
    }
    return $null
}

function Resolve-InboxDriverInf([string]$RequestedPath, [string]$ModelName, [string]$InfArch = 'arm64') {
    $archName = $(if ($InfArch -eq 'amd64') { 'x64' } else { 'ARM64' })
    $section = $(if ($InfArch -eq 'amd64') { 'Microsoft.NTamd64' } else { 'Microsoft.NTarm64' })
    if ($ModelName -notin @('Microsoft PCL6 Class Driver', 'Microsoft PS Class Driver')) {
        throw 'Only the allowlisted Microsoft class drivers can be registered from DriverStore.'
    }
    $storeRoot = [IO.Path]::GetFullPath((Join-Path $env:windir 'System32\DriverStore\FileRepository'))
    if ([string]::IsNullOrEmpty($RequestedPath)) {
        $paths = @(Get-ChildItem -LiteralPath $storeRoot -Directory -Filter "prnms005.inf_${InfArch}_*" -ErrorAction Stop |
            ForEach-Object { Join-Path $_.FullName 'prnms005.inf' } | Where-Object { Test-Path -LiteralPath $_ })
        if ($paths.Count -ne 1) { throw "Exactly one inbox $archName prnms005.inf candidate is required; specify -DriverInfPath." }
        $RequestedPath = $paths[0]
    }
    $resolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $RequestedPath -ErrorAction Stop).Path)
    $relative = $resolved.Substring([Math]::Min($storeRoot.Length + 1, $resolved.Length))
    if (-not $resolved.StartsWith($storeRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
        $relative -notmatch ('^prnms005\.inf_' + $InfArch + '_[a-z0-9]+\\prnms005\.inf$')) {
        throw "DriverInfPath must be the existing inbox $archName prnms005.inf inside Windows DriverStore."
    }
    foreach ($itemPath in @($storeRoot, [IO.Path]::GetDirectoryName($resolved), $resolved)) {
        if (((Get-Item -LiteralPath $itemPath -ErrorAction Stop).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'DriverStore INF paths containing reparse points are not permitted.'
        }
    }
    $inf = Get-Content -LiteralPath $resolved -Raw -ErrorAction Stop
    $archSection = [regex]::Match($inf, '(?ims)^\[' + [regex]::Escape($section) + '\]\s*\r?\n(?<models>.*?)(?=^\[|\z)').Groups['models'].Value
    $modelPattern = '(?m)^"' + [regex]::Escape($ModelName) + '"\s*='
    if ($inf -notmatch '(?im)^Provider\s*=\s*"Microsoft"\s*$' -or
        $inf -notmatch '(?im)^Class\s*=\s*Printer\s*$' -or
        $inf -notmatch '(?im)^ClassVer\s*=\s*4\.0\s*$' -or
        $archSection -notmatch $modelPattern) {
        throw "Inbox INF does not identify the exact Microsoft $archName class driver model."
    }
    return $resolved
}

function Assert-DriverRegistry {
    $driverRegistry = Get-ItemProperty -LiteralPath $driverKey -ErrorAction Stop
    if ((Read-OptionalRegistryValue $driverRegistry 'Version') -ne $driverVersion -or
        ($driverVersion -eq 3 -and [string]::IsNullOrEmpty((Read-OptionalRegistryValue $driverRegistry 'Driver'))) -or
        ($driverVersion -eq 4 -and [string]::IsNullOrEmpty((Read-OptionalRegistryValue $driverRegistry 'Data File')))) {
        throw "Installed driver registry entry is not a usable native $(if ($archLabel) { $archLabel } else { 'ARM64' }) driver of the expected version."
    }
}

function Assert-PortRegistry([string]$ExpectedPortName = $portName, [string]$ExpectedHostAddress = $hostAddress,
    [int]$ExpectedPortNumber = $portNumber) {
    $expectedPortKey = "$printRoot\Monitors\Standard TCP/IP Port\Ports\$ExpectedPortName"
    $port = Get-ItemProperty -LiteralPath $expectedPortKey
    $registryHost = Read-OptionalRegistryValue $port 'HostName'
    $registryIp = Read-OptionalRegistryValue $port 'IPAddress'
    if ([string]::IsNullOrEmpty($registryHost)) { $registryHost = $registryIp }
    if ($registryHost -ne $ExpectedHostAddress -or
        (-not [string]::IsNullOrEmpty($registryIp) -and $registryIp -ne $ExpectedHostAddress) -or
        (Read-OptionalRegistryValue $port 'PortNumber') -ne $ExpectedPortNumber -or
        (Read-OptionalRegistryValue $port 'Protocol') -ne 1) {
        throw "Port name collision or unexpected settings: $ExpectedPortName. Nothing existing will be changed."
    }
}

function Get-PortSnmpEnabled([string]$PortName) {
    $port = Get-ItemProperty -LiteralPath "$printRoot\Monitors\Standard TCP/IP Port\Ports\$PortName" -ErrorAction Stop
    return [int]((Read-OptionalRegistryValue $port 'SNMP Enabled')) -ne 0
}

function Set-OwnedPortBidirectional([string]$PortName, [bool]$Enabled) {
    # Win32_TCPIPPrinterPort.SNMPEnabled is read-only, so set the port monitor's
    # registry values directly (as the reference tool does) and restart the spooler
    # so the Standard TCP/IP Port monitor re-reads them.
    $key = "$printRoot\Monitors\Standard TCP/IP Port\Ports\$PortName"
    Set-ItemProperty -LiteralPath $key -Name 'SNMP Enabled' -Value ([int][bool]$Enabled) -Type DWord -ErrorAction Stop
    if ($Enabled) {
        Set-ItemProperty -LiteralPath $key -Name 'SNMP Community' -Value 'public' -Type String -ErrorAction Stop
        Set-ItemProperty -LiteralPath $key -Name 'SNMP Index' -Value 1 -Type DWord -ErrorAction Stop
    }
    Restart-Service -Name Spooler -Force -ErrorAction Stop
}

function Assert-QueueRegistry([string]$ExpectedPortName = $portName, [string]$ExpectedDriverName = $DriverName,
    [string]$ExpectedQueueKey = $queueKey) {
    $queue = Get-ItemProperty -LiteralPath $ExpectedQueueKey
    if ((Read-OptionalRegistryValue $queue 'Printer Driver') -ne $ExpectedDriverName -or
        (Read-OptionalRegistryValue $queue 'Port') -ne $ExpectedPortName -or
        (Read-OptionalRegistryValue $queue 'Description') -ne $ownerComment) {
        throw "Queue name collision or missing ownership marker: $ExpectedQueueKey. Nothing existing will be changed."
    }
}

$registerInboxDriver = -not (Test-Path -LiteralPath $driverKey)
$resolvedDriverInf = $null
if ($DriverName -eq 'Samsung CLX-9252 9352 Series PCL6 Class Driver' -and $architecture -cne 'Arm64') {
    throw 'The Samsung CLX-9252 9352 class driver profile is ARM64-only. Use the Microsoft PCL6 Class Driver on x64.'
}
if ($DriverName -eq 'Samsung CLX-9252 9352 Series PCL6 Class Driver' -and $registerInboxDriver) {
    throw 'The exact Samsung native ARM64 v4 driver must already be registered. This script does not stage or register Samsung packages.'
}
if ($registerInboxDriver -or -not [string]::IsNullOrEmpty($DriverInfPath)) {
    $resolvedDriverInf = Resolve-InboxDriverInf $DriverInfPath $DriverName $infArch
}
if (-not $registerInboxDriver) { Assert-DriverRegistry }

$queueExists = Test-Path -LiteralPath $sourceQueueKey
$portExists = Test-Path -LiteralPath $portKey
if ($renameQueue -and $queueExists -and (Test-Path -LiteralPath $queueKey)) {
    throw "The target queue name '$queueName' already exists. Refusing to rename onto it."
}
if ($renameQueue -and -not $queueExists) {
    throw "No owned queue named '$sourceQueueName' was found to rename. Nothing changed."
}
$migrateOwnedQueue = $false
$changeOwnedDriver = $false
$changeBidi = $false
$adoptPort = $false
$existingDriverName = $DriverName
$existingQueuePort = $portName
$existingHostAddress = $hostAddress
$existingPortNumber = $portNumber
if ($queueExists) {
    $existingRegistry = Get-ItemProperty -LiteralPath $sourceQueueKey
    $existingQueuePort = Read-OptionalRegistryValue $existingRegistry 'Port'
    $existingDriverName = Read-OptionalRegistryValue $existingRegistry 'Printer Driver'
    if ($existingDriverName -notin @('HP Universal Printing PCL 6', 'Microsoft PCL6 Class Driver', 'Microsoft PS Class Driver',
        'Samsung CLX-9252 9352 Series PCL6 Class Driver')) {
        throw 'Owned queue has an unsupported current driver. Refusing automatic replacement.'
    }
    Assert-QueueRegistry $existingQueuePort $existingDriverName $sourceQueueKey
    $changeOwnedDriver = $existingDriverName -cne $DriverName
    if ($existingQueuePort -match '^SayScorePDF_(.+)$' -and (Test-PrivateIPv4 $Matches[1])) {
        $existingHostAddress = $Matches[1]
        $existingPortNumber = 19100
    } elseif (Test-PrivateIPv4 $existingQueuePort) {
        $existingHostAddress = $existingQueuePort
        $existingPortNumber = 9100
    } else {
        throw 'Owned queue has an unexpected port identity. Refusing automatic repair.'
    }
    Assert-PortRegistry $existingQueuePort $existingHostAddress $existingPortNumber
    $migrateOwnedQueue = $existingQueuePort -cne $portName
    if (-not $migrateOwnedQueue) {
        $changeBidi = (Get-PortSnmpEnabled $existingQueuePort) -ne [bool]$Bidirectional
    }
    if ($migrateOwnedQueue -and $portExists) {
        throw 'The proposed new port already exists. Refusing to adopt it for an address update.'
    }
} elseif ($portExists) {
    # The owned queue is gone but a matching numeric-IP RAW 9100 port remains
    # (e.g. removed during testing). Adopt it instead of refusing, but only when
    # it has exactly the shape this script would create (host/protocol/port verified).
    Assert-PortRegistry
    $adoptPort = $true
    $changeBidi = (Get-PortSnmpEnabled $portName) -ne [bool]$Bidirectional
}

$plan = [pscustomobject]@{
    Mode = $(if ($Apply -and -not $WhatIfPreference) { 'Apply requested' } else { 'Dry run; no changes' })
    Queue = $queueName
    Driver = $DriverName
    DriverEnvironment = $printerEnvironment
    DriverVersion = $driverVersion
    DriverRegistry = $driverKey
    DriverRegistration = $(if ($registerInboxDriver) { "Register exact inbox Microsoft $archLabel model during Apply" } else { 'Already registered' })
    DriverInf = $resolvedDriverInf
    PortName = $portName
    HostAddress = $hostAddress
    CaptureAddress = $captureHost
    InterfaceAlias = $captureEndpoint.InterfaceAlias
    InterfaceIndex = $captureEndpoint.InterfaceIndex
    PortNumber = $portNumber
    Protocol = 'RAW'
    SNMPEnabled = [bool]$Bidirectional
    OwnershipComment = $ownerComment
    PreviousPort = $(if ($migrateOwnedQueue) { $existingQueuePort } else { $null })
    PreviousPortNumber = $(if ($migrateOwnedQueue) { $existingPortNumber } else { $null })
    PreviousDriver = $(if ($changeOwnedDriver) { $existingDriverName } else { $null })
    RenameFrom = $(if ($renameQueue) { $sourceQueueName } else { $null })
    Action = $(if ($renameQueue) { "Rename only the owned queue '$sourceQueueName' to '$queueName' and update it" } elseif ($migrateOwnedQueue) { 'Create new port and update only the owned queue; preserve old port' } elseif ($changeOwnedDriver) { 'Update only the owned queue driver; retain existing private-IP port' } elseif ($adoptPort) { 'Adopt the matching existing port and create the owned queue on it' } elseif ($changeBidi) { "Update only the owned port's SNMP/bidirectional setting" } elseif ($queueExists) { 'Already owned and matching; no changes required' } else { 'Create a new port and a new queue' })
    PrintValidation = 'Queue registration does not verify this print job or website support'
}
$plan | Format-List | Out-Host
if (-not $Apply -or $WhatIfPreference) {
    $infArgument = $(if ($resolvedDriverInf) { " -DriverInfPath '$resolvedDriverInf'" } else { '' })
    Write-Host "To apply this plan, run this script with -CaptureAddress $hostAddress -DriverName '$DriverName'$infArgument -Apply in an Administrator PowerShell window."
    return
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'The explicit -Apply operation requires an Administrator PowerShell window.'
}
Import-Module PrintManagement

$liveQueue = @(Get-Printer | Where-Object { $_.Name -eq $sourceQueueName })
$livePort = @(Get-PrinterPort | Where-Object { $_.Name -eq $portName })
$liveDriver = @(Get-PrinterDriver | Where-Object {
    $_.Name -eq $DriverName -and $_.PrinterEnvironment -eq $printerEnvironment -and $_.MajorVersion -eq $driverVersion
})
if ((-not $registerInboxDriver -and $liveDriver.Count -ne 1) -or
    ($registerInboxDriver -and $liveDriver.Count -ne 0)) {
    throw 'The live spooler driver inventory differs from the dry-run plan. Run a fresh plan.'
}
if ($queueExists) {
    Assert-QueueRegistry $existingQueuePort $existingDriverName $sourceQueueKey
    Assert-PortRegistry $existingQueuePort $existingHostAddress $existingPortNumber
    $oldLivePort = @(Get-PrinterPort | Where-Object { $_.Name -eq $existingQueuePort })
    if ($liveQueue.Count -ne 1 -or $oldLivePort.Count -ne 1 -or
        $liveQueue[0].DriverName -ne $existingDriverName -or $liveQueue[0].PortName -ne $existingQueuePort -or
        $liveQueue[0].Comment -ne $ownerComment) {
        throw 'Owned queue does not match the live spooler inventory. No changes made.'
    }
    if ($renameQueue -and @(Get-Printer | Where-Object { $_.Name -eq $queueName }).Count) {
        throw "The target queue name '$queueName' became occupied. No changes made."
    }
    if (-not $migrateOwnedQueue -and -not $changeOwnedDriver -and -not $renameQueue -and -not $changeBidi) {
        Write-Host 'The owned queue and port already match. No changes made.'
        return
    }
}
if ((-not $queueExists -and ($liveQueue.Count -or (Test-Path -LiteralPath $queueKey))) -or
    (((-not $queueExists -and -not $adoptPort) -or $migrateOwnedQueue) -and ($livePort.Count -or (Test-Path -LiteralPath $portKey)))) {
    throw 'Queue or port name became occupied. No existing objects will be changed.'
}
if (-not $PSCmdlet.ShouldProcess("$queueName using $driverName at RAW ${hostAddress}:$portNumber", $plan.Action)) {
    return
}

$recheckedEndpoint = Resolve-CaptureAddress $captureHost
if ($recheckedEndpoint.InterfaceIndex -ne $captureEndpoint.InterfaceIndex) {
    throw 'CaptureAddress moved to another adapter. Run a fresh dry run before applying.'
}

$createdPort = $false
$createdQueue = $false
try {
    if ($registerInboxDriver) {
        if ((Resolve-InboxDriverInf $resolvedDriverInf $DriverName $infArch) -cne $resolvedDriverInf) {
            throw 'Inbox driver INF changed before registration.'
        }
        Add-PrinterDriver -Name $DriverName -InfPath $resolvedDriverInf -PrinterEnvironment $printerEnvironment -Confirm:$false -ErrorAction Stop
        Assert-DriverRegistry
        $registeredLiveDriver = @(Get-PrinterDriver | Where-Object {
            $_.Name -eq $DriverName -and $_.PrinterEnvironment -eq $printerEnvironment -and $_.MajorVersion -eq $driverVersion
        })
        if ($registeredLiveDriver.Count -ne 1) { throw "Exact inbox $archLabel driver was not registered. No queue changed." }
    }
    if ((-not $queueExists -and -not $adoptPort) -or $migrateOwnedQueue) {
        if ($Bidirectional) {
            Add-PrinterPort -Name $portName -PrinterHostAddress $hostAddress -PortNumber $portNumber -SNMP 1 -SNMPCommunity 'public' -Confirm:$false -ErrorAction Stop
        } else {
            Add-PrinterPort -Name $portName -PrinterHostAddress $hostAddress -PortNumber $portNumber -Confirm:$false -ErrorAction Stop
        }
        $createdPort = $true
    }
    Assert-PortRegistry
    if ($queueExists) {
        Assert-QueueRegistry $existingQueuePort $existingDriverName $sourceQueueKey
        Assert-PortRegistry $existingQueuePort $existingHostAddress $existingPortNumber
        $currentQueue = Get-Printer -Name $sourceQueueName
        if ($currentQueue.DriverName -ne $existingDriverName -or $currentQueue.PortName -ne $existingQueuePort -or
            $currentQueue.Comment -ne $ownerComment) {
            throw 'Owned queue changed during setup. Refusing to update it.'
        }
        if ($renameQueue) {
            Rename-Printer -Name $sourceQueueName -NewName $queueName -Confirm:$false -ErrorAction Stop
        }
        Set-Printer -Name $queueName -PortName $portName -DriverName $DriverName -Confirm:$false -ErrorAction Stop
    } else {
        Add-Printer -Name $queueName -DriverName $driverName -PortName $portName -Comment $ownerComment -Confirm:$false -ErrorAction Stop
    }
    $createdQueue = $true
    Assert-QueueRegistry
    # A new/migrated port already carries the SNMP state from Add-PrinterPort; an
    # existing port's SNMP flag is toggled in place (registry + spooler restart).
    if ($changeBidi -and (($queueExists -and -not $migrateOwnedQueue) -or $adoptPort)) {
        Set-OwnedPortBidirectional $portName ([bool]$Bidirectional)
    }
    Write-Host "Configured $queueName (SNMP/bidirectional: $([bool]$Bidirectional)). Start SayScore PDF listening on ${hostAddress}:$portNumber before printing."
} catch {
    $creationError = $_
    if ($createdPort -and -not $createdQueue) {
        try {
            $references = @(Get-Printer | Where-Object { $_.PortName -eq $portName })
            if ($references.Count -eq 0) {
                Assert-PortRegistry
                Remove-PrinterPort -Name $portName -Confirm:$false -ErrorAction Stop
                Write-Warning 'Queue creation failed; this invocation removed its newly created, unused port.'
            } else {
                Write-Warning 'The new port is now referenced by a queue and was preserved.'
            }
        } catch {
            Write-Warning "The new port could not be rolled back safely and was preserved: $_"
        }
    }
    throw $creationError
}
