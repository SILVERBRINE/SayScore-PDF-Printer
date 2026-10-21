# Exits 0 when WSL 2 can import a distribution: wsl.exe supports --version and
# both Windows optional components are enabled. A PC can have the WSL package
# installed while the components are off, and then wsl --import fails with
# WSL_E_WSL_OPTIONAL_COMPONENT_REQUIRED.

$ErrorActionPreference = 'Stop'
try {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { exit 1 }
    # The inbox stub on PCs without WSL does not support --version.
    & wsl.exe --version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { exit 1 }
    foreach ($name in 'Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform') {
        $feature = Get-CimInstance Win32_OptionalFeature -Filter "Name='$name'"
        # InstallState 1 = enabled.
        if (-not $feature -or $feature.InstallState -ne 1) { exit 1 }
    }
    exit 0
} catch {
    exit 1
}
