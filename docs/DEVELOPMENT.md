# Developer notes

## How it works

The launcher (`SayScorePDF.exe` → `scripts/Bootstrap-SayScore.ps1`) registers a dedicated, lightweight WSL 2 distribution (`SayScore-Relay`, about 17 MB) from bundled per-CPU root filesystems, starts a network relay in it, then starts the app. The distribution does not mount Windows drives or run Windows programs.

The Windows printer queue prints to RAW 9100 / UDP 161 on the WSL 2 address, which is not assigned to Windows, so drivers see a separate network printer. The relay forwards to the app's internal TCP 19100 / UDP 1161 ports; keeping them separate prevents relay loops. The address is re-checked on every launch.

- x64 prefers the bundled Samsung X4305 driver; ARM64 uses the Samsung CLX-9252/9352 ARM64 driver. Microsoft class drivers can be chosen in the app's advanced settings.
- WSL 2 must use NAT networking (the default), not `networkingMode=mirrored`.
- Two relays, chosen with the app's 연결 방식 toggle and saved in `%LOCALAPPDATA%\SayScore PDF\mode.txt` (`simple` or `wsl`). The default (`simple`, also when the file is missing, unless an older WSL relay is already set up) is a Wintun adapter: `easy_output/tunrelay.py` runs as SYSTEM from the `SayScore PDF Relay` scheduled task (`scripts/Install-TunRelay.ps1`, installed copies only), gives Windows `.1` of a free /24, and rewrites packets (`easy_output/tunnat.py`) so a connection to the printer address `.2`:9100 reaches the app on `.1`:19100 from a stand-in peer `.3`, which the engine trusts; Windows' own TCP stack does the rest. SNMP 161 → 1161 likewise. ARM64 PCs run the relay on the bundled native ARM64 Python because the Wintun driver must match Windows. `wsl` uses the WSL relay above; the WSL 2 feature is installed the first time it is chosen.
- `SayScorePDF.exe` shows a startup window until the app's window appears; the startup scripts report their step through the file named in `SAYSCORE_PROGRESS`. `SayScorePDF.exe /restart` waits for the running app to exit first (used by the toggle).

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
- Pushing a `v*` tag also creates a draft release with a single `SayScorePDF-Setup.exe`. Publishing the draft makes the README download button point to it. The version comes from `easy_output/__init__.py` and is also stamped into the installer and `SayScorePDF.exe` file properties.
- `.github/workflows/stats.yml` records daily installer downloads and star history on the `stats` branch.
