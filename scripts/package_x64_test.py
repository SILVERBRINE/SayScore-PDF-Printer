from pathlib import Path
import runpy
import struct
import zipfile

project = Path(__file__).resolve().parents[1]
runtime = project / 'vendor' / 'python-x64' / '3.13.9'
for name in ('python.exe', 'pythonw.exe', 'python313.dll'):
    contents = (runtime / name).read_bytes()
    offset = struct.unpack_from('<I', contents, 0x3c)[0]
    if contents[offset:offset + 4] != b'PE\0\0' or struct.unpack_from('<H', contents, offset + 4)[0] != 0x8664:
        raise ValueError(f'Expected AMD64 portable runtime: {name}')
if not (runtime / 'LICENSE.txt').is_file():
    raise FileNotFoundError('Python upstream license is required')
source_files = runpy.run_path(str(project / 'scripts' / 'package_source.py'))['source_files']
destination = project.parent / 'sayscore-pdf-oneclick.zip'
prefix = Path('SayScore PDF')
SKIP = {('Doc',), ('include',), ('libs',), ('Lib', 'site-packages'), ('Lib', 'ensurepip'),
        ('Lib', 'idlelib'), ('Lib', 'test'), ('Lib', 'tkinter', 'test')}

def bundled(path):
    parts = path.relative_to(runtime).parts
    return not any(parts[:len(skip)] == skip for skip in SKIP)

with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in source_files():
        archive.write(path, prefix / path.relative_to(project))
    for path in sorted(runtime.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc' and bundled(path):
            archive.write(path, prefix / 'vendor' / 'python-x64' / '3.13.9' / path.relative_to(runtime))
    drivers = project / 'vendor' / 'drivers'
    for name in ('samsung-x4305-x64/us015.inf', 'samsung-woa-arm64/prnsacl1.inf', 'SOURCES.md'):
        if not (drivers / name).is_file():
            raise FileNotFoundError(f'Bundled driver file missing: {name}')
    for path in sorted(drivers.rglob('*')):
        if path.is_file():
            archive.write(path, prefix / path.relative_to(project))
print(destination)
