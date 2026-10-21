from pathlib import Path
import zipfile

project = Path(__file__).resolve().parents[1]
top = ["README.md", "사용법.txt", "LICENSE", "AGENTS.md", "pyproject.toml", "start.pyw", "SayScore PDF.cmd", ".gitignore"]

def source_files():
    files = [project / name for name in top]
    for directory, extensions in (("easy_output", {".py"}), ("scripts", {".py", ".ps1"}),
                                  ("tests", {".py", ".ps1"}), ("analysis", {".md"})):
        files.extend(path for path in (project / directory).rglob("*")
                     if path.is_file() and path.suffix.lower() in extensions)
    return sorted(set(files))

if __name__ == "__main__":
    destination = project.parent / "sayscore-pdf-source.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in source_files():
            archive.write(source, Path("sayscore-pdf") / source.relative_to(project))
    print(destination)
