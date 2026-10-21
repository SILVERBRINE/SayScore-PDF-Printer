from __future__ import annotations

import ipaddress
import ctypes
import os
import socket

_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in
                          ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))

def _ipv4(value):
    try:
        address = ipaddress.ip_address(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("숫자로 된 IPv4 주소를 입력하세요.") from exc
    if address.version != 4:
        raise ValueError("IPv4 주소만 사용할 수 있습니다.")
    return address

def _is_private(address):
    return any(address in network for network in _PRIVATE_NETWORKS)

def _windows_addresses():
    u32 = ctypes.c_uint32

    class Header(ctypes.Structure):
        _fields_ = [("Length", u32), ("IndexOrFlags", u32)]

    class AlignedHeader(ctypes.Union):
        _anonymous_ = ("Fields",)
        _fields_ = [("Alignment", ctypes.c_uint64), ("Fields", Header)]

    class SocketAddress(ctypes.Structure):
        _fields_ = [("Address", ctypes.c_void_p), ("Length", ctypes.c_int)]

    class Unicast(ctypes.Structure):
        pass

    Unicast._anonymous_ = ("Header",)
    Unicast._fields_ = [
        ("Header", AlignedHeader), ("Next", ctypes.POINTER(Unicast)),
        ("Socket", SocketAddress), ("PrefixOrigin", ctypes.c_int),
        ("SuffixOrigin", ctypes.c_int), ("DadState", ctypes.c_int),
        ("ValidLifetime", u32), ("PreferredLifetime", u32), ("LeaseLifetime", u32),
        ("OnLinkPrefixLength", ctypes.c_ubyte)]

    class Adapter(ctypes.Structure):
        pass

    Adapter._anonymous_ = ("Header",)
    Adapter._fields_ = [
        ("Header", AlignedHeader), ("Next", ctypes.POINTER(Adapter)),
        ("AdapterName", ctypes.c_char_p), ("FirstUnicast", ctypes.POINTER(Unicast)),
        ("FirstAnycast", ctypes.c_void_p), ("FirstMulticast", ctypes.c_void_p),
        ("FirstDnsServer", ctypes.c_void_p), ("DnsSuffix", ctypes.c_wchar_p),
        ("Description", ctypes.c_wchar_p), ("FriendlyName", ctypes.c_wchar_p),
        ("PhysicalAddress", ctypes.c_ubyte * 8), ("PhysicalAddressLength", u32),
        ("Flags", u32), ("Mtu", u32), ("IfType", u32), ("OperStatus", ctypes.c_int)]

    try:
        get_adapters = ctypes.WinDLL("iphlpapi").GetAdaptersAddresses
        get_adapters.argtypes = [u32, u32, ctypes.c_void_p, ctypes.POINTER(Adapter),
                                 ctypes.POINTER(u32)]
        get_adapters.restype = u32
        size = u32(15000)
        for attempt in range(3):
            buffer = ctypes.create_string_buffer(size.value)
            head = ctypes.cast(buffer, ctypes.POINTER(Adapter))
            result = get_adapters(socket.AF_INET, 0x0E, None, head, ctypes.byref(size))
            if result == 232:
                return []
            if result == 111:
                continue
            if result:
                raise OSError(result, "GetAdaptersAddresses failed")
            break
        else:
            raise OSError("Adapter inventory changed repeatedly")
        addresses = []
        current = head
        while current:
            adapter = current.contents
            if adapter.OperStatus == 1 and adapter.IfType != 24:
                label = ((adapter.Description or "") + " " + (adapter.FriendlyName or "")).lower()
                virtual = any(word in label for word in ("virtual", "vethernet", "hyper-v", "vpn", "tunnel"))
                unicast = adapter.FirstUnicast
                while unicast:
                    entry = unicast.contents
                    if entry.DadState == 4 and entry.Socket.Length >= 8 and entry.Socket.Address:
                        raw = ctypes.string_at(entry.Socket.Address, 8)
                        if int.from_bytes(raw[:2], "little") == socket.AF_INET:
                            addresses.append((virtual, adapter.IndexOrFlags,
                                              socket.inet_ntoa(raw[4:8])))
                    unicast = entry.Next
            current = adapter.Next
        return [value for _, _, value in sorted(addresses)]
    except (OSError, AttributeError) as exc:
        raise OSError("Windows에서 현재 연결된 IPv4 주소를 확인하지 못했습니다. 네트워크 연결을 확인하세요.") from exc

def local_ipv4_addresses() -> list[str]:
    if os.name != "nt":
        raise OSError("실제 어댑터 IPv4 주소 자동 검색은 Windows에서 지원됩니다.")
    addresses = []
    for value in _windows_addresses():
        try:
            address = _ipv4(value)
        except ValueError:
            continue
        if _is_private(address) and str(address) not in addresses:
            addresses.append(str(address))
    return addresses

def validate_bind_address(host: str, allow_local_network: bool = False) -> str:
    address = _ipv4(host)
    if address.is_loopback:
        return str(address)
    if not _is_private(address):
        raise ValueError("127.x.x.x 또는 이 PC에 할당된 사설 IPv4 주소만 사용할 수 있습니다.")
    if not allow_local_network:
        raise ValueError("사설 IPv4 수신에는 이 PC 네트워크 주소 사용을 명시적으로 허용해야 합니다.")
    if str(address) not in local_ipv4_addresses():
        raise ValueError("현재 연결된 이 PC의 어댑터에 할당되지 않은 IPv4 주소입니다.")
    return str(address)

def is_local_peer(host: str) -> bool:
    try:
        address = _ipv4(host)
        return address.is_loopback or (_is_private(address) and str(address) in local_ipv4_addresses())
    except (ValueError, OSError):
        return False
