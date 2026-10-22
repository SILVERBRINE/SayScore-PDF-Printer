# Third-party components

SayScore PDF's own code is licensed under GPL-3.0-or-later (see `LICENSE`). The Windows installer and
portable ZIP also bundle the components below, unmodified, under their own licenses.
The build (`.github/workflows/release.yml`) downloads each one from the source listed.

| Component | Version | License | Source |
| --- | --- | --- | --- |
| Python (Windows x64 runtime) | 3.13.9 | PSF License 2.0 (`vendor/python-x64/3.13.9/LICENSE.txt`) | https://www.python.org/ftp/python/3.13.9/ |
| GhostPCL | 10.08.0 | GNU AGPL-3.0 (`vendor/ghostpcl-10.08.0-win64/LICENSE`) | Binaries and source: https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/tag/gs10080 |
| Samsung X4305 / CLX-9252 9352 printer drivers | see `vendor/drivers/SOURCES.md` | Samsung/HP proprietary driver terms | https://downloadcenter.samsung.com (exact archives and SHA-256 in `vendor-sources/drivers-SOURCES.md`) |
| Relay root filesystem (`python:3.12-alpine` image: Alpine Linux, BusyBox, musl, Python 3.12) | as built by `tools/relay/Dockerfile` | Per package, including GPL-2.0 (BusyBox), MIT (musl), PSF (Python) | https://hub.docker.com/_/python, package sources at https://gitlab.alpinelinux.org/alpine/aports |
| Wintun | 0.14.1 | Wintun prebuilt-binaries license, unmodified redistribution (`vendor/wintun/LICENSE.txt`) | https://www.wintun.net/builds/wintun-0.14.1.zip (signed by WireGuard LLC) |

GhostPCL runs as a separate program (`gpcl6win64.exe`) to convert print jobs; SayScore PDF does
not link to it. Its complete corresponding source is available at the link above.
