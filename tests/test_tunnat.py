import socket
import struct
import unittest

from easy_output.tunnat import TCP, UDP, ICMP, checksum, translate

HOST, TARGET, PEER = (socket.inet_aton(a) for a in ("10.254.91.1", "10.254.91.2", "10.254.91.3"))


def ip(src, dst, protocol, segment):
    header = bytearray(struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(segment), 1, 0x4000, 64,
                                   protocol, 0, src, dst))
    header[10:12] = struct.pack("!H", checksum(bytes(header)))
    return bytes(header) + segment


def tcp(sport, dport, payload=b""):
    return struct.pack("!HHIIBBHHH", sport, dport, 1, 0, 5 << 4, 0x02, 65535, 0, 0) + payload


def udp(sport, dport, payload=b""):
    return struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload


def valid(packet):
    ihl = (packet[0] & 15) * 4
    if checksum(packet[:ihl]):
        return False
    protocol, src, dst, segment = packet[9], packet[12:16], packet[16:20], packet[ihl:]
    if protocol == ICMP:
        return checksum(segment) == 0
    pseudo = src + dst + struct.pack("!BBH", 0, protocol, len(segment))
    return checksum(pseudo + segment) == 0


class TranslateTest(unittest.TestCase):
    def test_print_connection_is_handed_to_the_app(self):
        out = translate(ip(HOST, TARGET, TCP, tcp(50000, 9100, b"%-12345X")), HOST, TARGET, PEER)
        self.assertEqual((out[12:16], out[16:20]), (PEER, HOST))
        self.assertEqual(struct.unpack("!HH", out[20:24]), (50000, 19100))
        self.assertTrue(out.endswith(b"%-12345X"))
        self.assertTrue(valid(out))

    def test_app_reply_appears_to_come_from_the_printer(self):
        out = translate(ip(HOST, PEER, TCP, tcp(19100, 50000)), HOST, TARGET, PEER)
        self.assertEqual((out[12:16], out[16:20]), (TARGET, HOST))
        self.assertEqual(struct.unpack("!HH", out[20:24]), (9100, 50000))
        self.assertTrue(valid(out))

    def test_snmp_both_ways(self):
        query = translate(ip(HOST, TARGET, UDP, udp(60000, 161, b"q")), HOST, TARGET, PEER)
        self.assertEqual(struct.unpack("!HH", query[20:24]), (60000, 1161))
        self.assertTrue(valid(query))
        reply = translate(ip(HOST, PEER, UDP, udp(1161, 60000, b"r")), HOST, TARGET, PEER)
        self.assertEqual((reply[12:16], struct.unpack("!HH", reply[20:24])), (TARGET, (161, 60000)))
        self.assertTrue(valid(reply))

    def test_ping_to_printer_is_answered(self):
        echo = struct.pack("!BBHHH", 8, 0, 0, 7, 1) + b"ping"
        echo = echo[:2] + struct.pack("!H", checksum(echo)) + echo[4:]
        out = translate(ip(HOST, TARGET, ICMP, echo), HOST, TARGET, PEER)
        self.assertEqual((out[12:16], out[16:20], out[20]), (TARGET, HOST, 0))
        self.assertTrue(valid(out))

    def test_other_traffic_is_dropped(self):
        for packet in (ip(HOST, TARGET, TCP, tcp(50000, 80)),           # other port
                       ip(HOST, PEER, TCP, tcp(445, 50000)),            # other reply port
                       ip(PEER, TARGET, TCP, tcp(50000, 9100)),         # not from Windows
                       ip(HOST, socket.inet_aton("224.0.0.22"), 2, b"\0" * 8),
                       b"\x60" + b"\0" * 39):                            # IPv6
            self.assertIsNone(translate(packet, HOST, TARGET, PEER))


if __name__ == "__main__":
    unittest.main()
