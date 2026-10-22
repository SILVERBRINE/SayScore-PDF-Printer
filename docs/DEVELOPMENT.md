# Developer notes

## How it works

The launcher (`SayScorePDF.exe` → `scripts/Bootstrap-SayScore.ps1`) registers a dedicated, lightweight WSL 2 distribution (`SayScore-Relay`, about 17 MB) from bundled per-CPU root filesystems, starts a network relay in it, then starts the app. The distribution does not mount Windows drives or run Windows programs.

The Windows printer queue prints to RAW 9100 / UDP 161 on the WSL 2 address, which is not assigned to Windows, so drivers see a separate network printer. The relay forwards to the app's internal TCP 19100 / UDP 1161 ports; keeping them separate prevents relay loops. The address is re-checked on every launch.

- x64 prefers the bundled Samsung X4305 driver; ARM64 uses the Samsung CLX-9252/9352 ARM64 driver. Microsoft class drivers can be chosen in the app's advanced settings.
- WSL 2 must use NAT networking (the default), not `networkingMode=mirrored`.
- Simple mode (chosen on first launch, saved in `%LOCALAPPDATA%\SayScore PDF\mode.txt`, or offered when the relay fails) skips WSL: without `relay-runtime.json` the app listens on this PC's own private IPv4 address on 9100 and the printer port targets it directly. The app shows a warning banner in this mode. The installer itself never installs WSL; the first launch asks.

## Data

The installed app uses `%LOCALAPPDATA%\SayScorePDF`; the portable ZIP uses `data` next to it.

| Path | Contents |
| --- | --- |
| `output` | Converted PDFs |
| `jobs` | Original jobs and conversion records |
| `diagnostics` | Communication diagnostics (contain IP addresses and printer details; review before sharing) |
| `runtime-status.json`, `relay-runtime.json` | App and relay status |

## Build and release

`.github/workflows/release.yml` downloads pinned versions of the Python runtime, GhostPCL and the Samsung drivers from their official sources, verifies signatures and hashes, and builds the relay root filesystems, the portable ZIP and the Inno Setup installer.

- Every push builds the ZIP and installer as workflow artifacts.
- Pushing a `v*` tag also creates a draft release with a single `SayScorePDF-Setup.exe`. Publishing the draft makes the README download button point to it.
- `.github/workflows/stats.yml` records daily installer downloads and star history on the `stats` branch.
