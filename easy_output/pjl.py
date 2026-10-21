from __future__ import annotations

from dataclasses import dataclass

UEL = b"\x1b%-12345X"


@dataclass(frozen=True)
class PjlInspection:
    kind: str
    response: bytes = b""
    commands: tuple[str, ...] = ()


class PjlResponder:
    """Classify short PJL control sessions without consuming print jobs."""

    MAX_QUERY_BYTES = 64 * 1024

    def __init__(self, identity: dict):
        self.identity = identity

    def inspect(self, data: bytes) -> PjlInspection:
        if not data:
            return PjlInspection("incomplete")
        if len(data) > self.MAX_QUERY_BYTES:
            return PjlInspection("print")

        leading = data.lstrip(b" \t\r\n\x00")
        if leading and UEL.startswith(leading):
            return PjlInspection("incomplete")

        cleaned = data.replace(UEL, b"").strip(b" \t\r\n\x00")
        if not cleaned:
            return PjlInspection("incomplete")
        prefix = cleaned.upper()
        if not prefix.startswith(b"@PJL"):
            if b"@PJL".startswith(prefix):
                return PjlInspection("incomplete")
            return PjlInspection("print")
        if b"\n" not in data and b"\r" not in data:
            return PjlInspection("incomplete")
        try:
            text = cleaned.decode("ascii")
        except UnicodeDecodeError:
            return PjlInspection("print")
        commands = tuple(line.strip() for line in text.replace("\r", "\n").split("\n")
                         if line.strip())
        if not commands:
            return PjlInspection("incomplete")

        upper = tuple(command.upper() for command in commands)
        print_commands = ("@PJL JOB", "@PJL SET", "@PJL ENTER", "@PJL EOJ",
                          "@PJL COMMENT", "@PJL DEFAULT", "@PJL INITIALIZE")
        if any(command.startswith(print_commands) for command in upper):
            return PjlInspection("print", commands=commands)
        if any(not command.startswith("@PJL") for command in upper):
            return PjlInspection("print", commands=commands)

        replies = []
        for original, command in zip(commands, upper):
            if command.startswith("@PJL INFO ID"):
                replies.extend(("@PJL INFO ID", f'"{self._model()}"'))
            elif command.startswith("@PJL INFO STATUS"):
                replies.extend(("@PJL INFO STATUS", "CODE=10001", 'DISPLAY="READY"', "ONLINE=TRUE"))
            elif command.startswith("@PJL INFO CONFIG"):
                replies.extend(("@PJL INFO CONFIG", f"MODEL={self._model()}",
                                f"SERIALNUMBER={self._serial()}", "LANGUAGES=PCLXL,PCL", "MEMORY=1024"))
            elif command.startswith("@PJL INFO MEMORY"):
                replies.extend(("@PJL INFO MEMORY", "TOTAL=1073741824", "LARGEST=1073741824"))
            elif command.startswith("@PJL INFO PAGECOUNT"):
                replies.extend(("@PJL INFO PAGECOUNT", "0"))
            elif command.startswith("@PJL ECHO"):
                replies.append(original)
            elif command.startswith(("@PJL INQUIRE", "@PJL DINQUIRE")):
                replies.extend((original, '"READY"'))
            elif command.startswith("@PJL USTATUS"):
                replies.extend((original, "CODE=10001", 'DISPLAY="READY"', "ONLINE=TRUE"))
            else:
                replies.extend((original, "ERROR=20001"))

        body = "\r\n".join(replies).encode("ascii", "replace") + b"\r\n"
        return PjlInspection("query", UEL + body + UEL, commands)

    def _model(self) -> str:
        return str(self.identity.get("model") or self.identity.get("descr") or
                   self.identity.get("name") or "SayScore PDF")[:127]

    def _serial(self) -> str:
        return str(self.identity.get("serial") or "SAYSCORE")[:64]
