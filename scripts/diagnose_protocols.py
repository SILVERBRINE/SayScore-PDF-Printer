#!/usr/bin/env python3
"""Read-only RAW/PJL/SNMP probes for a running SayScore endpoint."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import time

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from easy_output import snmp  # noqa: E402


OIDS = {
    "sysDescr": (1, 3, 6, 1, 2, 1, 1, 1, 0),
    "hrDeviceStatus": (1, 3, 6, 1, 2, 1, 25, 3, 2, 1, 5, 1),
    "hrPrinterStatus": (1, 3, 6, 1, 2, 1, 25, 3, 5, 1, 1, 1),
    "hrPrinterDetectedErrorState": (1, 3, 6, 1, 2, 1, 25, 3, 5, 1, 2, 1),
    "prtGeneralPrinterName": (1, 3, 6, 1, 2, 1, 43, 5, 1, 1, 16, 1),
    "prtGeneralSerialNumber": (1, 3, 6, 1, 2, 1, 43, 5, 1, 1, 17, 1),
    "ppmPrinterIEEE1284DeviceId": (1, 3, 6, 1, 4, 1, 2699, 1, 2, 1, 2, 1, 1, 3, 1),
    "samsungDriverMDL": (1, 3, 6, 1, 4, 1, 236, 11, 5, 1, 1, 1, 26, 0),
    "samsungDriverEXT": (1, 3, 6, 1, 4, 1, 236, 11, 5, 11, 53, 33, 4, 1, 2, 1, 1),
}


def _request(oids, pdu=0xA0, version=1, community="public", request_id=1,
             first=0, second=0):
    binds = b"".join(snmp._tlv(0x30, snmp._enc_oid(oid) + snmp._tlv(0x05, b""))
                     for oid in oids)
    body = (snmp._enc_int(request_id) + snmp._enc_int(first) + snmp._enc_int(second)
            + snmp._tlv(0x30, binds))
    return snmp._tlv(0x30, snmp._enc_int(version)
                     + snmp._tlv(0x04, community.encode("ascii")) + snmp._tlv(pdu, body))


def _integer(body):
    return int.from_bytes(body, "big", signed=True)


def _parse_reply(packet):
    _, start, _ = snmp._read_tlv(packet, 0)
    index = start
    _, _, index = snmp._read_tlv(packet, index)
    _, _, index = snmp._read_tlv(packet, index)
    pdu_tag, pstart, _ = snmp._read_tlv(packet, index)
    index = pstart
    _, request_start, request_end = snmp._read_tlv(packet, index); index = request_end
    _, error_start, error_end = snmp._read_tlv(packet, index); index = error_end
    _, error_index_start, error_index_end = snmp._read_tlv(packet, index); index = error_index_end
    _, list_start, list_end = snmp._read_tlv(packet, index)
    rows, cursor = [], list_start
    while cursor < list_end:
        _, bind_start, bind_end = snmp._read_tlv(packet, cursor)
        _, oid_start, oid_end = snmp._read_tlv(packet, bind_start)
        value_tag, value_start, value_end = snmp._read_tlv(packet, oid_end)
        body = packet[value_start:value_end]
        if value_tag == 0x04:
            value = body.decode("utf-8", "backslashreplace")
        elif value_tag in (0x02, 0x41, 0x42, 0x43, 0x46):
            value = _integer(body)
        elif value_tag == 0x06:
            value = ".".join(map(str, snmp._decode_oid(body)))
        elif value_tag in (0x80, 0x81, 0x82):
            value = {0x80: "noSuchObject", 0x81: "noSuchInstance", 0x82: "endOfMibView"}[value_tag]
        else:
            value = {"tag": hex(value_tag), "hex": body.hex()}
        rows.append({"oid": ".".join(map(str, snmp._decode_oid(packet[oid_start:oid_end]))),
                     "tag": hex(value_tag), "value": value})
        cursor = bind_end
    return {"pdu": hex(pdu_tag), "request_id": _integer(packet[request_start:request_end]),
            "error_status": _integer(packet[error_start:error_end]),
            "error_index": _integer(packet[error_index_start:error_index_end]), "values": rows}


def snmp_probe(host, community, timeout, oids, pdu=0xA0, version=1, first=0, second=0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    started = time.monotonic()
    try:
        sock.sendto(_request(oids, pdu=pdu, version=version, community=community,
                             request_id=int(time.time()) & 0x7fffffff,
                             first=first, second=second), (host, 161))
        packet, peer = sock.recvfrom(65535)
        return {"ok": True, "peer": f"{peer[0]}:{peer[1]}",
                "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                **_parse_reply(packet)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        sock.close()


def tcp_probe(host, port, timeout, payload=None):
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout) as client:
            result = {"ok": True, "local": f"{client.getsockname()[0]}:{client.getsockname()[1]}",
                      "elapsed_ms": round((time.monotonic() - started) * 1000, 1)}
            if payload is not None:
                client.sendall(payload)
                client.settimeout(timeout)
                reply = client.recv(16384)
                result["response_hex"] = reply.hex(" ")
                result["response_ascii"] = reply.decode("ascii", "backslashreplace")
            return result
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--community", default="public")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    report = {"timestamp": time.time(), "target": f"{args.host}:{args.port}",
              "tcp_connect": tcp_probe(args.host, args.port, args.timeout),
              "pjl_info_status": tcp_probe(args.host, args.port, args.timeout,
                  b"\x1b%-12345X@PJL INFO STATUS\r\n"),
              "pjl_info_id": tcp_probe(args.host, args.port, args.timeout,
                  b"\x1b%-12345X@PJL INFO ID\r\n"),
              # SNMPv1 returns one noSuchName error for the whole PDU, so use
              # one varbind per request to identify the exact failing OID.
              "snmp_v1_get": {name: snmp_probe(args.host, args.community, args.timeout,
                                                [oid], version=0)
                              for name, oid in OIDS.items()},
              "snmp_v2c_get": snmp_probe(args.host, args.community, args.timeout,
                                          list(OIDS.values()), version=1),
              "snmp_v2c_getnext": snmp_probe(args.host, args.community, args.timeout,
                  [(1, 3, 6, 1, 4, 1, 2699, 1, 2)], pdu=0xA1, version=1),
              "snmp_v2c_getbulk": snmp_probe(args.host, args.community, args.timeout,
                  [(1, 3, 6, 1, 2, 1, 1)], pdu=0xA5, version=1, second=8)}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        (args.output_dir / f"protocol-probe-{stamp}.json").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
