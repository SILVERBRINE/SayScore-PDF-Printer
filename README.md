<div align="center">

**한국어** · [English](README.en.md)

# SayScore PDF

Windows 인쇄 작업을 실제 Windows 프린터 드라이버와 Standard TCP/IP Port로 받아 PDF로 변환합니다.

<a href="https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases/latest/download/SayScorePDF-Setup.exe"><img alt="Windows용 다운로드" src="https://img.shields.io/badge/%E2%AC%87%20Windows%EC%9A%A9%20%EB%8B%A4%EC%9A%B4%EB%A1%9C%EB%93%9C-SayScorePDF--Setup.exe-2f81f7?style=for-the-badge&logo=windows&logoColor=white" height="44"></a>

<sub>x64 · ARM64 Windows 11 / x64 Windows 10 22H2 이상 · 무료</sub>

[![최신 버전](https://img.shields.io/github/v/release/SILVERBRINE/SayScore-PDF-Printer?label=%EC%B5%9C%EC%8B%A0%20%EB%B2%84%EC%A0%84)](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases/latest)
[![다운로드](https://img.shields.io/github/downloads/SILVERBRINE/SayScore-PDF-Printer/total?label=%EB%8B%A4%EC%9A%B4%EB%A1%9C%EB%93%9C)](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases)
[![Stars](https://img.shields.io/github/stars/SILVERBRINE/SayScore-PDF-Printer?style=flat)](https://github.com/SILVERBRINE/SayScore-PDF-Printer/stargazers)
[![후원하기](https://img.shields.io/badge/%E2%99%A5%20%ED%9B%84%EC%9B%90%ED%95%98%EA%B8%B0-GitHub%20Sponsors-bf3989?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/SILVERBRINE)

</div>

## 설치 (권장)

1. 위의 **Windows용 다운로드** 버튼을 눌러 `SayScorePDF-Setup.exe`를 받아 실행합니다. 이전 버전과 SHA-256은 [Releases](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases)에 있습니다.
   - 아직 코드 서명 전이라 "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누르세요.
2. WSL 2가 없는 PC에서는 설치 프로그램이 Windows의 WSL 2 기능만 켭니다. Linux 배포판이나 Docker는 설치하지 않습니다. 재부팅을 요청하면 재부팅하세요. 로그인하면 SayScore PDF가 자동으로 시작됩니다.
3. 처음 실행할 때 프린터를 등록하는 Windows 관리자 확인 창이 뜨면 승인합니다.
4. 인쇄 화면에서 `SayScore PDF`를 선택합니다.

제거는 Windows 설정 → 앱에서 합니다. SayScore PDF 프린터와 포트, `SayScore-Relay` 배포판, 자동 시작 항목을 지웁니다. 다른 프린터에서도 쓸 수 있는 프린터 드라이버와 변환된 PDF는 남겨 둡니다.

## 포터블 ZIP

릴리스에는 설치 파일만 올립니다. 포터블 ZIP은 [Actions](https://github.com/SILVERBRINE/SayScore-PDF-Printer/actions/workflows/release.yml)의 빌드 결과(Artifacts)에서 받을 수 있습니다. 압축을 완전히 푼 뒤 `SayScorePDF.exe`를 실행합니다. 동작은 설치판과 같지만, 자동 시작이 없어 재부팅 뒤에 다시 실행해야 합니다. PDF와 기록은 압축을 푼 폴더의 `data`에 저장됩니다.

## 동작 방식

실행기는 동봉된 CPU별 오프라인 파일로 SayScore 전용 경량 WSL 배포판(`SayScore-Relay`, 약 17MB)을 등록하고 네트워크 중계기를 실행한 다음 앱을 시작합니다. 이 배포판은 Windows 드라이브를 마운트하지 않고 Windows 프로그램도 실행하지 않습니다. 중계기 준비에는 인터넷이 필요하지 않습니다. Windows 프린터 큐는 Windows에 할당되지 않은 WSL 2 주소의 RAW 9100/UDP 161을 사용하고, 중계기는 이를 앱 전용 내부 포트 TCP 19100/UDP 1161로 전달합니다. 외부 포트와 내부 포트를 분리해 재귀 중계와 포트 고갈을 방지합니다. 실행할 때마다 주소를 다시 검사합니다.

## 빌드

`.github/workflows/release.yml`이 공식 출처에서 고정된 버전의 Python 런타임, GhostPCL, Samsung 드라이버를 받아 서명·해시를 검증하고, 중계 rootfs, ZIP, 설치 프로그램을 만듭니다. `v*` 태그를 push하면 설치 파일 하나(`SayScorePDF-Setup.exe`)가 붙은 초안(draft) 릴리스가 만들어집니다. 초안을 공개(Publish)해야 README의 다운로드 버튼이 그 버전을 가리킵니다.

## 요구 사항

- x64 Windows 10 22H2 이상/Windows 11, 또는 ARM64 Windows 11 (하드웨어 가상화 필요)
- WSL 2 (NAT 네트워크 모드, 기본값)
- 최소 4GB RAM
- 최초 프린터 설치 때 관리자 권한
- x64에서는 포함된 Samsung X4305 드라이버 경로를 우선 사용합니다.
- ARM64에서는 ARM64용 드라이버 경로를 별도로 판정하며 x64 드라이버를 사용하지 않습니다.

## 새 PC에서의 한계

WSL 2 기능을 처음 설치할 때는 인터넷과 관리자 승인이 필요하고 재부팅해야 할 수 있습니다. BIOS/UEFI 가상화 활성화나 조직 보안 정책 해제는 설치 프로그램이 대신할 수 없습니다. 관리자 권한이 없는 PC, Windows Server, 32비트 Windows, ARM64 Windows 10, 가상화가 차단된 PC까지 포함한 문자 그대로의 "모든 PC"는 지원할 수 없습니다.

x64와 ARM64 실제 장비 모두에서 설치부터 PDF 출력까지 검증했습니다.

## 데이터 위치

설치판은 `%LOCALAPPDATA%\SayScorePDF`, 포터블 ZIP은 압축을 푼 폴더의 `data`를 씁니다.

- 생성 PDF: `output`
- 원본 작업 및 변환 기록: `jobs`
- 통신 진단 로그: `diagnostics`
- 현재 상태: `runtime-status.json`
- 중계 상태: `relay-runtime.json`

PC에 이미 설치된 다른 프린터나 기본 프린터 설정은 변경하지 않습니다.

## 개인정보

- 인쇄 내용, 변환된 PDF, 진단 로그는 모두 이 PC의 데이터 폴더에만 저장되며 외부로 전송하지 않습니다.
- `diagnostics`의 진단 파일에는 PC의 IP 주소, 프린터·드라이버 정보가 들어 있습니다. 이슈를 올릴 때 첨부하기 전에 내용을 확인하세요.

## 통계

매일 한 번 [stats 워크플로](.github/workflows/stats.yml)가 기록을 갱신합니다. 다운로드 수는 GitHub이 날짜별 기록을 주지 않아 워크플로를 시작한 날부터 쌓입니다.

<img alt="설치 파일 다운로드 추이" src="https://raw.githubusercontent.com/SILVERBRINE/SayScore-PDF-Printer/stats/downloads.svg" width="49%"> <img alt="GitHub Stars 추이" src="https://raw.githubusercontent.com/SILVERBRINE/SayScore-PDF-Printer/stats/stars.svg" width="49%">

## 후원

SayScore PDF는 공익을 위해 무료로 제공됩니다. 개발과 유지에 도움을 주고 싶다면 [GitHub Sponsors](https://github.com/sponsors/SILVERBRINE)로 후원할 수 있습니다. 앱 오른쪽 위의 **♥ 후원하기** 버튼으로도 열 수 있습니다.

## 공식 배포처

SayScore PDF의 공식 배포처는 이 저장소의 [Releases](https://github.com/SILVERBRINE/SayScore-PDF-Printer/releases)뿐입니다. 다른 곳에서 받은 설치 파일은 변조되었을 수 있으니 사용하지 마세요.

## 라이선스

Copyright (C) 2026 SILVERBRINE. SayScore PDF 코드는 [GNU GPL v3](LICENSE) 또는 그 이후 버전으로 배포됩니다. 누구나 자유롭게 쓰고 고치고 다시 배포할 수 있지만, 수정본을 배포할 때는 소스 코드도 같은 라이선스로 공개해야 합니다. 설치 파일에 함께 들어가는 Python, GhostPCL(AGPL-3.0), Samsung 프린터 드라이버 등은 각자의 라이선스를 따릅니다. 자세한 내용은 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 보세요.