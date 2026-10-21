from __future__ import annotations

import ipaddress
import platform
import shutil
from pathlib import Path

from .network import local_ipv4_addresses

QUEUE_NAME = "SayScore PDF"
PORT_PREFIX = "SayScorePDF_"
OWNER_COMMENT = "SayScore PDF local capture queue; created by Install-LocalPrinter.ps1 v2"
SITE_REGISTRATION_HELP = (
    "공식 프린터 업데이트를 이미 적용했는데도 같은 오류가 계속되면 업데이트나 재부팅을 반복하지 마세요. "
    "지원 프린터 목록의 모델명 2~3개 또는 제작자가 확인한 지원 드라이버 정보가 필요합니다. "
    "MarkAny를 사용하는 사이트라면 공식 고객지원(https://www.markany.com/cscenter)을 참고하세요. "
    "설치된 모듈만으로 현재 사이트의 출력 솔루션을 특정할 수는 없습니다. "
    "확인된 지원 목록 없이 임의의 제조사 드라이버를 선택하거나 프린터 식별 정보를 바꾸지 않습니다."
)

def printer_inventory() -> dict:
    result = {"architecture": platform.machine(), "system": platform.platform(),
              "printers": [], "ports": {}, "warnings": []}
    if platform.system() != "Windows":
        result["warnings"].append("Windows 프린터 조회는 Windows에서만 지원됩니다.")
        return result
    import winreg
    base = r"SYSTEM\CurrentControlSet\Control\Print"

    def children(path):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                for index in range(winreg.QueryInfoKey(key)[0]):
                    yield winreg.EnumKey(key, index)
        except OSError as exc:
            result["warnings"].append(f"레지스트리 조회 실패: {path}: {exc}")

    def values(path):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                return {name: value for name, value, _ in
                        (winreg.EnumValue(key, i) for i in range(winreg.QueryInfoKey(key)[1]))}
        except OSError:
            return {}

    def quiet_children(path):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                return [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
        except OSError:
            return []

    result["monitors"] = quiet_children(base + r"\Monitors")
    ports_key = base + r"\Monitors\Standard TCP/IP Port\Ports"
    for name in children(ports_key):
        value = values(ports_key + "\\" + name)
        host = value.get("HostName") or value.get("IPAddress") or ""
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
        result["ports"][name] = {"host": host, "port": value.get("PortNumber", 9100),
                                   "protocol": value.get("Protocol"), "loopback": local,
                                   "monitor": "Standard TCP/IP Port",
                                   "snmp": value.get("SNMP Enabled"),
                                   "snmp_community": value.get("SNMP Community")}
    # Capture ports owned by other monitors (e.g. a different virtual-printer tool)
    # so an exported diagnostic can be compared against this queue side by side.
    for monitor in result["monitors"]:
        if monitor == "Standard TCP/IP Port":
            continue
        mports = base + "\\Monitors\\" + monitor + "\\Ports"
        for name in quiet_children(mports):
            if name not in result["ports"]:
                result["ports"][name] = {"monitor": monitor, "host": "", "port": None,
                                         "protocol": None, "loopback": False}
    for name in children(base + r"\Printers"):
        value = values(base + "\\Printers\\" + name)
        port_name = value.get("Port", "")
        attributes = value.get("Attributes")
        result["printers"].append({"name": name, "driver": value.get("Printer Driver", ""),
                                   "comment": value.get("Description", ""),
                                   "port_name": port_name,
                                   "attributes": attributes,
                                   "bidi_enabled": bool((attributes or 0) & 0x800),
                                   "work_offline": bool((attributes or 0) & 0x400),
                                   "endpoint": result["ports"].get(port_name)})
    return result

def owned_queues(inventory: dict) -> list[dict]:
    return [p for p in inventory.get("printers", []) if p.get("comment") == OWNER_COMMENT]

def choose_endpoint(inventory: dict, addresses: list[str] | None = None,
                    printer_addresses: list[str] | None = None) -> tuple[str, int, str]:
    if addresses is None:
        addresses = local_ipv4_addresses()
    endpoints = addresses if printer_addresses is None else printer_addresses
    dedicated = [p for p in owned_queues(inventory)
                 if p.get("port_name") in ((p.get("endpoint") or {}).get("host"),
                                           "IP_" + str((p.get("endpoint") or {}).get("host", "")))
                 and p.get("endpoint")
                 and p["endpoint"].get("host") in endpoints
                 and p["endpoint"].get("protocol") == 1
                 and int(p["endpoint"].get("port", 0)) == 9100]
    if len(dedicated) == 1:
        p = dedicated[0]
        return addresses[0] if addresses else "", int(p["endpoint"]["port"]), p["name"]
    return addresses[0] if addresses else "", 9100, ""

def address_change_notice(inventory: dict, addresses: list[str],
                          printer_addresses: list[str] | None = None) -> str:
    if not addresses:
        return ""
    endpoints = addresses if printer_addresses is None else printer_addresses
    replacement = endpoints[0] if endpoints else addresses[0]
    for printer in owned_queues(inventory):
        endpoint = printer.get("endpoint") or {}
        old = endpoint.get("host", "")
        if printer.get("port_name") not in (old, "IP_" + old) or old in endpoints:
            continue
        try:
            address = ipaddress.ip_address(old)
        except ValueError:
            continue
        if address.version == 4 and address.is_private and not address.is_loopback:
            return (f"재부팅/네트워크 변경으로 프린터 중계 주소가 바뀌었습니다 · {old} → {replacement} · "
                    "프린터 연결 갱신 필요: '프린터 연결'에서 갱신 계획을 확인하세요.")
    return ""

def find_converter(kind: str, project: Path) -> str | None:
    names = {"pcl": ("gpcl6win64.exe", "gpcl6win32.exe", "gpcl6"),
             "ps": ("gswin64c.exe", "gswin32c.exe", "gs")}[kind]
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    vendor = project / "vendor"
    if vendor.exists():
        for name in names:
            matches = sorted(vendor.rglob(name))
            if matches:
                return str(matches[0].resolve())
    if kind == "ps":
        for root in (Path("C:/Program Files/gs"), Path("C:/Program Files (x86)/gs")):
            if root.exists():
                for name in names:
                    matches = sorted(root.glob("*/bin/" + name), reverse=True)
                    if matches:
                        return str(matches[0])
    return None
