"""Build the Windows release (ZIP and installer staging) without user jobs, diagnostics, or caches.

    python scripts/package_release.py               # dist/<zip>
    python scripts/package_release.py --stage DIR   # copy the same files into DIR for Inno Setup
"""
import argparse
from datetime import date
from pathlib import Path
import hashlib
import os
import shutil
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
DESTINATION = PROJECT / "dist" / f"sayscore-pdf-oneclick-windows-{date.today().isoformat()}.zip"
ROOT_FILES = ("README.md", "사용법.txt", "LICENSE", "pyproject.toml",
              "start.pyw", "SayScorePDF.exe", "준비 상태 확인.cmd")
RUNTIME = Path("vendor", "python-x64", "3.13.9")
# Parts of the portable Python runtime the app never loads.
RUNTIME_SKIP = {("Doc",), ("include",), ("libs",), ("Lib", "site-packages"), ("Lib", "ensurepip"),
                ("Lib", "idlelib"), ("Lib", "test"), ("Lib", "tkinter", "test")}
# Build inputs that the release does not need at run time.
VENDOR_SKIP = {("relay-images",), ("ghostpcl-10.08.0-win64.zip",)}
REQUIRED = (Path("SayScorePDF.exe"), RUNTIME / "pythonw.exe", Path("vendor", "ghostpcl-10.08.0-win64", "gpcl6win64.exe"),
            Path("vendor", "drivers", "samsung-x4305-x64", "us015.inf"),
            Path("vendor", "drivers", "samsung-woa-arm64", "prnsacl1.inf"),
            Path("vendor", "relay-rootfs", "sayscore-relay-amd64.tar.gz"),
            Path("vendor", "relay-rootfs", "sayscore-relay-arm64.tar.gz"))


def _skipped(relative: Path) -> bool:
    parts = relative.parts
    if parts[:len(RUNTIME.parts)] == RUNTIME.parts:
        inner = parts[len(RUNTIME.parts):]
        return any(inner[:len(skip)] == skip for skip in RUNTIME_SKIP)
    if parts[0] == "vendor":
        return any(parts[1:1 + len(skip)] == skip for skip in VENDOR_SKIP)
    return False


def included_files():
    for name in ROOT_FILES:
        path = PROJECT / name
        if path.is_file():
            yield path
    for folder in ("easy_output", "scripts", "vendor"):
        root = PROJECT / folder
        if not root.exists():
            continue
        for path in root.rglob("*"):
            relative = path.relative_to(PROJECT)
            if (path.is_file() and "__pycache__" not in relative.parts
                    and path.suffix.lower() not in (".pyc", ".pyo") and not _skipped(relative)):
                yield path


def stage(destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    for path in sorted(set(included_files())):
        target = destination / path.relative_to(PROJECT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    print(destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, help="copy release files into this folder instead of zipping")
    args = parser.parse_args()
    missing = [str(path) for path in REQUIRED if not (PROJECT / path).is_file()]
    if missing:
        raise FileNotFoundError("Missing release inputs (see .github/workflows/release.yml): "
                                + ", ".join(missing))
    if args.stage:
        stage(args.stage.resolve())
        return
    DESTINATION.parent.mkdir(exist_ok=True)
    temporary = DESTINATION.with_suffix(DESTINATION.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as archive:
        for directory in ("data/inbox/", "data/jobs/", "data/output/", "data/diagnostics/",
                          "data/communication/"):
            archive.writestr(directory, b"")
        for path in sorted(set(included_files())):
            archive.write(path, path.relative_to(PROJECT))
    os.replace(temporary, DESTINATION)
    digest = hashlib.sha256(DESTINATION.read_bytes()).hexdigest().upper()
    print(DESTINATION)
    print(f"{DESTINATION.stat().st_size} bytes  SHA-256 {digest}")


if __name__ == "__main__":
    main()
