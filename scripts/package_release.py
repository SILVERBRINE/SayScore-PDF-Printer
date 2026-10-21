"""Build the Windows one-click ZIP without user jobs, diagnostics, or caches."""
from datetime import date
from pathlib import Path
import hashlib
import os
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
DESTINATION = PROJECT / "dist" / f"sayscore-pdf-oneclick-windows-{date.today().isoformat()}.zip"
ROOT_FILES = ("README.md", "사용법.txt", "LICENSE", "pyproject.toml",
              "start.pyw", "SayScore PDF.cmd", "준비 상태 확인.cmd")
RUNTIME = Path("vendor", "python-x64", "3.13.9")
# Parts of the portable Python runtime the app never loads.
RUNTIME_SKIP = {("Doc",), ("include",), ("libs",), ("Lib", "site-packages"), ("Lib", "ensurepip"),
                ("Lib", "idlelib"), ("Lib", "test"), ("Lib", "tkinter", "test")}
# Build inputs that the release does not need at run time.
VENDOR_SKIP = {("relay-images",), ("ghostpcl-10.08.0-win64.zip",)}
REQUIRED = (RUNTIME / "pythonw.exe", Path("vendor", "ghostpcl-10.08.0-win64", "gpcl6win64.exe"),
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


def main():
    missing = [str(path) for path in REQUIRED if not (PROJECT / path).is_file()]
    if missing:
        raise FileNotFoundError("Missing release inputs (run scripts/build_relay_rootfs.py first?): "
                                + ", ".join(missing))
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
