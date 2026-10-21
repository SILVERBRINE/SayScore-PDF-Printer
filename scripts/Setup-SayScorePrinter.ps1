param(
    [Parameter(Mandatory = $true)][ValidateSet('Install-LocalPrinter.ps1', 'Install-X64Printer.ps1')][string]$Installer,
    [Parameter(Mandatory = $true)][string]$CaptureAddress,
    [string]$PrinterAddress,
    [Parameter(Mandatory = $true)][string]$DriverName,
    [Parameter(Mandatory = $true)][string]$ResultPath,
    [string]$QueueName = 'SayScore PDF',
    [string]$PreviousQueueName,
    [switch]$Bidirectional
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$samsungDrivers = @('Samsung X4305 Series', 'Samsung CLX-9252 9352 Series PCL6 Class Driver')
$result = [ordered]@{ ok = $false; message = ''; driver = $DriverName; installer = $Installer
    warning = ''; output = ''; finished = (Get-Date).ToString('o') }
$output = ''
try {
    if ($DriverName -in $samsungDrivers) {
        try {
            $output += & (Join-Path $PSScriptRoot 'Install-SamsungDriver.ps1') -Apply *>&1 | Out-String
        } catch {
            $result.warning = 'Samsung 드라이버 설치 실패로 Windows 기본 Microsoft PCL6 드라이버를 사용했습니다: ' + $_.Exception.Message
            $output += ($_ | Out-String)
            $Installer = 'Install-LocalPrinter.ps1'
            $DriverName = 'Microsoft PCL6 Class Driver'
            $result.installer = $Installer
            $result.driver = $DriverName
        }
    }
    # Each installer only adopts queues using its own driver family. When the user
    # switches family (e.g. Samsung X4305 -> Microsoft PCL6), remove only the queue
    # SayScore created; the installer then reuses its matching port.
    $ownerComment = 'SayScore PDF local capture queue; created by Install-LocalPrinter.ps1 v2'
    $localDrivers = @('HP Universal Printing PCL 6', 'Microsoft PCL6 Class Driver', 'Microsoft PS Class Driver',
        'Samsung CLX-9252 9352 Series PCL6 Class Driver')
    $sourceName = if ([string]::IsNullOrWhiteSpace($PreviousQueueName)) { $QueueName } else { $PreviousQueueName }
    $owned = @(Get-Printer -ErrorAction SilentlyContinue | Where-Object { $_.Name -ceq $sourceName -and $_.Comment -ceq $ownerComment })
    if ($owned.Count -eq 1 -and $owned[0].DriverName -cne $DriverName) {
        $sameFamily = ($Installer -eq 'Install-LocalPrinter.ps1') -and ($owned[0].DriverName -in $localDrivers)
        if (-not $sameFamily) {
            Remove-Printer -Name $owned[0].Name -Confirm:$false -ErrorAction Stop
            $output += "Removed owned queue '$($owned[0].Name)' ($($owned[0].DriverName)) to switch to $DriverName`n"
            $PreviousQueueName = $null
        }
    }
    $script = Join-Path $PSScriptRoot $Installer
    $installerArgs = @{ CaptureAddress = $CaptureAddress; DriverName = $DriverName
        QueueName = $QueueName; Apply = $true }
    if (-not [string]::IsNullOrWhiteSpace($PrinterAddress)) { $installerArgs.PrinterAddress = $PrinterAddress }
    if (-not [string]::IsNullOrWhiteSpace($PreviousQueueName)) { $installerArgs.PreviousQueueName = $PreviousQueueName }
    if ($Bidirectional) { $installerArgs.Bidirectional = $true }
    $output += & $script @installerArgs *>&1 | Out-String
    $result.ok = $true
    $result.message = "SayScore PDF 프린터 준비 완료 ($DriverName)"
} catch {
    $result.message = $_.Exception.Message
    $output += ($_ | Out-String)
}
$result.output = $output
$result.finished = (Get-Date).ToString('o')
$temporary = $ResultPath + '.tmp'
[IO.File]::WriteAllText($temporary, ($result | ConvertTo-Json -Depth 3), [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temporary -Destination $ResultPath -Force
if (-not $result.ok) { exit 1 }
