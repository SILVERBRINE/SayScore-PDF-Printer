from __future__ import annotations

import socket
import threading
import time
import traceback
from typing import Callable

def _enc_len(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    body = []
    while length:
        body.insert(0, length & 0xFF)
        length >>= 8
    return bytes([0x80 | len(body)]) + bytes(body)

def _tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _enc_len(len(value)) + value

def _enc_int(value: int) -> bytes:
    if value == 0:
        body = b"\x00"
    else:
        body = value.to_bytes((value.bit_length() + 8) // 8, "big", signed=True)
        while len(body) > 1 and ((body[0] == 0x00 and not body[1] & 0x80) or
                                 (body[0] == 0xFF and body[1] & 0x80)):
            body = body[1:]
    return _tlv(0x02, body)

def _enc_uint(tag: int, value: int) -> bytes:
    value &= 0xFFFFFFFF
    body = value.to_bytes(4, "big").lstrip(b"\x00") or b"\x00"
    if body[0] & 0x80:
        body = b"\x00" + body
    return _tlv(tag, body)

def _enc_base128(number: int) -> bytes:
    if number == 0:
        return b"\x00"
    out = []
    while number:
        out.insert(0, number & 0x7F)
        number >>= 7
    for index in range(len(out) - 1):
        out[index] |= 0x80
    return bytes(out)

def _enc_oid(oid: tuple[int, ...]) -> bytes:
    body = _enc_base128(40 * oid[0] + oid[1])
    for sub in oid[2:]:
        body += _enc_base128(sub)
    return _tlv(0x06, body)

def _read_tlv(data: bytes, index: int) -> tuple[int, int, int]:
    tag = data[index]
    first = data[index + 1]
    if first < 0x80:
        return tag, index + 2, index + 2 + first
    count = first & 0x7F
    if count == 0 or index + 2 + count > len(data):
        raise ValueError("SNMP length form not supported")
    length = int.from_bytes(data[index + 2:index + 2 + count], "big")
    start = index + 2 + count
    if start + length > len(data):
        raise ValueError("SNMP length exceeds packet")
    return tag, start, start + length

def _decode_oid(body: bytes) -> tuple[int, ...]:
    if not body:
        raise ValueError("empty OID")
    first = body[0]
    nodes = [first // 40, first % 40]
    value = 0
    for byte in body[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            nodes.append(value)
            value = 0
    return tuple(nodes)

HR_DEVICE_RUNNING = 2
PRINTER_STATUS_IDLE = 3
PPM_ROOT = (1, 3, 6, 1, 4, 1, 2699, 1, 2, 1)

def _decode_int(data: bytes) -> int:
    return int.from_bytes(data, "big", signed=True)

def _oid_text(oid: tuple[int, ...]) -> str:
    return ".".join(str(node) for node in oid)

class SnmpResponder:

    def __init__(self, identity: dict, log: Callable[[dict], None] | None = None):
        self.identity = identity
        self.log = log
        self.community = str(identity.get("community") or "public")
        self.query_count = 0
        self._start = time.monotonic()
        self._socket = None
        self._thread = None
        self._stop = threading.Event()
        self.host = None
        self.table = self._build_table(identity)
        self._oids = sorted(self.table)

    def _build_table(self, identity: dict) -> dict:
        descr = (identity.get("descr") or identity.get("name") or "SayScore PDF")[:255]
        name = (identity.get("name") or descr)[:255]
        serial = (identity.get("serial") or "")[:64]
        enterprise = tuple(identity.get("enterprise") or (0, 0))
        manufacturer = (identity.get("manufacturer") or "SayScore")[:127]
        model = (identity.get("model") or descr)[:127]
        device_id = identity.get("device_id") or (
            f"MFG:{manufacturer};MDL:{model};CMD:PJL,PCLXL,PCL;CLS:PRINTER;"
            f"DES:{model};SERIALNUMBER:{serial};")
        octet = lambda text: ("octet", text.encode("utf-8", "replace"))
        table = {
            (1, 3, 6, 1, 2, 1, 1, 1, 0): octet(descr),
            (1, 3, 6, 1, 2, 1, 1, 2, 0): ("oid", enterprise),
            (1, 3, 6, 1, 2, 1, 1, 3, 0): ("uptime", None),
            (1, 3, 6, 1, 2, 1, 1, 4, 0): octet(""),
            (1, 3, 6, 1, 2, 1, 1, 5, 0): octet(name),
            (1, 3, 6, 1, 2, 1, 1, 6, 0): octet(""),
            (1, 3, 6, 1, 2, 1, 1, 7, 0): ("int", 72),
            (1, 3, 6, 1, 2, 1, 25, 3, 2, 1, 3, 1): octet(descr),
            (1, 3, 6, 1, 2, 1, 25, 3, 2, 1, 5, 1): ("int", HR_DEVICE_RUNNING),
            (1, 3, 6, 1, 2, 1, 25, 3, 5, 1, 1, 1): ("int", PRINTER_STATUS_IDLE),
            (1, 3, 6, 1, 2, 1, 25, 3, 5, 1, 2, 1): ("octet", b"\x00"),
            (1, 3, 6, 1, 2, 1, 43, 5, 1, 1, 16, 1): octet(name),
            (1, 3, 6, 1, 2, 1, 43, 5, 1, 1, 17, 1): octet(serial),
            # Printer-MIB input objects requested by the installed Samsung
            # X4305 x64 autoconfiguration module during the live print test.
            (1, 3, 6, 1, 2, 1, 43, 8, 2, 1, 13, 1, 1): octet("Tray 1"),
            (1, 3, 6, 1, 2, 1, 43, 8, 2, 1, 14, 1, 1): octet(manufacturer),
            (1, 3, 6, 1, 2, 1, 43, 8, 2, 1, 18, 1, 1): octet("Tray 1"),
            # PWG 5107.1-2005 Printer Port Monitor MIB, one printer and one
            # enabled bidirectional RAW/9100 port. Table indices are both 1.
            PPM_ROOT + (1, 1, 0): octet("ko-KR"),
            PPM_ROOT + (1, 2, 0): ("gauge", 1),
            PPM_ROOT + (1, 3, 0): ("gauge", 1),
            PPM_ROOT + (2, 1, 1, 2, 1): octet(name),
            PPM_ROOT + (2, 1, 1, 3, 1): octet(device_id[:1023]),
            PPM_ROOT + (2, 1, 1, 4, 1): ("gauge", 1),
            PPM_ROOT + (2, 1, 1, 5, 1): ("int", 1),
            PPM_ROOT + (2, 1, 1, 6, 1): ("int", 1),
            PPM_ROOT + (2, 1, 1, 7, 1): octet("public"),
            PPM_ROOT + (2, 1, 1, 8, 1): ("int", 1),
            PPM_ROOT + (3, 1, 1, 2, 1, 1): ("int", 1),
            PPM_ROOT + (3, 1, 1, 3, 1, 1): octet("RAW 9100"),
            PPM_ROOT + (3, 1, 1, 4, 1, 1): octet(""),
            # chPort9100(11) is the PPM recommendation when no matching
            # Printer-MIB v2 prtChannelTable entry is exposed.
            PPM_ROOT + (3, 1, 1, 5, 1, 1): ("int", 11),
            PPM_ROOT + (3, 1, 1, 6, 1, 1): ("int", 9100),
            PPM_ROOT + (3, 1, 1, 7, 1, 1): ("int", 2),
            PPM_ROOT + (3, 1, 1, 8, 1, 1): ("int", 0),
            PPM_ROOT + (3, 1, 1, 9, 1, 1): ("int", 2),
        }
        # Driver-specific objects are supplied by an architecture/profile
        # layer.  This keeps the shared responder neutral while allowing an
        # observed driver request to be reproduced without adding an entire
        # speculative vendor MIB.
        for oid_text, value in dict(identity.get("vendor_oids") or {}).items():
            try:
                oid = tuple(int(node) for node in str(oid_text).strip(".").split("."))
                if isinstance(value, dict):
                    kind, payload = value["kind"], value.get("value")
                    table[oid] = (kind, payload.encode("utf-8", "replace")
                                  if kind == "octet" and isinstance(payload, str) else payload)
                else:
                    table[oid] = octet(str(value))
            except (KeyError, TypeError, ValueError):
                continue
        return table

    def _trace_value(self, oid):
        spec = self.table.get(oid)
        if spec is None:
            return None
        kind, value = spec
        if kind == "uptime":
            value = int((time.monotonic() - self._start) * 100)
        elif isinstance(value, bytes):
            value = value.decode("utf-8", "backslashreplace")
        elif isinstance(value, tuple):
            value = _oid_text(value)
        return {"type": kind, "value": value}

    def _encode_value(self, spec) -> bytes:
        kind, payload = spec
        if kind == "octet":
            return _tlv(0x04, payload if isinstance(payload, bytes) else payload.encode())
        if kind == "oid":
            return _enc_oid(payload)
        if kind == "int":
            return _enc_int(payload)
        if kind == "gauge":
            return _enc_uint(0x42, payload)
        if kind == "uptime":
            return _enc_uint(0x43, int((time.monotonic() - self._start) * 100))
        raise ValueError(f"unknown value kind {kind}")

    def _resolve(self, oid: tuple[int, ...], next_mode: bool, v2c: bool):
        if next_mode:
            following = [candidate for candidate in self._oids if candidate > oid]
            if not following:
                return oid, (b"\x82\x00" if v2c else None)
            target = following[0]
            return target, self._encode_value(self.table[target])
        if oid in self.table:
            return oid, self._encode_value(self.table[oid])
        return oid, (b"\x81\x00" if v2c else None)

    def handle(self, packet: bytes, peer=None) -> bytes | None:
        source_ip, source_port = None, None
        if isinstance(peer, (tuple, list)) and len(peer) >= 2:
            source_ip, source_port = str(peer[0]), int(peer[1])
        elif isinstance(peer, str):
            source_ip, separator, port_text = peer.rpartition(":")
            if not separator:
                source_ip = peer
            else:
                try:
                    source_port = int(port_text)
                except ValueError:
                    source_ip = peer
        trace = {"peer": peer, "source_ip": source_ip, "source_port": source_port,
                 "result": "malformed", "queries": []}
        try:
            tag, start, end = _read_tlv(packet, 0)
            if tag != 0x30:
                return None
            index = start
            vtag, vstart, vend = _read_tlv(packet, index)
            version = int.from_bytes(packet[vstart:vend], "big", signed=True)
            if version not in (0, 1):
                return None
            version_bytes = packet[index:vend]
            index = vend
            ctag, cstart, cend = _read_tlv(packet, index)
            if ctag != 0x04:
                return None
            community = packet[cstart:cend].decode("ascii", "backslashreplace")
            trace["community"] = community
            community_bytes = packet[index:cend]
            index = cend
            if community != self.community:
                trace["result"] = "community-mismatch"
                return None
            ptag, pstart, pend = _read_tlv(packet, index)
            if ptag not in (0xA0, 0xA1, 0xA5):
                return None
            v2c = version == 1
            if ptag == 0xA5 and not v2c:
                return None
            version_text = "2c" if v2c else "1"
            pdu_text = {0xA0: "GET", 0xA1: "GETNEXT", 0xA5: "GETBULK"}[ptag]
            trace.update(version=version_text, snmp_version=version_text,
                         pdu=pdu_text, pdu_type=pdu_text)

            field = pstart
            rtag, rstart, rend = _read_tlv(packet, field)
            request_id_bytes = packet[field:rend]
            field = rend
            _, es_start, es_end = _read_tlv(packet, field)
            first_control = _decode_int(packet[es_start:es_end])
            field = es_end
            _, ei_start, ei_end = _read_tlv(packet, field)
            second_control = _decode_int(packet[ei_start:ei_end])
            trace.update(request_id=_decode_int(packet[rstart:rend]),
                         non_repeaters=first_control if ptag == 0xA5 else None,
                         max_repetitions=second_control if ptag == 0xA5 else None)
            field = ei_end
            lstag, lstart, lsend = _read_tlv(packet, field)
            if lstag != 0x30:
                return None

            requested, answers = [], []
            error_status, error_index, position = 0, 0, 0
            cursor = lstart
            while cursor < lsend:
                position += 1
                _, bstart, bend = _read_tlv(packet, cursor)
                _, ostart, oend = _read_tlv(packet, bstart)
                oid = _decode_oid(packet[ostart:oend])
                requested.append(oid)
                cursor = bend

            if ptag == 0xA5:
                non_repeaters = max(0, min(first_control, len(requested)))
                max_repetitions = max(0, min(second_control, 32))
                expanded = []
                for oid in requested[:non_repeaters]:
                    expanded.append((oid, True))
                repeated = requested[non_repeaters:]
                current = list(repeated)
                for _ in range(max_repetitions):
                    for index, oid in enumerate(current):
                        expanded.append((oid, True))
                        answer_oid, value = self._resolve(oid, True, True)
                        if value != b"\x82\x00":
                            current[index] = answer_oid
                work = expanded
            else:
                work = [(oid, ptag == 0xA1) for oid in requested]

            for position, (oid, next_mode) in enumerate(work, 1):
                answer_oid, value = self._resolve(oid, next_mode, v2c)
                if value is None:
                    if error_status == 0:
                        error_status, error_index = 2, position
                    answers.append(_tlv(0x30, _enc_oid(oid) + _tlv(0x05, b"")))
                    result = "noSuchName"
                else:
                    answers.append(_tlv(0x30, _enc_oid(answer_oid) + value))
                    result = ("endOfMibView" if value == b"\x82\x00"
                              else "noSuchInstance" if value == b"\x81\x00" else "value")
                known = result not in ("noSuchName", "noSuchInstance")
                query_trace = {"oid": _oid_text(oid), "requested_oid": _oid_text(oid),
                               "response_oid": _oid_text(answer_oid), "result": result,
                               "unknown": not known, "known_or_unknown": known}
                if result == "value":
                    query_trace["response"] = self._trace_value(answer_oid)
                    query_trace["response_type"] = query_trace["response"]["type"]
                    query_trace["response_value"] = query_trace["response"]["value"]
                trace["queries"].append(query_trace)

            if error_status and not v2c:
                answers = [_tlv(0x30, _enc_oid(oid) + _tlv(0x05, b"")) for oid in requested]
            pdu_body = (request_id_bytes
                        + _enc_int(error_status if not v2c else 0)
                        + _enc_int(error_index if not v2c else 0)
                        + _tlv(0x30, b"".join(answers)))
            pdu = _tlv(0xA2, pdu_body)
            trace["result"] = "response"
            return _tlv(0x30, version_bytes + community_bytes + pdu)
        except (ValueError, IndexError) as exc:
            trace.update(result="malformed", error=f"{type(exc).__name__}: {exc}",
                         traceback=traceback.format_exc())
            return None
        finally:
            self.query_count += 1
            if self.log is not None:
                try:
                    self.log(trace)
                except Exception:
                    pass

    def start(self, host: str, port: int = 161):
        if self._thread is not None:
            raise RuntimeError("SNMP responder already running")
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.bind((host, int(port)))
            udp.settimeout(0.25)
        except OSError:
            udp.close()
            raise
        self.host = udp.getsockname()[0]
        self._socket = udp
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        udp = self._socket
        while not self._stop.is_set():
            try:
                packet, peer = udp.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                reply = self.handle(packet, peer)
                if reply is not None:
                    udp.sendto(reply, peer)
            except OSError as exc:
                if self.log is not None and not self._stop.is_set():
                    try:
                        self.log({"protocol": "snmp", "peer": None,
                                  "result": "socket-error",
                                  "error": f"{type(exc).__name__}: {exc}",
                                  "traceback": traceback.format_exc()})
                    except Exception:
                        pass
                break
            except Exception as exc:
                if self.log is not None:
                    try:
                        self.log({"protocol": "snmp", "peer": f"{peer[0]}:{peer[1]}",
                                  "result": "server-exception",
                                  "error": f"{type(exc).__name__}: {exc}",
                                  "traceback": traceback.format_exc()})
                    except Exception:
                        pass
                continue

    def stop(self):
        self._stop.set()
        udp, self._socket = self._socket, None
        if udp is not None:
            udp.close()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(2)
        self.host = None
