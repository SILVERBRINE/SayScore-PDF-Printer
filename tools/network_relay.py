#!/usr/bin/env python3
"""Forward RAW/PJL TCP and SNMP UDP without inspecting print payloads."""
from __future__ import annotations

import argparse
import socket
import threading
import traceback


def _shutdown_quietly(sock: socket.socket, how: int) -> None:
    try:
        sock.shutdown(how)
    except OSError:
        pass


def _copy_stream(
    source: socket.socket,
    destination: socket.socket,
    direction: str,
    failed: threading.Event,
    failures: list[tuple[str, BaseException]],
) -> None:
    """Copy one half of a full-duplex connection with TCP backpressure.

    The sockets deliberately remain in blocking mode.  ``sendall`` on a
    non-blocking socket can raise EWOULDBLOCK for an otherwise healthy, large
    print job.  A thread per direction lets the kernel apply normal TCP
    backpressure while still allowing PJL replies to travel concurrently.
    """
    try:
        while not failed.is_set():
            block = source.recv(65536)
            if not block:
                _shutdown_quietly(destination, socket.SHUT_WR)
                return
            destination.sendall(block)
    except OSError as exc:
        if not failed.is_set():
            failures.append((direction, exc))
        failed.set()
        # Wake the pump blocked in the opposite direction.
        _shutdown_quietly(source, socket.SHUT_RDWR)
        _shutdown_quietly(destination, socket.SHUT_RDWR)


def copy_bidirectional(client: socket.socket, target_host: str, target_port: int) -> None:
    peer = client.getpeername()
    try:
        with socket.create_connection((target_host, target_port), timeout=10) as upstream:
            # create_connection's timeout is only needed while connecting.
            # Restore blocking operation before forwarding a print stream.
            upstream.settimeout(None)
            client.settimeout(None)
            failed = threading.Event()
            failures: list[tuple[str, BaseException]] = []
            forward = threading.Thread(
                target=_copy_stream,
                args=(client, upstream, "client->target", failed, failures),
                daemon=True,
            )
            forward.start()
            _copy_stream(upstream, client, "target->client", failed, failures)
            forward.join()
            if failures:
                direction, error = failures[0]
                raise OSError(f"{direction}: {error}") from error
    except Exception:
        print(f"tcp relay error peer={peer}:\n{traceback.format_exc()}", flush=True)
    finally:
        client.close()


def serve_tcp(listen_host: str, listen_port: int, target_host: str, target_port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((listen_host, listen_port))
        server.listen(64)
        print(f"tcp ready {listen_host}:{listen_port} -> {target_host}:{target_port}", flush=True)
        while True:
            client, _ = server.accept()
            threading.Thread(target=copy_bidirectional,
                             args=(client, target_host, target_port), daemon=True).start()


def serve_udp(listen_host: str, listen_port: int, target_host: str, target_port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind((listen_host, listen_port))
        print(f"udp ready {listen_host}:{listen_port} -> {target_host}:{target_port}", flush=True)
        while True:
            request, peer = server.recvfrom(65535)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream:
                    upstream.settimeout(5)
                    upstream.sendto(request, (target_host, target_port))
                    response, _ = upstream.recvfrom(65535)
                server.sendto(response, peer)
            except Exception:
                print(f"udp relay error peer={peer}:\n{traceback.format_exc()}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--raw-port", type=int, default=9100)
    parser.add_argument("--snmp-port", type=int, default=161)
    parser.add_argument("--target-raw-port", type=int)
    parser.add_argument("--target-snmp-port", type=int)
    args = parser.parse_args()
    target_raw_port = args.target_raw_port or args.raw_port
    target_snmp_port = args.target_snmp_port or args.snmp_port

    tcp = threading.Thread(target=serve_tcp,
                           args=(args.listen_host, args.raw_port,
                                 args.target_host, target_raw_port), daemon=True)
    udp = threading.Thread(target=serve_udp,
                           args=(args.listen_host, args.snmp_port,
                                 args.target_host, target_snmp_port), daemon=True)
    tcp.start()
    udp.start()
    tcp.join()
    udp.join()


if __name__ == "__main__":
    main()
