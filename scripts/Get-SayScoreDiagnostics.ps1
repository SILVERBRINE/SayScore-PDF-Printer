[CmdletBinding()]
param(
    [string]$PrinterName = 'SayScore PDF',
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\data\diagnostics'),
    [switch]$RunProtocolProbe
)

$ErrorActionPreference = 'Stop'
$queue = Get-Printer -Name $PrinterName -Full
$port = Get-PrinterPort -Name $queue.PortName
$driver = Get-PrinterDriver -Name $queue.DriverName
$cimPrinter = Get-CimInstance Win32_Printer -Filter ("Name='" + $PrinterName.Replace("'", "''") + "'")
$cimPort = Get-CimInstance Win32_TCPIPPrinterPort -Filter ("Name='" + $queue.PortName.Replace("'", "''") + "'")
$nic = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -eq $port.PrinterHostAddress } |
    Select-Object InterfaceAlias, InterfaceIndex, IPAddress, PrefixLength, AddressState

$portKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Print\Monitors\Standard TCP/IP Port\Ports\' + $queue.PortName
$queueKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Print\Printers\' + $PrinterName
$portRegistry = if (Test-Path -LiteralPath $portKey) { Get-ItemProperty -LiteralPath $portKey } else { $null }
$queueRegistry = if (Test-Path -LiteralPath $queueKey) { Get-ItemProperty -LiteralPath $queueKey } else { $null }
$report = [ordered]@{
    Timestamp = (Get-Date).ToString('o')
    ProcessArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture.ToString()
    OSArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    Printer = $queue | Select-Object Name, DriverName, PortName, PrinterStatus, RenderingMode, Type
    Driver = $driver | Select-Object Name, Manufacturer, MajorVersion, DriverVersion,
        InfPath, ConfigFile, DataFile, DriverPath, HelpFile, MonitorName, PrintProcessor
    Port = $port | Select-Object Name, Description, PrinterHostAddress, PortNumber, Protocol,
        PortMonitor, SNMPEnabled, SNMPCommunity, SNMPIndex, LprByteCounting, LprQueueName
    Win32_Printer = $cimPrinter | Select-Object PrinterStatus, ExtendedPrinterStatus,
        DetectedErrorState, WorkOffline, EnableBIDI, Status, Network, Local
    Win32_TCPIPPrinterPort = $cimPort | Select-Object HostAddress, Protocol, PortNumber,
        SNMPEnabled, SNMPCommunity, SNMPDevIndex, ByteCount, DoubleSpool, Queue, Type
    MatchingLocalIPv4 = @($nic)
    AddressTopology = [ordered]@{
        PrinterHostAddress = $port.PrinterHostAddress
        IsAssignedToThisComputer = @($nic).Count -gt 0
        IsSameAsPhysicalOrVirtualNic = @($nic).Count -gt 0
        Note = if (@($nic).Count -gt 0) {
            'The Standard TCP/IP port targets an address assigned to this computer. This is observable topology, not proof of a third-party rejection rule.'
        } else {
            'The Standard TCP/IP port target was not found among current local IPv4 assignments.'
        }
    }
    PortRegistry = if ($portRegistry) { $portRegistry | Select-Object Protocol, Version, HostName,
        PortNumber, 'SNMP Community', 'SNMP Enabled', 'SNMP Index', PortMonMibPortIndex } else { $null }
    QueueRegistry = if ($queueRegistry) { $queueRegistry | Select-Object Status, StatusExt,
        'Print Processor', Datatype, 'Printer Driver', Port, Attributes,
        ModernPrintingVerified, WindowsProtectedPrintSupportVerified } else { $null }
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$target = Join-Path $OutputDirectory "windows-print-$stamp.json"
$json = $report | ConvertTo-Json -Depth 5
$json | Set-Content -LiteralPath $target -Encoding utf8
$json
Write-Host "Saved: $target"

if ($RunProtocolProbe) {
    $project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $python = Join-Path $project 'vendor\python-x64\3.13.9\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $pythonCommand -or $pythonCommand.Source -like '*\WindowsApps\*') {
            throw '진단 프로브를 실행할 Python 3를 찾지 못했습니다.'
        }
        $python = $pythonCommand.Source
    }
    & $python (Join-Path $PSScriptRoot '..\tools\network_printer_probe.py') --host $port.PrinterHostAddress `
        --port $port.PortNumber --community $port.SNMPCommunity --output-dir $OutputDirectory
}
