from __future__ import annotations

import argparse
import atexit
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .core import Engine
from .diagnostics import (address_change_notice, choose_endpoint, find_converter,
                          owned_queues, printer_inventory, OWNER_COMMENT, QUEUE_NAME,
                          SITE_REGISTRATION_HELP)
from .network import local_ipv4_addresses
from .health import queue_health

PROJECT = Path(__file__).resolve().parent.parent
SETUP_DRIVER = "Microsoft PCL6 Class Driver"
PROJECT_URL = "https://github.com/SILVERBRINE/SayScore-PDF-Printer"
SPONSOR_URL = "https://github.com/sponsors/SILVERBRINE"
SAMSUNG_DRIVER = "Samsung CLX-9252 9352 Series PCL6 Class Driver"
X64_DRIVER = "Samsung X4305 Series"
LOCAL_DRIVERS = ("HP Universal Printing PCL 6", "Microsoft PCL6 Class Driver", "Microsoft PS Class Driver", SAMSUNG_DRIVER)
LABELS = {"queued": "대기", "receiving": "수신 중", "processing": "변환 중",
          "completed": "✔ 저장됨", "failed": "⚠ 확인 필요"}
FONT = "Malgun Gothic"
FONT_CANDIDATES = ("Malgun Gothic", "맑은 고딕", "Segoe UI", "Arial")
# SayScore brand: theme #6d4aff, purple gradient #3d2bd4 → #9a5cf7, teal-cyan accents.
BG, CARD, INK, MUTED = "#f6f5ff", "#ffffff", "#1b1840", "#5d5a7a"
ACCENT, ACCENT_DARK, ACCENT_SOFT, ACCENT_INK = "#6d4aff", "#4f32e0", "#efeaff", "#4b2bc6"
GRADIENT = ("#4f32e0", "#9a5cf7")
GOOD, WAIT, BAD = "#0e9f93", "#b7791f", "#d64562"
SOFT = {GOOD: "#e2f7f3", WAIT: "#fdf3e1", BAD: "#fdebef"}
LINE, FOCUS = "#e6e2f7", "#c5baff"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def choose_font(root) -> str:
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families(root))
    except Exception:
        return FONT
    for family in FONT_CANDIDATES:
        if family in available:
            return family
    return FONT
DEFAULT_RECEIVE_RATE = 256 * 1024
MAX_RECEIVE_RATE = 64 * 1024 * 1024
RELAY_CAPTURE_RAW_PORT = 19100
RELAY_CAPTURE_SNMP_PORT = 1161

def clean_queue_name(value) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name or len(name) > 220 or any(ch in name for ch in "!,\\/"):
        return None
    return name

def clean_receive_rate(value, default: int) -> int:
    try:
        rate = int(value)
    except (TypeError, ValueError):
        return default
    if rate <= 0:
        return 0
    return min(rate, MAX_RECEIVE_RATE)

def relay_route(data: Path, addresses: list[str]) -> tuple[str, str]:
    """Return the local capture address and separate printer-facing relay."""
    try:
        state = json.loads((data / "relay-runtime.json").read_text(encoding="utf-8"))
        capture = str(state.get("capture_address") or "")
        relay = str(state.get("relay_address") or "")
        capture_ip = ipaddress.ip_address(capture)
        relay_ip = ipaddress.ip_address(relay)
        if (capture not in addresses or capture_ip.version != 4 or not capture_ip.is_private
                or relay_ip.version != 4 or not relay_ip.is_private or relay_ip.is_loopback
                or relay in addresses or relay == capture):
            return "", ""
        return capture, relay
    except (OSError, ValueError, TypeError, AttributeError):
        return "", ""

def relay_peer(data: Path) -> str:
    """The simple-mode relay's stand-in sender, which the engine must accept."""
    try:
        state = json.loads((data / "relay-runtime.json").read_text(encoding="utf-8"))
        peer = ipaddress.ip_address(str(state.get("peer_address") or ""))
    except (OSError, ValueError, TypeError, AttributeError):
        return ""
    return str(peer) if state.get("mode") == "tun" and peer.version == 4 and peer.is_private else ""

def snmp_identity_from_config(config: dict, inventory: dict | None = None) -> dict:
    name = config.get("queue_name") or QUEUE_NAME
    driver = (owned_queue_driver(inventory) if inventory else None) or name
    serial_seed = f"{socket.gethostname()}|{driver}".encode("utf-8", "replace")
    identity = {"descr": f"SayScore PDF; compatible driver: {driver}", "name": name,
                "manufacturer": "SayScore", "model": "SayScore PDF",
                "serial": "SS" + hashlib.sha256(serial_seed).hexdigest()[:14].upper()}
    if "samsung" in driver.lower():
        if "x4305" in driver.lower():
            # These two x64 Type-3 driver queries are named MDL and
            # Printer serialNo in itdrvn.dll.  Values identify SayScore
            # honestly; the Samsung enterprise and model identity are not
            # claimed.  The adjacent EXT value remains unknown.
            identity["vendor_oids"] = {
                "1.3.6.1.4.1.236.11.5.1.1.1.26.0": identity["model"],
                "1.3.6.1.4.1.236.11.5.1.1.1.4.0": identity["serial"],
            }
        elif "9252" in driver or "9352" in driver:
            # ARM64 uses the Type-4 Bidi schema in saactcpip.xml rather than
            # the x64 Type-3 SNMP DLL.  Scalar instances use the SNMP .0
            # suffix; values mirror the explicit schema and its ready state.
            host = str(config.get("host") or "")
            identity["vendor_oids"] = {
                "1.3.6.1.4.1.236.11.5.1.12.2.5.0": host,
                "1.3.6.1.4.1.236.11.5.11.53.51.11.2.1.0": host,
                "1.3.6.1.4.1.236.11.5.11.53.51.11.2.2.0": "",
                "1.3.6.1.4.1.236.11.5.11.53.31.1.116.0": "00010001",
            }
        else:
            identity["model"] = driver
    return identity

def open_path(path: Path):
    if sys.platform == "win32":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])

def owned_queue(inventory: dict) -> dict | None:
    matches = owned_queues(inventory)
    return matches[0] if len(matches) == 1 else None

def owned_queue_driver(inventory: dict) -> str | None:
    queue = owned_queue(inventory)
    return queue.get("driver") if queue else None

def owned_queue_name(inventory: dict) -> str | None:
    queue = owned_queue(inventory)
    return queue.get("name") if queue else None

def setup_driver(inventory: dict) -> str:
    if owned_queue_driver(inventory) == SAMSUNG_DRIVER:
        return SAMSUNG_DRIVER
    return SETUP_DRIVER

def samsung_x64_registered() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    key = (r"SYSTEM\CurrentControlSet\Control\Print\Environments\Windows x64"
           r"\Drivers\Version-3" + "\\" + X64_DRIVER)
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key))
        return True
    except OSError:
        return False

BUNDLED_DRIVERS = {"AMD64": PROJECT / "vendor" / "drivers" / "samsung-x4305-x64" / "us015.inf",
                   "ARM64": PROJECT / "vendor" / "drivers" / "samsung-woa-arm64" / "prnsacl1.inf"}

def bundled_samsung(native_arch: str) -> bool:
    path = BUNDLED_DRIVERS.get(native_arch)
    return bool(path and path.is_file())

DRIVER_LABELS = {
    X64_DRIVER: "Samsung X4305 (동봉 · 실제 프린터 드라이버)",
    SAMSUNG_DRIVER: "Samsung CLX-9252/9352 (동봉 · 실제 프린터 드라이버)",
    "Microsoft PCL6 Class Driver": "Microsoft PCL6 Class Driver (Windows 기본)",
    "Microsoft PS Class Driver": "Microsoft PS Class Driver (Windows 기본 · Ghostscript 설치 필요)",
    "HP Universal Printing PCL 6": "HP Universal Printing PCL 6 (HP 드라이버가 설치된 PC만)",
}
AUTO_DRIVER_LABEL = "자동 (권장)"

def driver_options(native_arch: str) -> list[str]:
    """Drivers the user may pick for the SayScore queue on this architecture."""
    if native_arch == "AMD64":
        return [X64_DRIVER, "Microsoft PCL6 Class Driver", "Microsoft PS Class Driver",
                "HP Universal Printing PCL 6"]
    if native_arch == "ARM64":
        return [SAMSUNG_DRIVER, "Microsoft PCL6 Class Driver", "Microsoft PS Class Driver"]
    return []

def setup_choice(inventory: dict, native_arch: str, samsung_x64: bool | None = None,
                 bundled: bool | None = None, preferred: str | None = None) -> tuple[str, str]:
    if preferred and preferred in driver_options(native_arch):
        if preferred == X64_DRIVER:
            return "Install-X64Printer.ps1", X64_DRIVER
        return "Install-LocalPrinter.ps1", preferred
    owned = owned_queue_driver(inventory)
    if bundled is None:
        bundled = bundled_samsung(native_arch)
    if native_arch == "AMD64":
        if samsung_x64 is None:
            samsung_x64 = samsung_x64_registered()
        if owned == X64_DRIVER or (owned is None and (samsung_x64 or bundled)):
            return "Install-X64Printer.ps1", X64_DRIVER
        return "Install-LocalPrinter.ps1", owned if owned in LOCAL_DRIVERS and owned != SAMSUNG_DRIVER else SETUP_DRIVER
    if bundled and (owned is None or owned in LOCAL_DRIVERS):
        return "Install-LocalPrinter.ps1", SAMSUNG_DRIVER
    return "Install-LocalPrinter.ps1", setup_driver(inventory)

def native_windows_arch() -> str:
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.IsWow64Process2.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort), ctypes.POINTER(ctypes.c_ushort)]
    kernel.IsWow64Process2.restype = ctypes.c_int
    process_machine, native_machine = ctypes.c_ushort(), ctypes.c_ushort()
    if not kernel.IsWow64Process2(kernel.GetCurrentProcess(), ctypes.byref(process_machine), ctypes.byref(native_machine)):
        raise OSError(ctypes.get_last_error(), "실제 Windows 아키텍처를 확인하지 못했습니다.")
    architecture = native_machine.value
    if architecture == 0x8664:
        return "AMD64"
    if architecture == 0xaa64:
        return "ARM64"
    raise ValueError(f"지원되지 않는 실제 Windows 아키텍처입니다: {architecture}")

def available_driver_options() -> list[str]:
    try:
        return driver_options(native_windows_arch())
    except (OSError, ValueError, AttributeError):
        return []

def blend(start: str, end: str, t: float) -> str:
    a, b = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (start, end))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class GradientStrip(tk.Canvas):
    """A thin brand-gradient bar across the top of a card."""

    def __init__(self, parent, height):
        super().__init__(parent, height=height, bg=CARD, highlightthickness=0, bd=0)
        self.bind("<Configure>", self._draw)

    def _draw(self, event):
        self.delete("all")
        steps = max(1, event.width // 4)
        for i in range(steps):
            x0, x1 = event.width * i / steps, event.width * (i + 1) / steps + 1
            color = blend(*GRADIENT, i / max(1, steps - 1))
            self.create_rectangle(x0, 0, x1, event.height, fill=color, outline=color)


class GradientButton(tk.Canvas):
    """Rounded primary button in the SayScore gradient; configure(text=, state=) like ttk."""

    def __init__(self, parent, text, command, font, scale=1.0):
        super().__init__(parent, bg=CARD, highlightthickness=0, bd=0, takefocus=1, cursor="hand2")
        import tkinter.font as tkfont
        self._font, self._command, self._scale = font, command, scale
        self._metrics = tkfont.Font(root=parent, font=font)
        self._text, self._state, self._hover, self._focus = text, "normal", False, False
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False))
        self.bind("<FocusIn>", lambda e: self._set(focus=True))
        self.bind("<FocusOut>", lambda e: self._set(focus=False))
        self.bind("<ButtonRelease-1>", self._invoke)
        for key in ("<Return>", "<space>"):
            self.bind(key, self._invoke)
        self._draw()

    def configure(self, cnf=None, **kw):
        if "text" in kw:
            self._text = kw.pop("text")
        if "state" in kw:
            self._state = kw.pop("state")
            super().configure(cursor="hand2" if self._state == "normal" else "arrow")
        if cnf or kw:
            super().configure(cnf, **kw)
        self._draw()

    config = configure

    def _set(self, hover=None, focus=None):
        if hover is not None:
            self._hover = hover
        if focus is not None:
            self._focus = focus
        self._draw()

    def _invoke(self, _event=None):
        if self._state == "normal":
            self._command()

    def _draw(self):
        s = self._scale
        width = self._metrics.measure(self._text) + int(48 * s)
        height = self._metrics.metrics("linespace") + int(24 * s)
        super().configure(width=width, height=height)
        self.delete("all")
        radius = height / 2
        enabled = self._state == "normal"
        start, end = GRADIENT if enabled else ("#cfc6f5", "#cfc6f5")
        if enabled and self._hover:
            start, end = blend(start, "#000000", 0.12), blend(end, "#000000", 0.12)
        # One vertical line per column, trimmed at the rounded ends.
        for x in range(width):
            dx = max(radius - x - 0.5, x + 0.5 - (width - radius), 0)
            inset = radius - (max(radius * radius - dx * dx, 0)) ** 0.5
            color = blend(start, end, x / max(1, width - 1))
            self.create_line(x, inset, x, height - inset, fill=color)
        if self._focus and enabled:
            self.create_text(width / 2, height / 2, text=self._text, font=self._font, fill="#ffffff")
            self.create_line(radius, height - 4 * s, width - radius, height - 4 * s, fill="#ffffff", dash=(2, 2))
        else:
            self.create_text(width / 2, height / 2, text=self._text, font=self._font,
                             fill="#ffffff" if enabled else "#f6f3ff")


class App:
    def __init__(self, root: tk.Tk, data: Path, smoke: bool = False):
        self.root, self.data = root, data.resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.events = queue.Queue()
        self.engine = None
        self.pending_setup = None
        self.auto_setup_asked = False
        self.converter_pending = False
        self.converter_error = ""
        self.queue_health = {"state": "unknown", "detail": "조회 대기"}
        self.health_pending = False
        self.health_requested = 0.0
        self.route_ready = False
        self.jobs = {}
        previous = sorted((self.data / "jobs").glob("*/metadata.json"),
                          key=lambda p: p.stat().st_mtime)[-100:]
        for metadata in previous:
            try:
                job = json.loads(metadata.read_text(encoding="utf-8"))
                job["_history"] = True
                self.events.put(job)
            except (OSError, ValueError):
                pass
        self.inventory = printer_inventory()
        self.connection_warning = ""
        try:
            self.addresses = local_ipv4_addresses()
        except OSError as exc:
            self.addresses = []
            self.connection_warning = f"이 PC의 IPv4 주소를 확인하지 못했습니다: {exc}"
        relay_capture, self.relay_address = relay_route(self.data, self.addresses)
        if relay_capture:
            self.addresses = [relay_capture] + [item for item in self.addresses if item != relay_capture]
        printer_addresses = [self.relay_address] if self.relay_address else None
        host, port, printer = choose_endpoint(self.inventory, self.addresses, printer_addresses)
        listener_port = RELAY_CAPTURE_RAW_PORT if relay_capture else port
        self.address_change_notice = address_change_notice(self.inventory, self.addresses, printer_addresses)
        self.config = {"host": host, "port": listener_port,
                       "printer_host": self.relay_address or host,
                       "ghostpcl": find_converter("pcl", PROJECT) or find_converter("pcl", self.data),
                       "ghostscript": find_converter("ps", PROJECT),
                       "queue_name": owned_queue_name(self.inventory) or QUEUE_NAME,
                       "receive_rate": DEFAULT_RECEIVE_RATE, "snmp_enabled": True, "driver": None}
        try:
            saved = json.loads((self.data / "settings.json").read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError("설정은 JSON 객체여야 합니다.")
            self.config.update({k: saved[k] for k in ("ghostpcl", "ghostscript")
                                if saved.get(k) and Path(saved[k]).is_file()})
            self.config["queue_name"] = clean_queue_name(saved.get("queue_name")) or self.config["queue_name"]
            self.config["receive_rate"] = clean_receive_rate(saved.get("receive_rate"), DEFAULT_RECEIVE_RATE)
            self.config["snmp_enabled"] = bool(saved.get("snmp_enabled", True))
            if saved.get("driver") in available_driver_options():
                self.config["driver"] = saved["driver"]
            expected_saved_port = RELAY_CAPTURE_RAW_PORT if relay_capture else 9100
            if saved.get("host") in self.addresses and int(saved.get("port", 0)) == expected_saved_port:
                if not printer:
                    self.config.update(host=saved["host"], port=expected_saved_port)
            elif "host" in saved:
                backup = self.data / f"settings.previous-{time.time_ns()}.json"
                (self.data / "settings.json").replace(backup)
                self.connection_warning = "이전 루프백/미할당 주소 또는 비표준 포트 설정을 보관하고 해제했습니다. 프린터 연결을 다시 준비하세요."
        except (OSError, ValueError, TypeError):
            pass
        if self.address_change_notice:
            self.connection_warning = self.address_change_notice
        self.build_ui()
        self.refresh_route()
        root.protocol("WM_DELETE_WINDOW", self.close)
        atexit.register(self._atexit_cleanup)
        for variable in (self.status, self.phase, self.route):
            variable.trace_add("write", self.write_runtime_status)
        self.write_runtime_status()
        root.after(100, self.consume)
        if smoke:
            root.after(500, self.close)
        else:
            root.after(150, self.start)
            root.after(250, self.request_health)
            root.after(400, self.prepare_converter)
            root.after(900, self.auto_setup)
            root.after(5000, self.check_network)

    def build_ui(self):
        root = self.root
        root.title("SayScore PDF")
        scale = max(1.0, root.winfo_fpixels("1i") / 96)
        px = lambda value: int(value * scale)
        width = min(px(780), int(root.winfo_screenwidth() * 0.92))
        height = min(px(640), int(root.winfo_screenheight() * 0.88))
        root.geometry(f"{width}x{height}")
        root.minsize(min(px(600), width), min(px(500), height))
        root.configure(bg=BG)
        global FONT
        FONT = choose_font(root)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=INK, font=(FONT, 10))
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=INK, font=(FONT, 10))
        style.configure("Card.TLabel", background=CARD, foreground=INK, font=(FONT, 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT, 9))
        style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=(FONT, 10))
        style.configure("Eyebrow.TLabel", background=CARD, foreground=ACCENT_INK, font=(FONT, 9, "bold"))
        style.configure("TButton", font=(FONT, 10), padding=(14, 9), relief="flat", borderwidth=0,
                        background=ACCENT_SOFT, foreground=ACCENT_INK, focuscolor=ACCENT_SOFT)
        style.map("TButton", background=[("active", "#e6ddff"), ("pressed", "#ddd0ff")])
        style.configure("Primary.TButton", font=(FONT, 12, "bold"), padding=(22, 13), relief="flat",
                        borderwidth=0, foreground="#ffffff", background=ACCENT, focuscolor=ACCENT)
        style.map("Primary.TButton",
                  background=[("active", ACCENT_DARK), ("pressed", ACCENT_DARK), ("disabled", "#ccc5ee")],
                  foreground=[("disabled", "#f4f1ff")])
        style.configure("TMenubutton", font=(FONT, 10), padding=(14, 9), relief="flat", borderwidth=0,
                        background=ACCENT_SOFT, foreground=ACCENT_INK, arrowcolor=ACCENT_INK)
        style.map("TMenubutton", background=[("active", "#e6ddff")])
        style.configure("Treeview", rowheight=px(34), font=(FONT, 10), background=CARD,
                        fieldbackground=CARD, foreground=INK, borderwidth=0, relief="flat")
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.map("Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", ACCENT_INK)])
        style.configure("Treeview.Heading", font=(FONT, 9, "bold"), padding=(10, 8),
                        background="#f3f0ff", foreground=MUTED, relief="flat", borderwidth=0)
        style.map("Treeview.Heading", background=[("active", "#ebe5ff")])
        style.configure("TCheckbutton", background=BG, foreground=INK, font=(FONT, 10), focuscolor=BG)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("Vertical.TScrollbar", background=ACCENT_SOFT, troughcolor=CARD, borderwidth=0,
                        bordercolor=CARD, lightcolor=ACCENT_SOFT, darkcolor=ACCENT_SOFT,
                        arrowcolor=MUTED, gripcount=0)
        style.map("Vertical.TScrollbar", background=[("active", "#ddd2ff")])

        box = ttk.Frame(root, padding=(28, 22))
        box.pack(fill="both", expand=True)
        header = ttk.Frame(box)
        header.pack(fill="x")
        self._brand_mark(header, px(44)).pack(side="left")
        titles = ttk.Frame(header)
        titles.pack(side="left", padx=(12, 0))
        ttk.Label(titles, text="SayScore PDF", font=(FONT, 18, "bold")).pack(anchor="w")
        ttk.Label(titles, text=f"인쇄하면 자동으로 PDF로 저장됩니다 · v{__version__}", style="Muted.TLabel",
                  font=(FONT, 10)).pack(anchor="w")
        # GitHub Sponsors pink so the free project's donation link is easy to spot.
        style.configure("Sponsor.TButton", font=(FONT, 10, "bold"), padding=(14, 8), relief="flat",
                        borderwidth=0, background="#ffeff7", foreground="#bf3989", focuscolor="#ffeff7")
        style.map("Sponsor.TButton", background=[("active", "#ffd8eb"), ("pressed", "#ffc7e2")])
        ttk.Button(header, text="♥ 후원하기", style="Sponsor.TButton",
                   command=lambda: webbrowser.open(SPONSOR_URL)).pack(side="right")

        card = tk.Frame(box, bg=CARD, highlightbackground=LINE, highlightcolor=LINE, highlightthickness=1, bd=0)
        card.pack(fill="x", pady=(18, 0))
        GradientStrip(card, height=px(4)).pack(fill="x")
        cardpad = ttk.Frame(card, style="Card.TFrame", padding=(24, 18, 24, 22))
        cardpad.pack(fill="x")
        self.pill = tk.Label(cardpad, text="● 확인 중", font=(FONT, 9, "bold"), bg=SOFT[WAIT], fg=WAIT,
                             padx=px(10), pady=px(3))
        self.pill.pack(anchor="w")
        self.phase = tk.StringVar(value="준비 중…")
        self.headline = tk.Label(cardpad, textvariable=self.phase, font=(FONT, 15, "bold"),
                                 bg=CARD, fg=INK, anchor="w", justify="left")
        self.wrap(self.headline).pack(fill="x", pady=(10, 0))
        checks = ttk.Frame(cardpad, style="Card.TFrame")
        checks.pack(fill="x", pady=(14, 18))
        self.check_rows = {}
        for key, title in (("converter", "PDF 변환기"), ("printer", "SayScore PDF 프린터"), ("receiver", "인쇄 받기")):
            row = ttk.Frame(checks, style="Card.TFrame")
            row.pack(fill="x", pady=2)
            dot = tk.Label(row, text="●", font=(FONT, 9), bg=CARD, fg=WAIT, width=2)
            dot.pack(side="left")
            ttk.Label(row, text=title, style="Card.TLabel", width=18, font=(FONT, 10, "bold")).pack(side="left")
            text = tk.StringVar(value="확인 중…")
            self.wrap(ttk.Label(row, textvariable=text, style="CardMuted.TLabel")).pack(side="left", fill="x", expand=True)
            self.check_rows[key] = (dot, text)
        self.primary = GradientButton(cardpad, text="PDF 폴더 열기", command=self.primary_action,
                                      font=(FONT, 12, "bold"), scale=scale)
        self.primary.pack(anchor="w")

        # Shown only in simple mode (no WSL relay), where the printer targets this PC's own address.
        self.simple_banner = tk.Label(
            box, text="⚠ 간편 모드 · 프린터가 이 PC 자신의 주소로 연결되어 있어, 일부 프로그램이나 웹사이트는 "
                      "가상 프린터로 인식해 인쇄를 막을 수 있습니다. 그런 경우 더보기 → '권장 모드 설치'를 이용하세요 "
                      "(재부팅 필요).",
            font=(FONT, 9), bg=SOFT[WAIT], fg="#7a4f0f", anchor="w", justify="left", padx=px(12), pady=px(8))
        self.wrap(self.simple_banner)
        self.banner_anchor = card
        self.status = tk.StringVar(value=self.address_change_notice or "시작 중…")
        self.route = tk.StringVar(value="")
        self.health_label = tk.StringVar(value="Windows 프린터 상태: 조회 대기")
        self.wrap(ttk.Label(box, textvariable=self.status, style="Muted.TLabel")).pack(fill="x", pady=(8, 0))

        head = ttk.Frame(box)
        head.pack(fill="x", pady=(14, 6))
        ttk.Label(head, text="최근 PDF", font=(FONT, 12, "bold")).pack(side="left")
        ttk.Label(head, text="  두 번 클릭하면 열립니다", style="Muted.TLabel").pack(side="left")
        table = tk.Frame(box, bg=CARD, highlightbackground=LINE, highlightcolor=LINE, highlightthickness=1, bd=0)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("time", "state", "file", "detail"), show="headings",
                                 selectmode="browse", height=4)
        for key, title, width, stretch in (("time", "시간", 110, False), ("state", "상태", 90, False),
                                           ("file", "파일", 220, True), ("detail", "내용", 300, True)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=px(width), stretch=stretch)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("failed", foreground=BAD)
        self.tree.bind("<<TreeviewSelect>>", self.selected)
        self.tree.bind("<Double-1>", self.open_selected)
        self.detail = tk.StringVar(value="")
        self.wrap(ttk.Label(box, text="창을 닫으면 인쇄 받기가 멈춥니다 (최소화는 괜찮아요). "
                                      "PDF 저장 성공이 웹사이트의 프린터 지원 여부까지 확인해 주지는 않습니다.",
                            style="Muted.TLabel")).pack(side="bottom", fill="x", pady=(10, 0), before=table)

        footer = ttk.Frame(box)
        footer.pack(side="bottom", fill="x", pady=(8, 0), before=table)
        ttk.Button(footer, text="PDF 폴더 열기", command=self.open_output).pack(side="left")
        ttk.Button(footer, text="파일 가져오기", command=self.import_file).pack(side="left", padx=6)
        more = ttk.Menubutton(footer, text="더보기")
        menu = tk.Menu(more, tearoff=False, font=(FONT, 10))
        menu.add_command(label="선택한 PDF 열기", command=self.open_result)
        menu.add_command(label="선택 작업 다시 시도", command=self.retry)
        menu.add_command(label="작업 로그 열기", command=self.open_job_folder)
        menu.add_separator()
        menu.add_command(label="프린터 다시 설정", command=self.setup_printer)
        menu.add_command(label="수신 중지/시작", command=self.toggle_engine)
        menu.add_command(label="연결 설정 (고급)", command=self.settings)
        menu.add_command(label="권장 모드 설치 (WSL 2, 재부팅 필요)", command=self.install_recommended_mode)
        menu.add_separator()
        menu.add_command(label="사이트 오류 안내", command=self.site_help)
        menu.add_command(label="진단 내보내기", command=self.export_diagnostics)
        menu.add_separator()
        menu.add_command(label="프로젝트 페이지 (GitHub)", command=lambda: webbrowser.open(PROJECT_URL))
        menu.add_command(label="후원하기 (GitHub Sponsors)", command=lambda: webbrowser.open(SPONSOR_URL))
        more["menu"] = menu
        more.pack(side="right")
        if sys.platform == "win32":
            self.mode_buttons = {}
            toggle = tk.Frame(footer, bg=BG)
            toggle.pack(side="right", padx=(0, 10))
            ttk.Label(toggle, text="연결 방식", style="Muted.TLabel").pack(side="left", padx=(0, 6))
            for mode, label in (("wsl", "권장 · WSL"), ("simple", "간편 · 가상 어댑터")):
                button = tk.Label(toggle, text=label, font=(FONT, 9, "bold"), padx=px(10), pady=px(6),
                                  cursor="hand2")
                button.pack(side="left")
                button.bind("<Button-1>", lambda _e, m=mode: self.switch_mode(m))
                self.mode_buttons[mode] = button
            self.paint_mode_toggle()
        self.wrap(ttk.Label(box, textvariable=self.detail, style="Muted.TLabel")).pack(
            side="bottom", fill="x", pady=(6, 0), before=table)

    @staticmethod
    def wrap(label):
        label.bind("<Configure>", lambda event: event.widget.configure(wraplength=max(event.width - 4, 50)))
        return label

    def _brand_mark(self, parent, size):
        # The 256px app icon, shrunk by an integer factor (Tk has no smooth scaling).
        try:
            image = tk.PhotoImage(file=str(Path(__file__).with_name("assets") / "sayscore.png"))
            self._brand_image = image.subsample(max(1, round(image.width() / size)))
            return tk.Label(parent, image=self._brand_image, bg=BG, bd=0)
        except tk.TclError:
            return tk.Frame(parent, width=size, height=size, bg=ACCENT)

    def set_check(self, key, state, text):
        dot, variable = self.check_rows[key]
        dot.configure(fg={"ok": GOOD, "wait": WAIT, "bad": BAD}[state])
        variable.set(text)

    def set_pill(self, text, color):
        self.pill.configure(text=f"● {text}", fg=color, bg=SOFT[color])

    def current_mode(self) -> str:
        """'simple' (Wintun relay), 'wsl' (WSL relay) or '' (no relay)."""
        if not self.relay_address:
            return ""
        try:
            state = json.loads((self.data / "relay-runtime.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "wsl"
        return "simple" if isinstance(state, dict) and state.get("mode") == "tun" else "wsl"

    def paint_mode_toggle(self):
        if not getattr(self, "mode_buttons", None):
            return
        active = self.current_mode()
        for mode, button in self.mode_buttons.items():
            on = mode == active
            button.configure(bg=ACCENT if on else ACCENT_SOFT, fg="#ffffff" if on else ACCENT_INK,
                             cursor="arrow" if on else "hand2")

    def switch_mode(self, mode: str):
        if mode == self.current_mode():
            return
        name = {"wsl": "권장 모드 (WSL 2 중계)", "simple": "간편 모드 (가상 네트워크 어댑터)"}[mode]
        if not messagebox.askyesno(
                "연결 방식 전환",
                f"{name}로 바꾸고 SayScore PDF를 다시 시작합니다.\n\n"
                "다시 시작한 뒤 프린터 연결을 새 방식에 맞게 다시 설정하라는 안내가 나오면 '예'를 누르세요.\n\n"
                "계속할까요?", parent=self.root):
            return
        try:
            mode_file = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SayScore PDF" / "mode.txt"
            mode_file.parent.mkdir(parents=True, exist_ok=True)
            mode_file.write_text(mode, encoding="ascii")
            bootstrap = PROJECT / "scripts" / "Bootstrap-SayScore.ps1"
            # Wait for this window to close so the new instance does not see it as already running.
            subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                              "-Command", f"Start-Sleep -Seconds 3; & '{bootstrap}' -NoShortcut"],
                             creationflags=NO_WINDOW)
        except OSError as exc:
            messagebox.showerror("연결 방식 전환", f"전환하지 못했습니다: {exc}", parent=self.root)
            return
        self.close()

    def install_recommended_mode(self):
        if self.relay_address:
            messagebox.showinfo("권장 모드", "이미 권장 모드(WSL 2 중계)로 실행 중입니다.", parent=self.root)
            return
        if not messagebox.askyesno(
                "권장 모드 설치",
                "Windows 기능(WSL 2)을 설치합니다. 관리자 확인과 인터넷 연결이 필요하며, 설치 후 재부팅해야 합니다.\n\n"
                "재부팅 후 SayScore PDF를 다시 실행하면 권장 모드로 바뀌고, 프린터 연결도 자동으로 다시 설정됩니다.\n\n"
                "계속할까요?", parent=self.root):
            return
        try:
            subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                              "-File", str(PROJECT / "scripts" / "Bootstrap-SayScore.ps1"), "-InstallWsl"],
                             creationflags=NO_WINDOW)
        except OSError as exc:
            messagebox.showerror("권장 모드 설치", f"설치를 시작하지 못했습니다: {exc}", parent=self.root)

    def update_overview(self):
        if not hasattr(self, "check_rows"):
            return
        if self.config.get("ghostpcl"):
            self.set_check("converter", "ok", "준비됨")
        elif self.converter_pending:
            self.set_check("converter", "wait", "처음 한 번 내려받는 중… (인터넷 필요)")
        elif self.converter_error:
            self.set_check("converter", "bad", "준비 실패 · 더보기 → 연결 설정에서 지정하거나 앱을 다시 실행하세요")
        else:
            self.set_check("converter", "wait", "확인 중…")
        if self.pending_setup:
            self.set_check("printer", "wait", "설정 중… 관리자 확인 창에서 '예'를 누르세요")
        elif self.route_ready:
            driver = owned_queue_driver(self.inventory) or ""
            self.set_check("printer", "ok", f"설치됨 · {driver} · {self.config['host']}" if driver else f"설치됨 ({self.config['host']})")
        elif self.address_change_notice:
            self.set_check("printer", "bad", "IP가 바뀌어 다시 연결해야 합니다")
        else:
            self.set_check("printer", "bad", "아직 설치되지 않았습니다")
        receiving = bool(self.engine is not None and getattr(self.engine, "host", None))
        if receiving:
            snmp = ("" if not self.config.get("snmp_enabled")
                    else " · SNMP 응답" if getattr(self.engine, "snmp_active", False)
                    else " · SNMP 시작 실패")
            self.set_check("receiver", "ok", f"대기 중 · {self.engine.host}:{self.engine.port}{snmp}")
        elif self.engine is not None:
            self.set_check("receiver", "wait", "파일 가져오기만 가능 (프린터 설정 후 자동 시작)")
        else:
            self.set_check("receiver", "bad", "중지됨")
        if self.pending_setup:
            headline, button, enabled = "프린터를 설정하고 있습니다…", "설정 중…", False
        elif not self.route_ready:
            headline = ("IP 주소가 바뀌었습니다. 버튼을 눌러 프린터를 다시 연결하세요."
                        if self.address_change_notice else "버튼 한 번으로 'SayScore PDF' 프린터를 추가하세요.")
            button, enabled = "프린터 자동 설정", True
        elif not receiving:
            headline, button, enabled = "인쇄 받기가 멈춰 있습니다.", "인쇄 받기 시작", True
        else:
            headline, button, enabled = "인쇄할 때 프린터로 'SayScore PDF'를 선택하세요.", "PDF 폴더 열기", True
        if self.phase.get() != headline and not self.phase.get().startswith("새 PDF"):
            self.phase.set(headline)
        self.paint_mode_toggle()
        if self.relay_address or sys.platform != "win32":
            self.simple_banner.pack_forget()
        elif not self.simple_banner.winfo_manager():
            self.simple_banner.pack(fill="x", pady=(10, 0), after=self.banner_anchor)
        if self.pending_setup:
            self.set_pill("설정 중", WAIT)
        elif not self.route_ready:
            self.set_pill("설정 필요", BAD)
        elif not receiving:
            self.set_pill("일시 중지", WAIT)
        else:
            self.set_pill("준비 완료", GOOD)
        self.primary.configure(text=button, state="normal" if enabled else "disabled")

    def primary_action(self):
        if not self.route_ready:
            self.setup_printer(confirm=False)
        elif not (self.engine is not None and self.engine.host):
            if self.engine:
                self.toggle_engine()
            self.start()
        else:
            self.open_output()

    def write_runtime_status(self, *_args):
        listener = getattr(self.engine, "_listener", None)
        try:
            bound = listener.getsockname() if listener else None
        except OSError:
            bound = None
        report = {"product": "SayScore PDF", "pid": os.getpid(), "updated": time.time(),
                  "status": self.status.get(), "phase": self.phase.get(), "route": self.route.get(),
                  "configured_host": self.config["host"], "configured_port": self.config["port"],
                  "printer_host": self.config.get("printer_host"),
                  "processing_active": self.engine is not None,
                  "listener_host": bound[0] if bound else None,
                  "listener_port": bound[1] if bound else None,
                  "listener_active": bool(bound), "queue_health": self.queue_health,
                  "address_change_notice": self.address_change_notice,
                  "queue_health_pending": self.health_pending,
                  "queue_name": self.config.get("queue_name"),
                  "receive_rate": self.config.get("receive_rate"),
                  "snmp_enabled": bool(self.config.get("snmp_enabled")),
                  "snmp_active": bool(getattr(self.engine, "snmp_active", False)),
                  "snmp_error": getattr(self.engine, "snmp_error", ""),
                  "bidirectional_diagnostics": (self.engine.communication_status()
                                                   if self.engine and hasattr(self.engine, "communication_status")
                                                   else None),
                  "converter_ready": bool(self.config.get("ghostpcl")),
                  "windows_print_validation": "not inferred from queue registration",
                  "website_validation": "untested"}
        try:
            target = self.data / "runtime-status.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(target)
        except OSError:
            pass

    def request_health(self):
        if self.health_pending:
            if time.monotonic() - self.health_requested > 10:
                self.queue_health = {"state": "unknown", "detail": "Windows 프린터 상태 조회 지연 · 결과 미확인"}
                self.health_label.set(self.queue_health["detail"])
            return
        self.health_pending = True
        self.health_requested = time.monotonic()
        name = owned_queue_name(self.inventory) or self.config.get("queue_name") or QUEUE_NAME

        def read():
            try:
                health = queue_health(name)
            except (OSError, ValueError) as exc:
                health = {"state": "unknown", "detail": str(exc)}
            health["checked"] = time.time()
            self.events.put({"kind": "queue_health", "health": health})

        threading.Thread(target=read, daemon=True).start()

    def prepare_converter(self):
        if self.config.get("ghostpcl") or self.converter_pending or sys.platform != "win32":
            return
        self.converter_pending, self.converter_error = True, ""
        self.update_overview()
        destination = PROJECT / "vendor"
        try:
            destination.mkdir(exist_ok=True)
            probe = destination / ".write-test"
            probe.write_bytes(b"")
            probe.unlink()
        except OSError:
            destination = self.data / "vendor"
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-File", str(PROJECT / "scripts" / "Get-GhostPCL.ps1"), "-Destination", str(destination)]

        def run():
            error = ""
            try:
                result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace",
                                        timeout=900, creationflags=NO_WINDOW)
                if result.returncode:
                    error = (result.stderr or result.stdout).strip()[-600:]
            except (OSError, subprocess.SubprocessError) as exc:
                error = str(exc)
            path = find_converter("pcl", PROJECT) or find_converter("pcl", self.data)
            self.events.put({"kind": "converter", "path": path, "error": "" if path else (error or "변환기를 찾지 못했습니다.")})

        threading.Thread(target=run, daemon=True).start()

    def converter_ready(self, event):
        self.converter_pending = False
        self.converter_error = event.get("error", "")
        if event.get("path"):
            self.config["ghostpcl"] = event["path"]
            if self.engine:
                self.engine.ghostpcl = event["path"]
                for job in list(self.jobs.values()):
                    if job.get("state") == "failed" and "GhostPCL" in job.get("detail", "") and job.get("capture_complete"):
                        try:
                            self.engine.retry(job["id"])
                        except (OSError, ValueError, RuntimeError):
                            pass
        self.update_overview()
        self.write_runtime_status()

    def start(self):
        if self.engine:
            return
        engine = None
        try:
            engine = Engine(self.data, self.events.put,
                            ghostscript=self.config["ghostscript"], ghostpcl=self.config["ghostpcl"],
                            receive_rate=self.config.get("receive_rate", DEFAULT_RECEIVE_RATE),
                            snmp_enabled=bool(self.config.get("snmp_enabled")),
                            snmp_identity=snmp_identity_from_config(self.config, self.inventory),
                            trusted_peers=tuple(filter(None, [relay_peer(self.data)])))
            if self.config["host"] not in local_ipv4_addresses():
                raise ValueError("사용 가능한 사설 IPv4 주소가 없습니다. 네트워크(Wi-Fi/유선)에 연결한 뒤 다시 실행하세요.")
            snmp_port = RELAY_CAPTURE_SNMP_PORT if self.relay_address else 161
            engine.start(host=self.config["host"], port=int(self.config["port"]),
                         allow_local_network=True, snmp_port=snmp_port)
            self.engine = engine
            ready = self.refresh_route()
            self.status.set(("전용 프린터 수신 대기" if ready else "프린터 연결 준비 필요 · 파일 가져오기 사용 가능")
                            + f" · 수신기 {self.config['host']}:{self.config['port']}")
            if self.connection_warning:
                self.status.set(self.connection_warning + " · " + self.status.get())
            if getattr(engine, "snmp_error", ""):
                self.status.set(engine.snmp_error + " · " + self.status.get())
        except (OSError, ValueError, RuntimeError) as exc:
            try:
                if engine is None:
                    raise RuntimeError(str(exc))
                engine.start_files_only()
                self.engine = engine
                self.status.set(f"프린터 연결 준비 필요 · 파일 가져오기 사용 가능 · 수신 시작 실패: {exc}")
                if self.connection_warning:
                    self.status.set(self.connection_warning + " · " + self.status.get())
            except (OSError, ValueError, RuntimeError) as file_exc:
                self.status.set(f"수신/파일 처리를 시작하지 못했습니다: {file_exc}")
        self.update_overview()

    def refresh_route(self):
        self.inventory = printer_inventory()
        try:
            self.addresses = local_ipv4_addresses()
        except OSError:
            self.addresses = []
        relay_capture, self.relay_address = relay_route(self.data, self.addresses)
        if relay_capture:
            self.addresses = [relay_capture] + [item for item in self.addresses if item != relay_capture]
        printer_addresses = [self.relay_address] if self.relay_address else None
        self.config["printer_host"] = self.relay_address or self.config["host"]
        host, port, printer = choose_endpoint(self.inventory, self.addresses, printer_addresses)
        self.address_change_notice = address_change_notice(self.inventory, self.addresses, printer_addresses)
        ready = bool(printer and host == self.config["host"] and port == 9100)
        self.route_ready = ready
        self.route.set(f"연결할 프린터: {printer}" if ready else (self.address_change_notice
                       or "프린터 연결 준비 필요 · '프린터 자동 설정'으로 전용 SayScore PDF 큐를 준비하세요."))
        self.update_overview()
        return ready

    def site_help(self):
        messagebox.showinfo("사이트 오류 안내 · 등록되지 않은 프린터", SITE_REGISTRATION_HELP, parent=self.root)

    def check_network(self):
        if self.engine and self.engine.host:
            try:
                addresses = local_ipv4_addresses()
            except OSError as exc:
                self.status.set(f"네트워크 주소 확인 실패 · 프린터 연결을 확인하세요: {exc}")
            else:
                if self.engine.host not in addresses:
                    try:
                        self.engine.stop()
                        self.engine.start_files_only()
                        self.connection_warning = "네트워크 주소가 바뀌었습니다. 프린터 연결을 갱신하세요."
                        self.status.set(self.connection_warning + " · 파일 가져오기 사용 가능")
                        if addresses:
                            self.config.update(host=addresses[0],
                                               port=RELAY_CAPTURE_RAW_PORT if self.relay_address else 9100)
                        self.auto_setup_asked = False
                        self.root.after(500, self.auto_setup)
                    except (OSError, ValueError, RuntimeError) as exc:
                        self.status.set(f"네트워크 변경 후 수신 중지 확인 필요: {exc}")
        was_ready = self.route_ready
        ready = self.refresh_route()
        receiving = (self.engine is not None and self.engine.host == self.config["host"]
                     and self.engine.port == self.config["port"])
        if receiving and not self.pending_setup:
            if ready and not was_ready:
                self.connection_warning = ""
                self.status.set(f"전용 프린터 연결 갱신 확인 · 수신 대기 · {self.config['host']}:{self.config['port']} · 사이트 호환성 미검증")
            elif was_ready and not ready:
                self.status.set(self.address_change_notice or "프린터 연결 준비 필요 · 전용 큐의 연결 설정을 확인하세요.")
        self.root.after(5000, self.check_network)
        self.request_health()
        self.write_runtime_status()

    def auto_setup(self):
        if (sys.platform != "win32" or self.route_ready or self.pending_setup
                or self.auto_setup_asked or not self.addresses):
            return
        self.auto_setup_asked = True
        if self.address_change_notice:
            message = "이 PC의 IP 주소가 바뀌어 'SayScore PDF' 프린터를 새 주소로 다시 연결해야 합니다."
        else:
            message = "인쇄한 문서를 PDF로 받으려면 'SayScore PDF' 프린터를 이 PC에 한 번 추가해야 합니다."
        message += ("\n\n지금 자동으로 설정할까요?\n\n· Windows 관리자 확인 창이 뜨면 '예'를 누르세요."
                    "\n· 다른 프린터와 기본 프린터는 바꾸지 않습니다.")
        if messagebox.askyesno("SayScore PDF 프린터 설정", message, parent=self.root):
            self.setup_printer(confirm=False)

    def setup_printer(self, confirm=True):
        if sys.platform != "win32":
            messagebox.showerror("프린터 연결", "전용 프린터 등록은 Windows에서 지원됩니다.")
            return
        if self.pending_setup:
            return
        try:
            addresses = local_ipv4_addresses()
            host = self.config["host"] if self.config["host"] in addresses else (addresses[0] if addresses else "")
            if not host:
                raise ValueError("이 PC에 연결된 네트워크(사설 IPv4 주소)가 없습니다. Wi-Fi 또는 유선 네트워크에 연결한 뒤 다시 시도하세요.")
            inventory = printer_inventory()
            script, driver = setup_choice(inventory, native_windows_arch(),
                                          preferred=self.config.get("driver"))
            queue_name = clean_queue_name(self.config.get("queue_name")) or QUEUE_NAME
            previous_name = owned_queue_name(inventory)
            printer_host = self.config.get("printer_host") or host
        except (OSError, ValueError, AttributeError) as exc:
            messagebox.showerror("프린터 설정을 시작할 수 없습니다", str(exc), parent=self.root)
            return
        rename_note = (f"\n이름 변경: '{previous_name}' → '{queue_name}'"
                       if previous_name and previous_name != queue_name else "")
        if confirm and not messagebox.askyesno(
                "SayScore PDF 프린터 설정",
                f"'{queue_name}' 프린터를 {printer_host} 중계 주소로 설정합니다.\n드라이버: {driver}{rename_note}\n\n"
                "관리자 확인 창이 뜨면 '예'를 누르세요. 다른 프린터는 바꾸지 않습니다.", parent=self.root):
            return
        result_path = self.data / "printer-setup-result.json"
        try:
            result_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            messagebox.showerror("프린터 설정 실패", str(exc), parent=self.root)
            return
        arguments = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                     "-File", str(PROJECT / "scripts" / "Setup-SayScorePrinter.ps1"),
                     "-Installer", script, "-CaptureAddress", host, "-DriverName", driver,
                     "-QueueName", queue_name, "-ResultPath", str(result_path)]
        if printer_host != host:
            arguments += ["-PrinterAddress", printer_host]
        if previous_name and previous_name != queue_name:
            arguments += ["-PreviousQueueName", previous_name]
        if self.config.get("snmp_enabled"):
            arguments += ["-Bidirectional"]
        import ctypes
        code = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe",
                                                   subprocess.list2cmdline(arguments), str(PROJECT), 0)
        if code <= 32:
            self.status.set("관리자 확인이 취소되어 프린터를 설정하지 않았습니다. '프린터 자동 설정'을 다시 누르세요."
                            if code == 5 else f"관리자 권한 실행을 시작하지 못했습니다 (코드 {code}).")
            self.update_overview()
            return
        self.pending_setup = {"host": host, "printer_host": printer_host, "port": 9100,
                              "driver": driver, "result": result_path}
        self.status.set("프린터를 설정하는 중입니다…")
        self.update_overview()
        self.root.after(1000, lambda: self.check_setup(180))

    def check_setup(self, attempts):
        expected = self.pending_setup or {}
        result_file = expected.get("result")
        outcome = None
        if result_file and Path(result_file).is_file():
            try:
                outcome = json.loads(Path(result_file).read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                outcome = None
        self.inventory = printer_inventory()
        try:
            addresses = local_ipv4_addresses()
            relay_capture, relay_address = relay_route(self.data, addresses)
            if relay_capture:
                addresses = [relay_capture] + [item for item in addresses if item != relay_capture]
            host, port, printer = choose_endpoint(
                self.inventory, addresses, [relay_address] if relay_address else None)
        except OSError:
            host, port, printer = "", 9100, ""
        applied = bool(printer and (not expected or (
            host == expected["host"] and port == expected["port"]
            and any(p["name"] == printer and p.get("driver") == expected["driver"]
                    for p in self.inventory["printers"]))))
        if outcome is not None and outcome.get("ok") and outcome.get("driver") and expected:
            expected["driver"] = outcome["driver"]
            self.setup_warning = outcome.get("warning", "")
        if outcome is not None and not outcome.get("ok") and not applied:
            self.pending_setup = None
            self.status.set("프린터 설정 실패: " + outcome.get("message", ""))
            self.update_overview()
            messagebox.showerror("프린터 설정 실패",
                                 outcome.get("message", "") + "\n\n문제가 계속되면 더보기 → 진단 내보내기 파일을 전달해 주세요.",
                                 parent=self.root)
            return
        listener_port = RELAY_CAPTURE_RAW_PORT if relay_address else port
        if applied and (host != self.config["host"] or listener_port != self.config["port"]
                        or not self.engine or self.engine.host is None):
            if self.engine and not self.toggle_engine():
                return
            self.config.update(host=host, port=listener_port)
            self.start()
        if applied and self.refresh_route():
            self.pending_setup = None
            self.connection_warning = ""
            receiving = self.engine is not None and self.engine.host == self.config["host"]
            self.status.set(f"전용 프린터 등록 확인 · 수신 {'대기' if receiving else '중지/파일 처리만 가능'} · {self.config['host']}:{self.config['port']} · 사이트 호환성 미검증")
            if getattr(self, "setup_warning", ""):
                self.status.set(self.setup_warning + " · " + self.status.get())
            self.update_overview()
        elif attempts:
            self.root.after(1000, lambda: self.check_setup(attempts - 1))
        else:
            self.pending_setup = None
            self.status.set("프린터 설정 결과를 확인하지 못했습니다. '프린터 자동 설정'을 다시 눌러 보세요.")
            self.update_overview()

    def toggle_engine(self):
        if self.engine:
            try:
                self.engine.stop()
            except RuntimeError as exc:
                self.status.set(f"수신 중지 대기: {exc}")
                return False
            self.engine = None
            self.status.set("수신 중지 · 다시 시작하면 새 인쇄 작업을 감지합니다.")
            self.update_overview()
        else:
            self.start()
        return True

    def consume(self):
        for _ in range(100):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event.get("kind") == "queue_health":
                self.health_pending = False
                self.queue_health = event["health"]
                self.health_label.set("Windows 프린터 상태: " + self.queue_health["detail"])
                self.write_runtime_status()
                continue
            if event.get("kind") == "converter":
                self.converter_ready(event)
                continue
            job_id = event.get("id")
            if not job_id:
                self.status.set(event.get("detail", ""))
                continue
            history = event.pop("_history", False)
            self.jobs[job_id] = event
            created = event.get("created") or event.get("updated") or time.time()
            name = Path(event.get("output") or "").name if event.get("output") else Path(event.get("input") or "인쇄 작업").name
            if name == "original.bin":
                name = "인쇄 작업"
            values = (time.strftime("%m-%d %H:%M", time.localtime(created)),
                      LABELS.get(event["state"], event["state"]), name, event.get("detail", ""))
            tags = (event["state"],)
            if self.tree.exists(job_id):
                self.tree.item(job_id, values=values, tags=tags)
            else:
                self.tree.insert("", 0, iid=job_id, values=values, tags=tags)
            if history:
                continue
            if event["state"] == "completed":
                self.phase.set(f"새 PDF 저장됨 · {name}  (두 번 클릭해 열기)")
                self.tree.selection_set(job_id)
                self.root.after(15000, self.clear_notice)
            elif event["state"] in ("processing", "receiving"):
                self.phase.set("인쇄 작업을 받아 PDF로 바꾸는 중…")
            elif event["state"] == "failed":
                self.phase.set("PDF로 바꾸지 못한 작업이 있습니다 · 아래 목록을 확인하세요")
                self.root.after(15000, self.clear_notice)
        self.root.after(100, self.consume)

    def clear_notice(self):
        self.phase.set("")
        self.update_overview()

    def selection(self):
        ids = self.tree.selection()
        return self.jobs.get(ids[0]) if ids else None

    def selected(self, _event=None):
        job = self.selection()
        if job:
            self.detail.set(job.get("detail", "") + ("\n" + job["output"] if job.get("output") else ""))

    def open_selected(self, _event=None):
        job = self.selection()
        if job and job.get("output") and Path(job["output"]).exists():
            open_path(Path(job["output"]))
        elif job:
            self.open_job_folder()

    def open_output(self):
        target = self.data / "output"
        target.mkdir(exist_ok=True)
        open_path(target)

    def open_result(self):
        job = self.selection()
        if job and job.get("output") and Path(job["output"]).exists():
            open_path(Path(job["output"]))

    def open_job_folder(self):
        job = self.selection()
        if job:
            folder = (self.data / "jobs" / job["id"]).resolve()
            if folder.is_relative_to(self.data / "jobs") and folder.is_dir():
                open_path(folder)

    def import_file(self):
        if not self.engine:
            self.start()
        if not self.engine:
            return
        path = filedialog.askopenfilename(title="PDF 또는 인쇄 데이터 선택", filetypes=[("인쇄 데이터", "*.pdf *.ps *.prn *.pcl"), ("모든 파일", "*.*")])
        if path:
            try:
                self.engine.submit(Path(path))
            except (OSError, ValueError, RuntimeError) as exc:
                messagebox.showerror("가져오기 실패", str(exc))

    def retry(self):
        job = self.selection()
        if job and job.get("state") == "failed" and self.engine:
            try:
                self.engine.retry(job["id"])
            except (OSError, ValueError, RuntimeError) as exc:
                messagebox.showerror("재시도 실패", str(exc))

    def settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("연결 설정 (고급)")
        dialog.transient(self.root)
        dialog.grab_set()
        form = ttk.Frame(dialog, padding=24)
        form.pack(fill="both", expand=True)
        ttk.Label(form, text="보통은 바꿀 필요가 없습니다. 이 PC에 현재 할당된 사설 IPv4 주소만 선택할 수 있습니다.").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 15))
        try:
            addresses = local_ipv4_addresses()
        except OSError:
            addresses = []
        fields = {}
        rows = (("host", "이 PC의 사설 IPv4"), ("port", "포트"),
                ("queue_name", "프린터(큐) 이름"), ("receive_rate", "수신 속도 (KB/s, 0=제한없음)"),
                ("ghostpcl", "PCL 변환기"), ("ghostscript", "PostScript 변환기"))
        for row, (key, label) in enumerate(rows, 1):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=7)
            if key == "receive_rate":
                initial = str(int(self.config.get("receive_rate", DEFAULT_RECEIVE_RATE)) // 1024)
            elif key == "port" and self.relay_address:
                # The Windows queue always uses RAW 9100.  The relay forwards
                # it to a distinct local capture port to prevent a relay loop.
                initial = "9100"
            else:
                initial = str(self.config.get(key) or "")
            fields[key] = tk.StringVar(value=initial)
            if key == "host":
                ttk.Combobox(form, textvariable=fields[key], values=addresses, state="readonly", width=55).grid(row=row, column=1, padx=10)
            else:
                ttk.Entry(form, textvariable=fields[key], width=58).grid(row=row, column=1, padx=10)
            if key in ("ghostpcl", "ghostscript"):
                def browse(k=key):
                    path = filedialog.askopenfilename(parent=dialog, title="변환기 실행 파일 선택")
                    if path:
                        fields[k].set(path)
                ttk.Button(form, text="선택", command=browse).grid(row=row, column=2)
        drivers = available_driver_options()
        driver_labels = [AUTO_DRIVER_LABEL] + [DRIVER_LABELS[name] for name in drivers]
        current_driver = self.config.get("driver")
        driver_var = tk.StringVar(value=DRIVER_LABELS.get(current_driver, AUTO_DRIVER_LABEL)
                                  if current_driver in drivers else AUTO_DRIVER_LABEL)
        ttk.Label(form, text="프린터 드라이버").grid(row=len(rows) + 1, column=0, sticky="w", pady=7)
        ttk.Combobox(form, textvariable=driver_var, values=driver_labels, state="readonly", width=55).grid(
            row=len(rows) + 1, column=1, padx=10)
        snmp_var = tk.BooleanVar(value=bool(self.config.get("snmp_enabled")))
        ttk.Checkbutton(form, variable=snmp_var,
                        text="양방향 통신(SNMP) 켜기 · 실제 프린터처럼 UDP 161 상태 응답/검색 지원").grid(
            row=len(rows) + 2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(form, text="프린터 이름, 드라이버, 양방향(SNMP) 설정을 바꾸면 적용을 위해 '더보기 → 프린터 다시 설정'을 한 번 실행해야 합니다 (관리자 확인).",
                  style="Muted.TLabel").grid(row=len(rows) + 3, column=0, columnspan=3, sticky="w", pady=(2, 0))

        def save():
            try:
                host = fields["host"].get().strip()
                if host not in local_ipv4_addresses():
                    raise ValueError("이 PC에 현재 할당된 사설 IPv4 주소만 사용할 수 있습니다. 네트워크 연결 후 설정 창을 다시 여세요.")
                port = int(fields["port"].get())
                if port != 9100:
                    raise ValueError("사이트 인쇄 프로필은 표준 RAW 포트 9100을 사용합니다.")
                queue_name = clean_queue_name(fields["queue_name"].get())
                if not queue_name:
                    raise ValueError("프린터(큐) 이름은 비울 수 없고 ! , / \\ 문자는 쓸 수 없습니다.")
                rate_text = fields["receive_rate"].get().strip() or "0"
                if not rate_text.isdigit():
                    raise ValueError("수신 속도는 KB/s 단위의 0 이상 정수여야 합니다.")
                receive_rate = clean_receive_rate(int(rate_text) * 1024, DEFAULT_RECEIVE_RATE)
                listener_port = RELAY_CAPTURE_RAW_PORT if self.relay_address else port
                driver = next((name for name in drivers if DRIVER_LABELS[name] == driver_var.get()), None)
                config = {"host": host, "port": listener_port, "queue_name": queue_name,
                          "receive_rate": receive_rate, "snmp_enabled": bool(snmp_var.get()),
                          "driver": driver}
                for key in ("ghostpcl", "ghostscript"):
                    config[key] = fields[key].get().strip() or None
                    if config[key] and not Path(config[key]).is_file():
                        raise ValueError(f"변환기 파일을 찾을 수 없습니다: {config[key]}")
                renamed = queue_name != (owned_queue_name(self.inventory) or self.config.get("queue_name"))
                bidi_changed = bool(snmp_var.get()) != bool(self.config.get("snmp_enabled"))
                driver_changed = driver != self.config.get("driver")
                if self.engine and not self.toggle_engine():
                    raise RuntimeError("이전 작업이 종료되지 않았습니다. 잠시 후 다시 시도하세요.")
                self.config = config
                self.connection_warning = ""
                (self.data / "settings.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
                dialog.destroy()
                self.start()
                self.refresh_route()
                if renamed or bidi_changed or driver_changed:
                    messagebox.showinfo("설정 변경",
                                        "변경 내용을 Windows에 적용하려면 '더보기 → 프린터 다시 설정'을 "
                                        "눌러 주세요 (관리자 확인).",
                                        parent=self.root)
            except (ValueError, OSError, RuntimeError) as exc:
                messagebox.showerror("설정을 저장할 수 없습니다", str(exc), parent=dialog)
        ttk.Button(form, text="저장하고 연결", command=save).grid(row=len(rows) + 4, column=1, sticky="e", pady=(15, 0))

    def export_diagnostics(self):
        destination = filedialog.asksaveasfilename(title="진단 파일 저장", initialfile="sayscore-pdf-diagnostics.json", defaultextension=".json")
        if destination:
            try:
                setup_result = None
                try:
                    setup_result = json.loads((self.data / "printer-setup-result.json").read_text(encoding="utf-8-sig"))
                except (OSError, ValueError):
                    pass
                report = {"inventory": printer_inventory(), "settings": self.config,
                          "running": self.engine is not None, "queue_health": self.queue_health,
                          "address_change_notice": self.address_change_notice,
                          "site_registration_help": SITE_REGISTRATION_HELP,
                          "last_printer_setup": setup_result, "converter_error": self.converter_error,
                          "queue_health_pending": self.health_pending,
                          "bidirectional_diagnostics": (self.engine.communication_status()
                                                         if self.engine and hasattr(self.engine, "communication_status")
                                                         else None),
                          "recent_bidirectional_requests": (self.engine.recent_communication()
                                                             if self.engine and hasattr(self.engine, "recent_communication")
                                                             else None),
                          "jobs": list(self.jobs.values())}
                Path(destination).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                self.detail.set(f"진단 저장 완료: {destination}")
            except OSError as exc:
                messagebox.showerror("진단 저장 실패", str(exc))

    def close(self):
        if self.engine:
            try:
                self.engine.stop()
            except RuntimeError as exc:
                self.status.set(f"작업 종료 대기: {exc}")
                return
        self.engine = None
        self.status.set("앱 종료 · 수신/파일 처리 중지")
        self.root.destroy()

    def _atexit_cleanup(self):
        engine, self.engine = self.engine, None
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass

def default_data_dir() -> Path:
    candidate = PROJECT / "data"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write-test"
        probe.write_bytes(b"")
        probe.unlink()
        return candidate
    except OSError:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "SayScorePDF"

_instance_handle = None

def already_running() -> bool:
    global _instance_handle
    if sys.platform != "win32":
        return False
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    _instance_handle = kernel.CreateMutexW(None, False, "Local\\SayScorePDF.App")
    if ctypes.get_last_error() != 183:
        return False
    user = ctypes.windll.user32
    window = user.FindWindowW(None, "SayScore PDF")
    if window:
        user.ShowWindow(window, 9)
        user.SetForegroundWindow(window)
    return True

def main():
    parser = argparse.ArgumentParser(description="SayScore PDF · 인쇄 감지와 PDF 저장")
    parser.add_argument("--data", type=Path, default=None)
    parser.add_argument("--smoke", action="store_true", help="수신 없이 UI를 열고 자동으로 닫아 확인")
    args = parser.parse_args()
    if not args.smoke and already_running():
        return
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    if sys.platform == "win32":
        try:
            import ctypes
            # Own taskbar entry, so Windows shows the window icon instead of pythonw's.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SILVERBRINE.SayScorePDF")
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    try:
        root.iconbitmap(default=str(Path(__file__).with_name("assets") / "sayscore.ico"))
    except tk.TclError:
        pass
    App(root, args.data or default_data_dir(), smoke=args.smoke)
    root.mainloop()

if __name__ == "__main__":
    main()
