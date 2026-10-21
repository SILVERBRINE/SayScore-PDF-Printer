#!/usr/bin/env python3
"""Run the shared protocol engine briefly so Windows diagnostics can probe it."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from easy_output.core import Engine  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--data", type=Path, default=PROJECT / "data")
    parser.add_argument("--ghostpcl", type=Path,
                        default=PROJECT / "vendor" / "ghostpcl-10.08.0-win64" / "gpcl6win64.exe")
    args = parser.parse_args()
    identity = {
        "descr": "Samsung X4305 Series", "name": "SayScore PDF",
        "manufacturer": "Samsung", "model": "Samsung X4305 Series",
        "serial": "SAYSCORE-DIAGNOSTIC", "enterprise": (1, 3, 6, 1, 4, 1, 236),
        "vendor_oids": {
            "1.3.6.1.4.1.236.11.5.1.1.1.26.0": "Samsung X4305 Series",
            "1.3.6.1.4.1.236.11.5.1.1.1.4.0": "SAYSCORE-DIAGNOSTIC",
        },
    }
    engine = Engine(args.data, lambda event: None,
                    ghostpcl=str(args.ghostpcl) if args.ghostpcl.is_file() else None,
                    snmp_enabled=True, snmp_identity=identity)
    try:
        engine.start(args.host, args.port, allow_local_network=True)
        print(f"ready tcp={engine.host}:{engine.port} snmp={engine.snmp_active}", flush=True)
        time.sleep(max(0.1, args.seconds))
    finally:
        engine.stop()


if __name__ == "__main__":
    main()
