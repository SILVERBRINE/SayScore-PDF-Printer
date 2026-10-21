<div align="center">

[한국어](README.md) · **English**

# SayScore PDF

Receives Windows print jobs through a real Windows printer driver and a Standard TCP/IP port, and saves them as PDF.

<a href="https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases/latest/download/SayScorePDF-Setup.exe"><img alt="Download for Windows" src="https://img.shields.io/badge/%E2%AC%87%20Download%20for%20Windows-SayScorePDF--Setup.exe-2f81f7?style=for-the-badge&logo=windows&logoColor=white" height="44"></a>

<sub>x64 · ARM64 Windows 11 / x64 Windows 10 22H2 or later · Free</sub>

[![Latest release](https://img.shields.io/github/v/release/SILVERBRINE/SayScore-PDF-Printer?label=latest)](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/SILVERBRINE/SayScore-PDF-Printer/total?label=downloads)](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases)
[![Stars](https://img.shields.io/github/stars/SILVERBRINE/SayScore-PDF-Printer?style=flat)](https://github.com/SILVERBRINE/SayScore-PDF-Printer/stargazers)
[![Sponsor](https://img.shields.io/badge/%E2%99%A5%20Sponsor-GitHub%20Sponsors-bf3989?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/SILVERBRINE)

</div>

## Install (recommended)

1. Click **Download for Windows** above and run `SayScorePDF-Setup.exe`. Earlier versions and SHA-256 checksums are on the [Releases](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases) page.
   - The installer is not code-signed yet. If Windows shows "Windows protected your PC", choose **More info → Run anyway**.
2. On a PC without WSL 2, the installer turns on only the WSL 2 Windows feature. It does not install a Linux distribution or Docker. Restart if asked; SayScore PDF starts automatically when you sign in.
3. On first launch, approve the Windows administrator prompt that registers the printer.
4. Choose `SayScore PDF` in any print dialog.

Uninstall from Windows Settings → Apps. This removes the SayScore PDF printer and its port, the `SayScore-Relay` distribution and the autostart entry. Printer drivers (other printers may use them) and your converted PDFs are kept.

## Portable ZIP

Releases carry only the installer. The portable ZIP is available from the build artifacts in [Actions](https://github.com/SILVERBRINE/SayScore-PDF-Printer/actions/workflows/release.yml). Extract it completely and run `SayScorePDF.exe`. It works like the installed version but does not start automatically, so run it again after a restart. PDFs and logs are saved in the `data` folder next to it.

## How it works

The launcher registers a dedicated, lightweight WSL distribution (`SayScore-Relay`, about 17 MB) from bundled per-CPU files, starts a network relay in it, then starts the app. The distribution does not mount Windows drives or run Windows programs, and preparing it needs no internet connection. The Windows printer queue prints to RAW 9100 / UDP 161 on the WSL 2 address, which is not assigned to Windows, and the relay forwards that to the app's internal TCP 19100 / UDP 1161 ports. Keeping the external and internal ports separate prevents relay loops and port exhaustion. The address is re-checked on every launch.

## Build

`.github/workflows/release.yml` downloads pinned versions of the Python runtime, GhostPCL and the Samsung drivers from their official sources, verifies their signatures and hashes, and builds the relay root filesystems, the ZIP and the installer. Pushing a `v*` tag creates a draft release with a single installer (`SayScorePDF-Setup.exe`). The download button points to a version only after its draft is published.

## Requirements

- x64 Windows 10 22H2 or later / Windows 11, or ARM64 Windows 11 (hardware virtualization required)
- WSL 2 (NAT networking mode, the default)
- At least 4 GB RAM
- Administrator rights when the printer is first installed
- On x64, the bundled Samsung X4305 driver is preferred.
- On ARM64, the ARM64 driver is selected separately; the x64 driver is never used.

## Limits on new PCs

Turning on WSL 2 the first time needs an internet connection and administrator approval, and may need a restart. The installer cannot enable BIOS/UEFI virtualization or lift organization security policies. PCs without administrator rights, Windows Server, 32-bit Windows, ARM64 Windows 10 and PCs with virtualization blocked are not supported.

Installation through PDF output has been verified on real x64 and ARM64 hardware.

## Data location

The installed version uses `%LOCALAPPDATA%\SayScorePDF`; the portable ZIP uses the `data` folder where it was extracted.

- Converted PDFs: `output`
- Original jobs and conversion records: `jobs`
- Communication diagnostics: `diagnostics`
- Current status: `runtime-status.json`
- Relay status: `relay-runtime.json`

Other printers already on the PC and the default printer setting are not changed.

## Privacy

- Print contents, converted PDFs and diagnostic logs stay in the data folder on this PC and are never sent anywhere.
- Diagnostic files in `diagnostics` contain the PC's IP addresses and printer/driver details. Review them before attaching them to an issue.

## Statistics

The [stats workflow](.github/workflows/stats.yml) updates these once a day. GitHub keeps no daily download history, so the download chart starts from the day the workflow was enabled.

<img alt="Installer downloads over time" src="https://raw.githubusercontent.com/SILVERBRINE/SayScore-PDF-Printer/stats/downloads.svg" width="49%"> <img alt="GitHub stars over time" src="https://raw.githubusercontent.com/SILVERBRINE/SayScore-PDF-Printer/stats/stars.svg" width="49%">

## Sponsor

SayScore PDF is free for the public good. If you would like to support its development and upkeep, you can sponsor it through [GitHub Sponsors](https://github.com/sponsors/SILVERBRINE). The **♥ 후원하기** (Sponsor) button at the top right of the app opens the same page.

## Official downloads

The only official source of SayScore PDF is this repository's [Releases](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases) page. Do not use installers obtained elsewhere; they may have been tampered with.

## License

Copyright (C) 2026 SILVERBRINE. SayScore PDF's code is licensed under the [GNU GPL v3](LICENSE) or any later version. Anyone may use, modify and redistribute it, but modified versions must also be released as source under the same license. Python, GhostPCL (AGPL-3.0), the Samsung printer drivers and other components bundled with the installer follow their own licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
