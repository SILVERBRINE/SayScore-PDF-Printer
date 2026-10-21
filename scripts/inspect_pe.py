#!/usr/bin/env python3
"""List PE architecture, imports, and exports without third-party packages."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct


def inspect(path: Path):
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("not a PE image")
    machine, sections = struct.unpack_from("<HH", data, pe + 4)
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    if magic not in (0x10B, 0x20B):
        raise ValueError(f"unsupported optional header {magic:#x}")
    directory = optional + (96 if magic == 0x10B else 112)
    section_table = optional + optional_size
    section_rows = []
    for index in range(sections):
        base = section_table + index * 40
        name = data[base:base + 8].rstrip(b"\0").decode("ascii", "replace")
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from("<IIII", data, base + 8)
        section_rows.append((name, virtual_address, max(virtual_size, raw_size), raw_offset))

    def offset(rva):
        for _, address, size, raw in section_rows:
            if address <= rva < address + size:
                return raw + rva - address
        if rva < len(data):
            return rva
        raise ValueError(f"RVA outside image: {rva:#x}")

    def cstring(at):
        end = data.index(0, at)
        return data[at:end].decode("ascii", "replace")

    export_rva, _ = struct.unpack_from("<II", data, directory)
    import_rva, _ = struct.unpack_from("<II", data, directory + 8)
    exports = []
    if export_rva:
        e = offset(export_rva)
        _, _, _, _, _, base, number_functions, number_names, functions_rva, names_rva, ordinals_rva = struct.unpack_from("<IIHHIIIIIII", data, e)
        names_at, ordinals_at = offset(names_rva), offset(ordinals_rva)
        functions_at = offset(functions_rva)
        for index in range(number_names):
            name_rva = struct.unpack_from("<I", data, names_at + index * 4)[0]
            ordinal_index = struct.unpack_from("<H", data, ordinals_at + index * 2)[0]
            function_rva = struct.unpack_from("<I", data, functions_at + ordinal_index * 4)[0]
            exports.append({"name": cstring(offset(name_rva)), "ordinal": base + ordinal_index,
                            "rva": function_rva})
    imports = []
    if import_rva:
        descriptor = offset(import_rva)
        thunk_size = 4 if magic == 0x10B else 8
        ordinal_mask = 1 << (31 if thunk_size == 4 else 63)
        while True:
            original, _, _, name_rva, first = struct.unpack_from("<IIIII", data, descriptor)
            if not any((original, name_rva, first)):
                break
            names = []
            thunk = offset(original or first)
            while True:
                value = int.from_bytes(data[thunk:thunk + thunk_size], "little")
                if not value:
                    break
                if value & ordinal_mask:
                    names.append(f"ordinal:{value & 0xffff}")
                else:
                    names.append(cstring(offset(value) + 2))
                thunk += thunk_size
            imports.append({"dll": cstring(offset(name_rva)), "functions": names})
            descriptor += 20
    return {"path": str(path.resolve()), "machine": {0x14C: "x86", 0x8664: "x64", 0xAA64: "ARM64"}.get(machine, hex(machine)),
            "pe_format": "PE32" if magic == 0x10B else "PE32+", "imports": imports,
            "exports": exports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="+")
    args = parser.parse_args()
    print(json.dumps([inspect(path) for path in args.paths], indent=2))


if __name__ == "__main__":
    main()
