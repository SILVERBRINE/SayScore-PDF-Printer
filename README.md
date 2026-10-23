<div align="center">

**한국어** · [English](README.en.md)

# SayScore PDF

인쇄하면 자동으로 PDF로 저장되는 무료 Windows 프린터

<a href="https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases/latest/download/SayScorePDF-Setup.exe"><img alt="Windows용 다운로드" src="https://img.shields.io/badge/%E2%AC%87%20Windows%EC%9A%A9%20%EB%8B%A4%EC%9A%B4%EB%A1%9C%EB%93%9C-SayScorePDF--Setup.exe-2f81f7?style=for-the-badge&logo=windows&logoColor=white" height="44"></a>

[![최신 버전](https://img.shields.io/github/v/release/SILVERBRINE/SayScore-PDF-Printer?label=%EC%B5%9C%EC%8B%A0%20%EB%B2%84%EC%A0%84)](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases/latest)
[![다운로드](https://img.shields.io/github/downloads/SILVERBRINE/SayScore-PDF-Printer/total?label=%EB%8B%A4%EC%9A%B4%EB%A1%9C%EB%93%9C)](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases)
[![후원하기](https://img.shields.io/badge/%E2%99%A5%20%ED%9B%84%EC%9B%90%ED%95%98%EA%B8%B0-GitHub%20Sponsors-bf3989?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/SILVERBRINE)

</div>

## 사용법

1. 위의 **Windows용 다운로드** 버튼으로 설치 파일을 받아 실행합니다.
   - "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누르세요.
2. 처음 실행하면 앱 전용 가상 네트워크 어댑터를 준비합니다. 관리자 확인 창이 나오면 **예**를 누릅니다. 재부팅은 필요 없어서 PC방처럼 재부팅하면 초기화되는 PC에서도 쓸 수 있습니다.
   - 프린터는 일반 네트워크 프린터처럼 연결됩니다.
   - 필요하면 앱 아래쪽 **연결 방식**에서 **WSL** 방식으로 바꿀 수 있습니다. 처음 한 번 Windows 기능(WSL 2)을 설치하고 재부팅해야 합니다.
3. 아무 프로그램에서나 인쇄할 때 프린터로 **SayScore PDF**를 고릅니다.
4. PDF는 앱의 **PDF 폴더 열기** 버튼으로 확인할 수 있습니다.

## 요구 사항

- Windows 11 (x64, ARM64) 또는 Windows 10 22H2 이상 (x64)
- 관리자 권한 (프린터 추가에 필요)
- WSL 방식을 고를 때만: 인터넷 연결, BIOS/UEFI 가상화 켜짐 (대부분의 PC는 기본으로 켜져 있음), 재부팅 1회

## 제거

**Windows 설정 → 앱**에서 SayScore PDF를 제거하면 프린터도 함께 지워집니다. 저장된 PDF는 남습니다.

## 개인정보

인쇄한 내용과 PDF는 내 PC에만 저장되며 어디에도 전송되지 않습니다.

## 다운로드 · Star 추이

<img alt="다운로드 추이" src="https://raw.githubusercontent.com/SILVERBRINE/SayScore-PDF-Printer/stats/downloads.svg" width="49%"> <img alt="Star 추이" src="https://raw.githubusercontent.com/SILVERBRINE/SayScore-PDF-Printer/stats/stars.svg" width="49%">

## 후원

SayScore PDF는 공익을 위해 무료로 제공됩니다. 도움이 되셨다면 [GitHub Sponsors](https://github.com/sponsors/SILVERBRINE)로 응원해 주세요.

## 공식 배포처 · 라이선스

공식 배포처는 이 저장소의 [Releases](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases)뿐입니다. 다른 곳에서 받은 설치 파일은 사용하지 마세요.

Copyright (C) 2026 SILVERBRINE · [GNU GPL v3](LICENSE) · [서드파티 고지](THIRD_PARTY_NOTICES.md) · [개발 문서](docs/DEVELOPMENT.md)
