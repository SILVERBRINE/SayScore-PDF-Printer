<div align="center">

[한국어](README.md) · **English**

# SayScore PDF

A free Windows printer that saves everything you print as a PDF

<a href="https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases/latest/download/SayScorePDF-Setup.exe"><img alt="Download for Windows" src="https://img.shields.io/badge/%E2%AC%87%20Download%20for%20Windows-SayScorePDF--Setup.exe-2f81f7?style=for-the-badge&logo=windows&logoColor=white" height="44"></a>

[![Latest release](https://img.shields.io/github/v/release/SILVERBRINE/SayScore-PDF-Printer?label=latest)](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/SILVERBRINE/SayScore-PDF-Printer/total?label=downloads)](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases)
[![Sponsor](https://img.shields.io/badge/%E2%99%A5%20Sponsor-GitHub%20Sponsors-bf3989?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/SILVERBRINE)

</div>

## How to use

1. Download the installer with the **Download for Windows** button above and run it.
   - If Windows shows "Windows protected your PC", choose **More info → Run anyway**.
2. On first launch it sets up an app-only virtual network adapter. Choose **Yes** in the administrator prompt. No restart is needed, so it also works on PCs that reset on restart, such as internet cafés.
   - The printer connects like a regular network printer.
   - If needed, switch to **WSL** with the **연결 방식** (connection mode) buttons at the bottom of the app. The first switch installs the Windows WSL 2 feature and needs a restart.
3. Print from any app and choose the **SayScore PDF** printer.
4. Open your PDFs with the app's **PDF 폴더 열기** (Open PDF folder) button.

## Requirements

- Windows 11 (x64, ARM64) or Windows 10 22H2 or later (x64)
- Administrator rights (to add the printer)
- Only when choosing WSL: an internet connection, virtualization enabled in BIOS/UEFI (on by default on most PCs) and one restart

## Uninstall

Remove SayScore PDF in **Windows Settings → Apps**; its printer is removed too. Your saved PDFs are kept.

## Privacy

What you print and the PDFs stay on your PC and are never sent anywhere.

## Downloads and stars

<img alt="Downloads over time" src="https://raw.githubusercontent.com/SILVERBRINE/SayScore-PDF-Printer/stats/downloads.svg" width="49%"> <img alt="Stars over time" src="https://raw.githubusercontent.com/SILVERBRINE/SayScore-PDF-Printer/stats/stars.svg" width="49%">

## Sponsor

SayScore PDF is free for the public good. If it helps you, please consider supporting it through [GitHub Sponsors](https://github.com/sponsors/SILVERBRINE).

## Official downloads and license

The only official source is this repository's [Releases](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases) page. Do not use installers from anywhere else.

Copyright (C) 2026 SILVERBRINE · [GNU GPL v3](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Developer notes](docs/DEVELOPMENT.md)
