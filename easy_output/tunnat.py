"""Packet rewriting for the simple-mode relay (no WSL, no restart).

The relay owns a Wintun adapter whose subnet holds three addresses:

    host    assigned to Windows; the app listens here (19100 TCP, 1161 UDP)
    target  the printer address; never assigned to Windows
    peer    a stand-in sender; never assigned to Windows

Windows sends print traffic for target into the adapter. Instead of running a
TCP stack, the relay rewrites each packet so Windows' own stack completes the
connection with the app, and rewrites the replies back:

    host:E -> target:9100   becomes   peer:E -> host:19100
    host:19100 -> peer:E    becomes   target:9100 -> host:E

(the same for SNMP on 161/1161). Pings to target are answered so port setup
sees a live printer. Everything else is dropped.
"""
from __future__ import annotations

import struct

TCP, UDP, ICMP = 6, 17, 1
# printer-facing port -> app capture port
PORTS = {TCP: {9100: 19100}, UDP: {161: 1161}}


def checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def _transport_checksum(protocol: int, src: bytes, dst: bytes, segment: bytearray) -> None:
    offset = 16 if protocol == TCP else 6
    segment[offset:offset + 2] = b"\0\0"
    pseudo = src + dst + struct.pack("!BBH", 0, protocol, len(segment))
    value = checksum(pseudo + bytes(segment))
    if protocol == UDP and value == 0:
        value = 0xFFFF
    segment[offset:offset + 2] = struct.pack("!H", value)


def _rebuild(header: bytearray, src: bytes, dst: bytes, protocol: int, segment: bytearray) -> bytes:
    header[12:16], header[16:20] = src, dst
    header[10:12] = b"\0\0"
    header[10:12] = struct.pack("!H", checksum(bytes(header)))
    if protocol in (TCP, UDP):
        _transport_checksum(protocol, src, dst, segment)
    elif protocol == ICMP:
        segment[2:4] = b"\0\0"
        segment[2:4] = struct.pack("!H", checksum(bytes(segment)))
    return bytes(header) + bytes(segment)


def translate(packet: bytes, host: bytes, target: bytes, peer: bytes) -> bytes | None:
    """Return the packet to hand back to Windows, or None to drop it.

    Addresses are 4-byte IPv4 values (socket.inet_aton).
    """
    if len(packet) < 20 or packet[0] >> 4 != 4:
        return None
    ihl = (packet[0] & 0x0F) * 4
    total = struct.unpack("!H", packet[2:4])[0]
    if ihl < 20 or total < ihl or total > len(packet):
        return None
    if struct.unpack("!H", packet[6:8])[0] & 0x3FFF:  # fragments (MF or an offset)
        return None
    protocol, src, dst = packet[9], packet[12:16], packet[16:20]
    if src != host:
        return None
    header, segment = bytearray(packet[:ihl]), bytearray(packet[ihl:total])

    if dst == target:
        if protocol in PORTS and len(segment) >= (20 if protocol == TCP else 8):
            port = struct.unpack("!H", segment[2:4])[0]
            capture = PORTS[protocol].get(port)
            if capture is None:
                return None
            segment[2:4] = struct.pack("!H", capture)
            return _rebuild(header, peer, host, protocol, segment)
        if protocol == ICMP and len(segment) >= 8 and segment[0] == 8:  # echo request
            segment[0] = 0
            return _rebuild(header, target, host, protocol, segment)
        return None

    if dst == peer and protocol in PORTS and len(segment) >= (20 if protocol == TCP else 8):
        port = struct.unpack("!H", segment[0:2])[0]
        printer = {capture: printer for printer, capture in PORTS[protocol].items()}.get(port)
        if printer is None:
            return None
        segment[0:2] = struct.pack("!H", printer)
        return _rebuild(header, target, host, protocol, segment)
    return None
