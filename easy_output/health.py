from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

def queue_health(name="SayScore PDF"):
    if sys.platform != "win32":
        return {"state": "unknown", "detail": "Windows에서만 프린터 상태를 조회합니다."}
    spool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    spool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    spool.OpenPrinterW.restype = wintypes.BOOL
    spool.GetPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    spool.GetPrinterW.restype = wintypes.BOOL
    spool.ClosePrinter.argtypes = [wintypes.HANDLE]
    spool.ClosePrinter.restype = wintypes.BOOL
    handle = wintypes.HANDLE()
    if not spool.OpenPrinterW(name, ctypes.byref(handle), None):
        return {"state": "unknown", "detail": f"프린터 상태 조회 실패: Windows 오류 {ctypes.get_last_error()}"}
    try:
        needed = wintypes.DWORD()
        spool.GetPrinterW(handle, 6, None, 0, ctypes.byref(needed))
        if needed.value < ctypes.sizeof(wintypes.DWORD):
            return {"state": "unknown", "detail": f"프린터 상태 조회 실패: Windows 오류 {ctypes.get_last_error()}"}
        buffer = ctypes.create_string_buffer(needed.value)
        if not spool.GetPrinterW(handle, 6, buffer, len(buffer), ctypes.byref(needed)):
            return {"state": "unknown", "detail": f"프린터 상태 조회 실패: Windows 오류 {ctypes.get_last_error()}"}
        value = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
        if value & 0x80:
            state, detail = "offline", "오프라인"
        elif value & 1:
            state, detail = "paused", "일시 중지"
        elif value & 2:
            state, detail = "error", "오류"
        elif value == 0:
            state, detail = "online", "온라인 (Windows 상태값 0)"
        else:
            state, detail = "reported", f"Windows 상태값 {value}"
        return {"state": state, "status": value, "detail": detail}
    finally:
        spool.ClosePrinter(handle)
