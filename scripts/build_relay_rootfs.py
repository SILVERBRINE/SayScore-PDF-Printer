"""Flatten the bundled relay container images into WSL-importable root filesystems.

The relay runs in its own WSL 2 distribution instead of Docker Desktop.  The
Windows printer port still targets the WSL VM address, which is not assigned to
Windows, so the network topology the drivers see is unchanged.
"""
from __future__ import annotations

import gzip
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

PROJECT = Path(__file__).resolve().parents[1]
IMAGES = PROJECT / "vendor" / "relay-images"
OUTPUT = PROJECT / "vendor" / "relay-rootfs"
RELAY_SOURCE = PROJECT / "tools" / "network_relay.py"
RELAY_VERSION = "6-wsl"
PYTHON = "usr/local/bin/python3"

# The relay needs no Windows drives, Windows executables, or login user.
WSL_CONF = """\
[automount]
enabled = false
mountFsTab = false

[interop]
enabled = false
appendWindowsPath = false

[user]
default = root
"""


def _normalize(name: str) -> str:
    path = PurePosixPath(name.lstrip("/"))
    parts = [part for part in path.parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValueError(f"Unsafe layer path: {name}")
    return "/".join(parts)


def _remove_tree(entries: dict, prefix: str, keep_root: bool) -> None:
    for key in [key for key in entries if key == prefix or key.startswith(prefix + "/")]:
        if keep_root and key == prefix:
            continue
        del entries[key]


def flatten(image: Path) -> dict[str, tuple[tarfile.TarInfo, bytes | None]]:
    entries: dict[str, tuple[tarfile.TarInfo, bytes | None]] = {}
    with tarfile.open(image) as outer:
        manifest = json.load(outer.extractfile("manifest.json"))
        if len(manifest) != 1:
            raise ValueError(f"{image.name}: expected exactly one image")
        for layer_name in manifest[0]["Layers"]:
            data = outer.extractfile(layer_name).read()
            with tarfile.open(fileobj=io.BytesIO(data)) as layer:
                for member in layer.getmembers():
                    name = _normalize(member.name)
                    if not name:
                        continue
                    parent, _, base = name.rpartition("/")
                    if base == ".wh..wh..opq":
                        _remove_tree(entries, parent, keep_root=True)
                        continue
                    if base.startswith(".wh."):
                        _remove_tree(entries, f"{parent}/{base[4:]}".lstrip("/"), keep_root=False)
                        continue
                    if member.islnk():
                        member.linkname = _normalize(member.linkname)
                    member.name = name
                    content = layer.extractfile(member).read() if member.isfile() else None
                    if name in entries and not member.isdir():
                        del entries[name]  # re-add after any hard link targets it now replaces
                    entries[name] = (member, content)
    return entries


def _add_file(entries: dict, name: str, content: bytes, mode: int = 0o644) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.uid, info.gid = len(content), mode, 0, 0
    entries.pop(name, None)
    entries[name] = (info, content)


def build(architecture: str) -> Path:
    image = IMAGES / f"sayscore-network-relay-{architecture}.tar"
    entries = flatten(image)
    if PYTHON not in entries:
        raise ValueError(f"{image.name}: {PYTHON} missing from image")
    _add_file(entries, "relay/network_relay.py", RELAY_SOURCE.read_bytes())
    _add_file(entries, "etc/wsl.conf", WSL_CONF.encode("ascii"))
    _add_file(entries, "etc/sayscore-relay-version", (RELAY_VERSION + "\n").encode("ascii"))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT / f"sayscore-relay-{architecture}.tar.gz"
    temporary = destination.with_suffix(".tmp")
    with gzip.GzipFile(temporary, "wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for info, content in entries.values():
                archive.addfile(info, io.BytesIO(content) if content is not None else None)
    temporary.replace(destination)
    return destination


def main() -> None:
    for architecture in ("amd64", "arm64"):
        print(build(architecture))


if __name__ == "__main__":
    main()
