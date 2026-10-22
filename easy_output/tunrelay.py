"""Simple-mode relay: a Wintun adapter whose printer address Windows does not own.

Runs as SYSTEM from the "SayScore PDF Relay" scheduled task
(scripts/Install-TunRelay.ps1):

    pythonw -m easy_output.tunrelay

It creates the "SayScore PDF" adapter, gives Windows the host address of a free
/24, allows the app's capture ports from the stand-in peer in the firewall,
writes %ProgramData%\\SayScorePDF\\tun-relay.json for the app, and then rewrites
packets with easy_output.tunnat until it is stopped.
"""
from __future__ import annotations

import ctypes
import ipaddress
import json
import os
import platform
import socket
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path

from .tunnat import translate

PROJECT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "SayScorePDF"
STATE = STATE_DIR / "tun-relay.json"
LOG = STATE_DIR / "tun-relay.log"
ADAPTER = "SayScore PDF"
# Fixed so Windows keeps treating it as the same adapter across restarts.
ADAPTER_GUID = uuid.UUID("5e1b6d0c-58a4-4f6e-9a3e-53a7c0d1f2b4")
CANDIDATES = ("10.254.91.0/24", "10.253.47.0/24", "172.31.251.0/24", "192.168.251.0/24")
FIREWALL_GROUP = "SayScore PDF"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ERROR_NO_MORE_ITEMS = 259


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, value: uuid.UUID) -> "GUID":
        raw = value.bytes_le
        return cls(int.from_bytes(raw[0:4], "little"), int.from_bytes(raw[4:6], "little"),
                   int.from_bytes(raw[6:8], "little"), (ctypes.c_ubyte * 8)(*raw[8:16]))


def log(message: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 512 * 1024:
            LOG.replace(LOG.with_suffix(".old.log"))
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")
    except OSError:
        pass


def powershell(script: str) -> str:
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            creationflags=NO_WINDOW, timeout=120)
    if result.returncode:
        raise RuntimeError(f"PowerShell failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


class Wintun:
    def __init__(self):
        # The DLL must match this process: the bundled x64 runtime loads amd64, also under ARM64 emulation.
        arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "amd64"
        dll = ctypes.WinDLL(str(PROJECT / "vendor" / "wintun" / arch / "wintun.dll"), use_last_error=True)
        handle, dword = ctypes.c_void_p, wintypes.DWORD
        signatures = {
            "WintunCreateAdapter": (handle, [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(GUID)]),
            "WintunCloseAdapter": (None, [handle]),
            "WintunGetAdapterLUID": (None, [handle, ctypes.POINTER(ctypes.c_uint64)]),
            "WintunStartSession": (handle, [handle, dword]),
            "WintunEndSession": (None, [handle]),
            "WintunGetReadWaitEvent": (wintypes.HANDLE, [handle]),
            "WintunReceivePacket": (ctypes.c_void_p, [handle, ctypes.POINTER(dword)]),
            "WintunReleaseReceivePacket": (None, [handle, ctypes.c_void_p]),
            "WintunAllocateSendPacket": (ctypes.c_void_p, [handle, dword]),
            "WintunSendPacket": (None, [handle, ctypes.c_void_p]),
        }
        for name, (restype, argtypes) in signatures.items():
            function = getattr(dll, name)
            function.restype, function.argtypes = restype, argtypes
        self.dll = dll

    def create(self):
        guid = GUID.of(ADAPTER_GUID)
        adapter = self.dll.WintunCreateAdapter(ADAPTER, "SayScore", ctypes.byref(guid))
        if not adapter:
            raise ctypes.WinError(ctypes.get_last_error())
        luid = ctypes.c_uint64()
        self.dll.WintunGetAdapterLUID(adapter, ctypes.byref(luid))
        index = wintypes.ULONG()
        error = ctypes.WinDLL("iphlpapi").ConvertInterfaceLuidToIndex(ctypes.byref(luid), ctypes.byref(index))
        if error:
            raise ctypes.WinError(error)
        return adapter, index.value


def pick_subnet(index: int) -> ipaddress.IPv4Network:
    """The first candidate /24 that no other interface uses or routes to."""
    routes = json.loads(powershell(
        f"@(Get-NetRoute -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
        f"Where-Object InterfaceIndex -ne {index} | ForEach-Object DestinationPrefix) | ConvertTo-Json") or "[]")
    taken = []
    for prefix in routes if isinstance(routes, list) else [routes]:
        network = ipaddress.ip_network(prefix, strict=False)
        if network.prefixlen and not network.is_multicast and network.prefixlen < 32:
            taken.append(network)
    previous = None
    try:
        previous = json.loads(STATE.read_text(encoding="utf-8")).get("subnet")
    except (OSError, ValueError, AttributeError):
        pass
    ordered = ([previous] if previous in CANDIDATES else []) + [c for c in CANDIDATES if c != previous]
    for candidate in ordered:
        network = ipaddress.ip_network(candidate)
        if not any(network.overlaps(other) for other in taken):
            return network
    raise RuntimeError("사용할 수 있는 사설 주소 대역이 없습니다: " + ", ".join(CANDIDATES))


def configure(index: int, host: str, peer: str, prefix: int) -> None:
    powershell(f"""
$ErrorActionPreference = 'Stop'
Get-NetIPAddress -InterfaceIndex {index} -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object IPAddress -ne '{host}' | Remove-NetIPAddress -Confirm:$false
if (-not (Get-NetIPAddress -InterfaceIndex {index} -IPAddress '{host}' -ErrorAction SilentlyContinue)) {{
    New-NetIPAddress -InterfaceIndex {index} -IPAddress '{host}' -PrefixLength {prefix} | Out-Null
}}
Set-NetIPInterface -InterfaceIndex {index} -InterfaceMetric 9000
Get-NetFirewallRule -Group '{FIREWALL_GROUP}' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
foreach ($p in @(@('TCP', 19100), @('UDP', 1161))) {{
    New-NetFirewallRule -DisplayName "SayScore PDF relay ($($p[0]))" -Group '{FIREWALL_GROUP}' -Direction Inbound `
        -Protocol $p[0] -LocalAddress '{host}' -LocalPort $p[1] -RemoteAddress '{peer}' -Action Allow -Profile Any | Out-Null
}}
for ($i = 0; $i -lt 50; $i++) {{
    if ((Get-NetIPAddress -InterfaceIndex {index} -IPAddress '{host}' -ErrorAction SilentlyContinue).AddressState -eq 'Preferred') {{ break }}
    Start-Sleep -Milliseconds 200
}}
""")


def write_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(STATE)


def run() -> None:
    wintun = Wintun()
    adapter, index = wintun.create()
    session = None
    try:
        network = pick_subnet(index)
        host, target, peer = (str(network.network_address + n) for n in (1, 2, 3))
        configure(index, host, peer, network.prefixlen)
        session = wintun.dll.WintunStartSession(adapter, 0x400000)
        if not session:
            raise ctypes.WinError(ctypes.get_last_error())
        state = {"schema": 1, "subnet": str(network), "capture_address": host, "relay_address": target,
                 "peer_address": peer, "interface_index": index, "pid": os.getpid()}
        log(f"relay up · {target} -> {host} (peer {peer}, interface {index})")
        h, t, p = (socket.inet_aton(a) for a in (host, target, peer))
        event = wintun.dll.WintunGetReadWaitEvent(session)
        wait = ctypes.windll.kernel32.WaitForSingleObject
        wait.argtypes, wait.restype = [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD
        size = wintypes.DWORD()
        beat = 0.0
        while True:
            now = time.time()
            if now - beat >= 10:
                state["updated"] = int(now)
                write_state(state)
                beat = now
            pointer = wintun.dll.WintunReceivePacket(session, ctypes.byref(size))
            if not pointer:
                error = ctypes.get_last_error()
                if error != ERROR_NO_MORE_ITEMS:
                    raise ctypes.WinError(error)
                wait(event, 1000)
                continue
            packet = ctypes.string_at(pointer, size.value)
            wintun.dll.WintunReleaseReceivePacket(session, pointer)
            reply = translate(packet, h, t, p)
            if reply is None:
                continue
            out = wintun.dll.WintunAllocateSendPacket(session, len(reply))
            if out:
                ctypes.memmove(out, reply, len(reply))
                wintun.dll.WintunSendPacket(session, out)
    finally:
        if session:
            wintun.dll.WintunEndSession(session)
        wintun.dll.WintunCloseAdapter(adapter)


def main() -> int:
    try:
        run()
    except Exception as exc:  # the scheduled task restarts us; leave a trace for diagnostics
        log(f"relay stopped: {exc!r}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
