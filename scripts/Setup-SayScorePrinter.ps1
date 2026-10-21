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
