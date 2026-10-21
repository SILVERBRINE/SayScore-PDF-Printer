"""Build the Windows one-click ZIP without user jobs, diagnostics, or caches."""
from pathlib import Path
import os
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
DESTINATION = PROJECT.parent / "sayscore-pdf-oneclick-windows-2026-10-21.zip"
ROOT_FILES = ("README.md", "사용법.txt", "LICENSE", "AGENTS.md", "pyproject.toml",
              "start.pyw", "SayScore PDF.cmd", "준비 상태 확인.cmd", ".gitignore")


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
                    and path.suffix.lower() not in (".pyc", ".pyo")):
                yield path
    for name in ("tools/network_relay.py", "tools/relay/Dockerfile"):
        path = PROJECT / name
        if path.is_file():
            yield path


def main():
    temporary = DESTINATION.with_suffix(DESTINATION.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as archive:
        for directory in ("data/inbox/", "data/jobs/", "data/output/", "data/diagnostics/",
                          "data/communication/"):
            archive.writestr(directory, b"")
        for path in sorted(set(included_files())):
            archive.write(path, path.relative_to(PROJECT))
    os.replace(temporary, DESTINATION)
    print(DESTINATION)


if __name__ == "__main__":
    main()
