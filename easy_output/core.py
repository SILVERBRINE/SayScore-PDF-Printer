from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import threading
import time
import traceback
import uuid

from .network import is_local_peer, validate_bind_address
from .pjl import PjlResponder
from .snmp import SnmpResponder

class Engine:
    MAX_BYTES = 128 * 1024 * 1024
    RECEIVE_TIMEOUT = 30.0
    CONVERT_TIMEOUT = 120.0
    STABLE_SECONDS = 2.0

    @staticmethod
    def _replace(source, destination):
        for attempt in range(6):
            try:
                os.replace(source, destination)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))

    def __init__(self, root: Path, emit, ghostscript: str | None = None,
                 ghostpcl: str | None = None, *, receive_rate: int = 0,
                 snmp_enabled: bool = False, snmp_identity: dict | None = None,
                 trusted_peers: tuple[str, ...] = ()):
        self.receive_rate = max(0, int(receive_rate))
        # Addresses that are not this PC's but reach it only through SayScore's own
        # relay adapter (the simple-mode stand-in peer).
        self.trusted_peers = frozenset(trusted_peers)
        self.snmp_enabled = snmp_enabled
        self.snmp_identity = dict(snmp_identity or {})
        self._snmp = None
        self.snmp_active = False
        self.snmp_error = ""
        self.pjl_query_count = 0
        self.root = Path(root).resolve()
        self.inbox = self.root / "inbox"
        self.output = self.root / "output"
        self.jobs = self.root / "jobs"
        # Keep ``communication`` as a compatibility alias.  New builds put all
        # protocol evidence in one obvious, support-friendly directory.
        self.diagnostics = self.root / "diagnostics"
        self.communication = self.diagnostics
        for directory in (self.inbox, self.output, self.jobs, self.diagnostics):
            directory.mkdir(parents=True, exist_ok=True)
        self.emit = emit
        self.ghostscript = ghostscript
        self.ghostpcl = ghostpcl
        self._queue = queue.Queue(maxsize=32)
        self._stop = threading.Event()
        self._listener = None
        self._threads = []
        self._slots = threading.BoundedSemaphore(4)
        self._lock = threading.Lock()
        self._communication_lock = threading.Lock()
        self._communication_errors = []
        self._pjl = PjlResponder(self.snmp_identity)
        self._seen = {}
        self._submitted = {}
        self.port = None
        self.host = None
        for metadata in self.jobs.glob("*/metadata.json"):
            try:
                job = json.loads(metadata.read_text(encoding="utf-8"))
                if job.get("state") in ("receiving", "queued", "processing"):
                    self._update(job, "failed", "이전 실행이 중단되었습니다. 완료된 원본은 다시 시도할 수 있습니다.")
                source = Path(job.get("input", ""))
                if source.parent == self.inbox and job.get("capture_complete") and job.get("source_signature"):
                    self._submitted[source] = tuple(job["source_signature"])
            except (OSError, ValueError, KeyError):
                continue

    def _new(self, source):
        job_id = uuid.uuid4().hex
        folder = self.jobs / job_id
        folder.mkdir()
        job = {"id": job_id, "state": "receiving", "detail": "원본 수신 중",
               "input": str(source), "output": None, "created": time.time()}
        self._update(job)
        return job

    def _update(self, job, state=None, detail=None, **fields):
        if state is not None:
            job["state"] = state
        if detail is not None:
            job["detail"] = detail
        job.update(fields)
        job["updated"] = time.time()
        folder = self.jobs / job["id"]
        temporary = folder / "metadata.tmp"
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        self._replace(temporary, folder / "metadata.json")
        try:
            self.emit(dict(job))
        except Exception:
            pass

    def start(self, host="127.0.0.1", port=19100, *, allow_local_network=False,
              snmp_port=161):
        host = validate_bind_address(host, allow_local_network=allow_local_network)
        if self._listener is not None or any(t.is_alive() for t in self._threads):
            raise RuntimeError("Engine is already running or still stopping")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((host, port))
            listener.listen(4)
            listener.settimeout(0.25)
        except Exception:
            listener.close()
            raise
        self._stop.clear()
        self._listener = listener
        self.host = listener.getsockname()[0]
        self.port = listener.getsockname()[1]
        self._threads = []
        self._spawn(self._work)
        self._spawn(self._accept, listener)
        self._spawn(self._watch)
        self._start_snmp(self.host, snmp_port)
        return self.port

    def _start_snmp(self, host, port=161):
        self.snmp_active, self.snmp_error = False, ""
        if not self.snmp_enabled:
            return
        responder = SnmpResponder(
            self.snmp_identity,
            log=lambda record: self._log_communication("snmp-requests.jsonl", record))
        try:
            responder.start(host, port)
        except OSError as exc:
            self.snmp_error = (f"SNMP 응답기를 시작하지 못했습니다 (UDP {port}): {exc}. "
                               "Windows SNMP 서비스가 이미 161을 쓰고 있을 수 있습니다.")
            return
        self._snmp = responder
        self.snmp_active = True

    def _log_communication(self, filename, record):
        entry = {"timestamp": time.time(), **record}
        target = self.communication / filename
        try:
            with self._communication_lock:
                with target.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception as exc:
            # Diagnostics must never break printing, but failures must remain
            # visible through runtime-status / exported diagnostics.
            self._communication_errors.append({
                "timestamp": time.time(), "file": str(target),
                "error": f"{type(exc).__name__}: {exc}",
            })
            self._communication_errors = self._communication_errors[-20:]

    def communication_status(self):
        return {
            "snmp_queries": getattr(self._snmp, "query_count", 0),
            "pjl_queries": self.pjl_query_count,
            "log_directory": str(self.communication),
            "logging_errors": list(self._communication_errors),
        }

    def recent_communication(self, limit=200):
        records = {}
        for protocol, filename in (("snmp", "snmp-requests.jsonl"),
                                   ("pjl", "pjl-requests.jsonl"),
                                   ("tcp", "tcp-connections.jsonl"),
                                   ("errors", "protocol-errors.jsonl")):
            rows = []
            try:
                lines = (self.communication / filename).read_text(encoding="utf-8").splitlines()
                for line in lines[-max(0, int(limit)):]:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
            except OSError:
                pass
            records[protocol] = rows
        return records

    def _stop_snmp(self):
        responder, self._snmp = self._snmp, None
        self.snmp_active = False
        if responder is not None:
            responder.stop()

    def _spawn(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        with self._lock:
            self._threads = [t for t in self._threads if t.is_alive()]
            self._threads.append(thread)
        thread.start()

    def start_files_only(self):
        if self._listener is not None or any(t.is_alive() for t in self._threads):
            raise RuntimeError("Engine is already running or still stopping")
        self._stop.clear()
        self.host = None
        self.port = None
        self._threads = []
        self._spawn(self._work)
        self._spawn(self._watch)

    def stop(self):
        self._stop.set()
        self._stop_snmp()
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.close()
        deadline = time.monotonic() + 5
        for thread in list(self._threads):
            if thread is not threading.current_thread():
                thread.join(max(0, deadline - time.monotonic()))
        if any(t.is_alive() for t in self._threads):
            raise RuntimeError("종료를 기다리는 작업이 있습니다. 같은 저장 폴더에서 새 엔진을 시작하지 마세요.")
        with self._lock:
            while True:
                try:
                    job = self._queue.get_nowait()
                except queue.Empty:
                    break
                self._update(job, "failed", "앱 종료로 대기가 취소되었습니다. 저장된 원본으로 다시 시도하세요.")
                self._queue.task_done()

    def submit(self, path):
        source = Path(path).resolve(strict=True)
        if not source.is_file():
            raise ValueError("입력은 일반 파일이어야 합니다.")
        job = self._new(source)
        destination = self.jobs / job["id"] / "original.bin"
        try:
            before = source.stat()
            job["source_signature"] = [before.st_size, before.st_mtime_ns]
            with source.open("rb") as incoming, destination.open("wb") as saved:
                self._copy(incoming, saved)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("복사 중 원본이 변경되었습니다. 복사가 끝난 뒤 다시 시도하세요.")
            self._enqueue(job)
        except Exception as exc:
            self._update(job, "failed", str(exc))
        return job["id"]

    def retry(self, job_id):
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise ValueError("Invalid job ID")
        metadata = json.loads((self.jobs / job_id / "metadata.json").read_text(encoding="utf-8"))
        if not metadata.get("capture_complete"):
            raise ValueError("수신이 완료되지 않은 작업은 원래 프로그램에서 다시 인쇄해야 합니다.")
        return self.submit(self.jobs / job_id / "original.bin")

    def _copy(self, incoming, saved):
        count = 0
        while True:
            if self._stop.is_set():
                raise ValueError("앱 종료로 원본 복사가 중단되었습니다.")
            block = incoming.read(65536)
            if not block:
                break
            count += len(block)
            if count > self.MAX_BYTES:
                raise ValueError("128 MB 작업 크기 제한 초과; 원본 일부를 보관했습니다.")
            saved.write(block)
        if not count:
            raise ValueError("빈 인쇄 작업입니다.")

    def _enqueue(self, job):
        self._update(job, "queued", "PDF 변환 대기 중", capture_complete=True)
        with self._lock:
            if self._stop.is_set():
                self._update(job, "failed", "앱 종료로 대기가 취소되었습니다. 저장된 원본으로 다시 시도하세요.")
                return
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                self._update(job, "failed", "대기열이 가득 찼습니다. 저장된 원본으로 다시 시도하세요.")

    def _accept(self, listener):
        while not self._stop.is_set():
            try:
                connection, peer = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if peer[0] not in self.trusted_peers and not is_local_peer(peer[0]):
                self._log_communication("tcp-connections.jsonl", {
                    "event": "rejected", "reason": "non-local-peer",
                    "peer_ip": peer[0], "peer_port": peer[1],
                })
                connection.close()
                continue
            if not self._slots.acquire(blocking=False):
                self._log_communication("tcp-connections.jsonl", {
                    "event": "rejected", "reason": "connection-limit",
                    "peer_ip": peer[0], "peer_port": peer[1],
                })
                connection.close()
                continue
            connection_id = uuid.uuid4().hex
            destination = connection.getsockname()
            self._log_communication("tcp-connections.jsonl", {
                "event": "open", "connection_id": connection_id,
                "peer_ip": peer[0], "peer_port": peer[1],
                "source_ip": peer[0], "source_port": peer[1],
                "destination_ip": destination[0], "destination_port": destination[1],
            })
            self._spawn(self._receive, connection, peer, connection_id)

    @staticmethod
    def _header_preview(data, limit=4096, total_bytes=None):
        sample = bytes(data[:limit])
        # For a PJL-wrapped print job, protocol metadata ends at ENTER
        # LANGUAGE.  Never include PCL/PCLXL document bytes after that line.
        boundary = re.search(br"@PJL\s+ENTER\s+LANGUAGE\s*=\s*[^\r\n]+\r?\n", sample, re.I)
        body_omitted = boundary is not None and len(sample) > boundary.end()
        if body_omitted:
            sample = sample[:boundary.end()]
        return {
            "captured_bytes": len(sample),
            "truncated": (total_bytes if total_bytes is not None else len(data)) > len(sample),
            "document_body_omitted": body_omitted,
            "hex": sample.hex(" "),
            "ascii": "".join(chr(byte) if 32 <= byte < 127 else "." for byte in sample),
        }

    @staticmethod
    def _print_classification(data):
        """Classify only the page-description language visible in a short header."""
        sample = bytes(data[:4096]).lstrip(b" \t\r\n\x00")
        upper = sample.upper()
        language = re.search(br"@PJL\s+ENTER\s+LANGUAGE\s*=\s*([^\r\n]+)", upper)
        if language:
            value = language.group(1).strip(b' \t"')
            if value in (b"POSTSCRIPT", b"POSTSCRIPT2", b"POSTSCRIPT3", b"PS"):
                return "PRINT_PS"
            if value.startswith((b"PCL", b"PCLXL")):
                return "PRINT_PCL"
        if sample.startswith(b"%!"):
            return "PRINT_PS"
        if sample.startswith((b"\x1b", b") HP-PCL XL;")) or b"@PJL" in upper:
            return "PRINT_PCL"
        return "UNKNOWN"

    @staticmethod
    def _pjl_classification(commands):
        query_words = (" INFO ", " INQUIRE ", " DINQUIRE ", " ECHO ", " USTATUS ")
        normalized = tuple(f" {command.upper()} " for command in commands)
        return "PJL_QUERY" if any(any(word in command for word in query_words)
                                  for command in normalized) else "PJL_COMMAND"

    def _receive(self, connection, peer, connection_id=None):
        connection_id = connection_id or uuid.uuid4().hex
        session_started = time.monotonic()
        destination = connection.getsockname()
        job = None
        count = 0
        received_total = 0
        sent_total = 0
        first_bytes = bytearray()
        classification = "EMPTY_PROBE"
        close_reason = "eof"
        try:
            connection.settimeout(0.25)
            count = 0
            started = None
            last_data = time.monotonic()
            pending = bytearray()
            with ExitStack() as receiving:
                saved = None
                while True:
                    if self._stop.is_set():
                        raise ValueError("앱 종료로 수신이 중단되었습니다. 원본 일부를 보관했습니다.")
                    try:
                        block = connection.recv(65536)
                    except socket.timeout:
                        if time.monotonic() - last_data > self.RECEIVE_TIMEOUT:
                            if job is None:
                                close_reason = "idle-timeout"
                                return
                            raise ValueError("수신 시간 초과: 연결 종료(EOF)를 받지 못했습니다. 원본 일부를 보관했습니다.")
                        continue
                    if not block:
                        break
                    received_total += len(block)
                    if len(first_bytes) < 4096:
                        first_bytes.extend(block[:4096 - len(first_bytes)])
                    if job is None:
                        pending.extend(block)
                        inspection = self._pjl.inspect(bytes(pending))
                        if inspection.kind == "incomplete":
                            last_data = time.monotonic()
                            continue
                        if inspection.kind == "query":
                            classification = self._pjl_classification(inspection.commands)
                            self.pjl_query_count += 1
                            self._log_communication(
                                "pjl-requests.jsonl",
                                {"connection_id": connection_id,
                                 "peer_ip": peer[0], "peer_port": peer[1],
                                 "result": "response", "commands": list(inspection.commands),
                                 "response": self._header_preview(inspection.response)})
                            connection.sendall(inspection.response)
                            sent_total += len(inspection.response)
                            pending.clear()
                            last_data = time.monotonic()
                            continue
                        job = self._new(f"tcp://{peer[0]}:{peer[1]}")
                        classification = self._print_classification(pending)
                        saved = receiving.enter_context(
                            (self.jobs / job["id"] / "original.bin").open("wb"))
                        started = time.monotonic()
                        block = bytes(pending)
                        pending.clear()
                    last_data = time.monotonic()
                    count += len(block)
                    if count > self.MAX_BYTES:
                        raise ValueError("128 MB 작업 크기 제한 초과; 원본 일부를 보관했습니다.")
                    saved.write(block)
                    self._pace(count, started)
                    last_data = time.monotonic()
            if job is not None:
                self._enqueue(job)
        except Exception as exc:
            close_reason = "exception"
            self._log_communication("protocol-errors.jsonl", {
                "protocol": "tcp9100", "connection_id": connection_id,
                "peer_ip": peer[0], "peer_port": peer[1],
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })
            if job is not None:
                self._update(job, "failed", str(exc))
        finally:
            try:
                connection.close()
            finally:
                self._log_communication("tcp-connections.jsonl", {
                    "event": "close", "connection_id": connection_id,
                    "peer_ip": peer[0], "peer_port": peer[1],
                    "source_ip": peer[0], "source_port": peer[1],
                    "destination_ip": destination[0], "destination_port": destination[1],
                    "classification": classification, "reason": close_reason,
                    "received_bytes": received_total,
                    "bytes_sent": sent_total,
                    "connection_duration_ms": round((time.monotonic() - session_started) * 1000, 3),
                    "header": self._header_preview(first_bytes,
                                                   total_bytes=received_total),
                    "job_id": job.get("id") if job is not None else None,
                })
            self._slots.release()

    def _pace(self, count, started):
        if self.receive_rate <= 0:
            return
        target = started + count / self.receive_rate
        while True:
            remaining = target - time.monotonic()
            if remaining <= 0:
                return
            if self._stop.wait(min(remaining, 0.1)):
                return

    def _watch(self):
        while not self._stop.wait(0.5):
            try:
                paths = [p for p in self.inbox.iterdir() if p.is_file() and not p.name.startswith(".")
                         and p.suffix.lower() not in (".tmp", ".part", ".crdownload")]
                for path in paths:
                    try:
                        stat = path.stat()
                        signature = (stat.st_size, stat.st_mtime_ns)
                        if self._submitted.get(path) == signature:
                            continue
                        previous, since = self._seen.get(path, (None, time.monotonic()))
                        if previous != signature:
                            self._seen[path] = (signature, time.monotonic())
                        elif time.monotonic() - since >= self.STABLE_SECONDS:
                            self.submit(path)
                            self._submitted[path] = signature
                    except OSError:
                        continue
            except OSError:
                continue

    def _work(self):
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._convert(job)
            except Exception as exc:
                self._update(job, "failed", str(exc))
            finally:
                self._queue.task_done()

    @staticmethod
    def _payload(data):
        if data.startswith(b"\x1b%-12345X") or data.lstrip().startswith(b"@PJL"):
            match = re.search(br"@PJL\s+ENTER\s+LANGUAGE\s*=\s*[^\r\n]+\r?\n", data[:65536], re.I)
            if match is None:
                raise ValueError("PJL 작업에 지원되는 ENTER LANGUAGE 경계가 없습니다.")
            data = data[match.end():]
            ending = data.rfind(b"\x1b%-12345X")
            if ending >= 0:
                data = data[:ending]
        return data.lstrip(b"\r\n\t ")

    @staticmethod
    def _check_pdf(path):
        with Path(path).open("rb") as stream:
            header = stream.read(8)
            stream.seek(max(0, Path(path).stat().st_size - 4096))
            tail = stream.read()
        if not re.match(br"%PDF-[12]\.\d", header) or b"%%EOF" not in tail:
            raise ValueError("PDF 머리글 또는 끝 표시가 없습니다. 손상되었거나 수신이 덜 된 파일입니다.")

    def _convert(self, job):
        self._update(job, "processing", "인쇄 형식 확인 및 PDF 변환 중")
        folder = self.jobs / job["id"]
        original = (folder / "original.bin").read_bytes()
        language = re.search(br"@PJL\s+ENTER\s+LANGUAGE\s*=\s*(PCL(?:XL|6)?)[\r\n\s]", original[:65536], re.I)
        data = self._payload(original)
        temporary = folder / "converted.pdf"
        kind = "unknown"
        warnings = []
        if data.startswith(b"%PDF-"):
            kind = "PDF"
            temporary.write_bytes(data)
            self._check_pdf(temporary)
        else:
            if data.startswith(b"%!"):
                kind, converter = "PostScript", self.ghostscript
                guidance = "PostScript 변환에는 Ghostscript 실행 파일을 설정하세요."
            elif language or data.startswith((b"\x1b", b") HP-PCL XL;", b") HP-PCL XL")):
                kind, converter = "PCL", self.ghostpcl
                guidance = "PCL 드라이버 작업입니다. PostScript 드라이버로 변경하거나 GhostPCL 실행 파일을 설정하세요."
            else:
                raise ValueError("지원하지 않는 인쇄 형식입니다. PDF, PostScript 또는 PCL 작업이 필요합니다. XPS/EMF는 지원하지 않습니다.")
            if not converter:
                raise ValueError(guidance)
            payload = folder / "payload.bin"
            payload.write_bytes(data)
            command = [str(converter), "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
                       "-sOutputFile=" + str(temporary), "-f", str(payload)]
            with (folder / "converter.log").open("wb") as log:
                returncode = self._run_converter(command, log)
            if returncode != 0:
                raise ValueError(f"{kind} 변환 실패 (종료 코드 {returncode}). converter.log를 확인하세요.")
            with (folder / "converter.log").open("rb") as log:
                for line in log.read(65536).decode("utf-8", errors="replace").splitlines():
                    if any(word in line.lower() for word in ("warning", "unsupported", "may not be correct")):
                        warnings.append(line[:500])
            self._check_pdf(temporary)
        if self._stop.is_set():
            raise ValueError("앱 종료로 변환이 취소되었습니다. 원본을 보관했습니다.")
        target = self._readable_target(job)
        self._replace(temporary, target)
        detail = f"{kind} → PDF 저장 완료 (기본 형식 검사)"
        if warnings:
            detail += " · 변환기 경고: 출력 모양과 converter.log를 확인하세요."
        self._update(job, "completed", detail,
                     output=str(target), format=kind,
                     warnings=warnings,
                     validation="header-and-EOF-only; full PDF structure and visual fidelity not verified")

    def _readable_target(self, job):
        stamp = time.strftime("%Y-%m-%d %H%M%S", time.localtime(job.get("created") or time.time()))
        with self._lock:
            for number in range(1, 1000):
                suffix = "" if number == 1 else f" ({number})"
                target = self.output / f"인쇄 {stamp}{suffix}.pdf"
                if not target.exists():
                    target.touch()
                    return target
        return self.output / (job["id"] + ".pdf")

    def _run_converter(self, command, log):
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + self.CONVERT_TIMEOUT
        try:
            while process.poll() is None:
                if self._stop.wait(0.05):
                    raise ValueError("앱 종료로 변환이 취소되었습니다. 원본과 로그를 보관했습니다.")
                if time.monotonic() > deadline:
                    raise ValueError("변환 시간 제한 초과. 원본과 converter.log를 확인하세요.")
            return process.returncode
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
