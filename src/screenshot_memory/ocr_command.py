"""Explicit OCR orchestration; only the parent can publish to the store.

The child receives pixels and explicit model paths, never a store root or token.
Its startup handshake precedes all native work. IPC and elapsed worker time are
bounded, and owned processes are closed before observations reach the adapter.
"""

import ctypes
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from typing import Literal

from pydantic import Field

from screenshot_memory.adapters.ocr import (
    EngineIdentity,
    EnginePage,
    OcrEngineError,
    StoreOcrAdapter,
)
from screenshot_memory.adapters.rapidocr import LocalModels, RapidOcrEngine
from screenshot_memory.contracts import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    Digest,
    Metadata,
    OpaqueID,
)
from screenshot_memory.ocr_records import DECODE_ROW
from screenshot_memory.regions import PillowSourceGridDecoder
from screenshot_memory.shared.docio.models import Bounds, PageSourceResult
from screenshot_memory.shared.vindex import Store

MAX_HEADER = 16 * 1024
MAX_REPLY = 1024 * 1024
MAX_TIMEOUT = 120.0


class WorkerRequest(Metadata):
    nonce: OpaqueID
    config_sha256: Digest
    models: tuple[str, str, str]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    bounds: Bounds


class WorkerReply(Metadata):
    nonce: OpaqueID
    config_sha256: Digest
    status: Literal["ok", "unavailable"]
    page: EnginePage | None = None


class _WindowsJob:
    """Contain the suspended launcher before its first instruction, including bootstrap."""

    def __init__(self):
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [
                ("user_time", ctypes.c_longlong),
                ("job_time", ctypes.c_longlong),
                ("flags", w.DWORD),
                ("min_ws", ctypes.c_size_t),
                ("max_ws", ctypes.c_size_t),
                ("active_limit", w.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", w.DWORD),
                ("scheduling", w.DWORD),
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", ctypes.c_ulonglong * 6),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        class Accounting(ctypes.Structure):
            _fields_ = [
                ("times", ctypes.c_longlong * 4),
                ("faults", w.DWORD),
                ("total", w.DWORD),
                ("active", w.DWORD),
                ("terminated", w.DWORD),
            ]

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        k.CreateJobObjectW.restype = w.HANDLE
        k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.QueryInformationJobObject.argtypes = [
            w.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            w.DWORD,
            ctypes.c_void_p,
        ]
        k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenProcess.restype = w.HANDLE
        k.CloseHandle.argtypes = [w.HANDLE]
        self.kernel = k
        self.accounting = Accounting
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("worker_job_unavailable")
        limits = Extended()
        limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway.
        if not k.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            k.CloseHandle(self.handle)
            raise OSError("worker_job_unavailable")

    def start(self, process):
        from ctypes import wintypes as w

        class ThreadEntry(ctypes.Structure):
            _fields_ = [
                ("size", w.DWORD),
                ("usage", w.DWORD),
                ("tid", w.DWORD),
                ("owner", w.DWORD),
                ("base_priority", w.LONG),
                ("delta_priority", w.LONG),
                ("flags", w.DWORD),
            ]

        k = self.kernel
        handle = k.OpenProcess(0x101, False, process.pid)  # SET_QUOTA | TERMINATE.
        if not handle:
            raise OSError("worker_job_unavailable")
        try:
            if not k.AssignProcessToJobObject(self.handle, handle):
                raise OSError("worker_job_unavailable")
        finally:
            k.CloseHandle(handle)
        k.CreateToolhelp32Snapshot.restype = w.HANDLE
        k.Thread32First.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
        k.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
        k.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenThread.restype = w.HANDLE
        k.ResumeThread.argtypes = [w.HANDLE]
        k.ResumeThread.restype = w.DWORD
        snapshot = k.CreateToolhelp32Snapshot(4, 0)  # SNAPTHREAD.
        if snapshot == ctypes.c_void_p(-1).value:
            raise OSError("worker_resume_unavailable")
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            more = k.Thread32First(snapshot, ctypes.byref(entry))
            while more:
                if entry.owner == process.pid:
                    thread = k.OpenThread(2, False, entry.tid)  # SUSPEND_RESUME.
                    if not thread:
                        raise OSError("worker_resume_unavailable")
                    try:
                        if k.ResumeThread(thread) != 1:
                            raise OSError("worker_resume_unavailable")
                        return
                    finally:
                        k.CloseHandle(thread)
                more = k.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            k.CloseHandle(snapshot)
        raise OSError("worker_resume_unavailable")

    def close(self) -> bool:
        k = self.kernel
        try:
            if not k.TerminateJobObject(self.handle, 1):
                return False
            deadline = time.monotonic() + 5
            while True:
                counts = self.accounting()
                if not k.QueryInformationJobObject(
                    self.handle, 1, ctypes.byref(counts), ctypes.sizeof(counts), None
                ):
                    return False
                if counts.active == 0:
                    return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.01)
        finally:
            k.CloseHandle(self.handle)


def enter_worker_containment() -> str:
    """Verify startup containment before releasing a pixel request to native code."""
    if os.name != "nt":
        if os.getpgrp() != os.getpid():
            raise OSError("worker_group_unavailable")
        return "process_group"
    from ctypes import wintypes as w

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.restype = w.HANDLE
    k.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
    contained = w.BOOL()
    if not k.IsProcessInJob(k.GetCurrentProcess(), None, ctypes.byref(contained)) or not contained:
        raise OSError("worker_job_unavailable")
    return "windows_job"


def _windows_worker_handle(pid: int, launcher_pid: int):
    """Verify the announced PID is this launcher or its direct child, then pin it."""
    from ctypes import wintypes as w

    class Entry(ctypes.Structure):
        _fields_ = [
            ("size", w.DWORD),
            ("usage", w.DWORD),
            ("pid", w.DWORD),
            ("heap", ctypes.c_size_t),
            ("module", w.DWORD),
            ("threads", w.DWORD),
            ("parent", w.DWORD),
            ("priority", w.LONG),
            ("flags", w.DWORD),
            ("name", w.WCHAR * 260),
        ]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = w.HANDLE
    k.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    k.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    k.CloseHandle.argtypes = [w.HANDLE]
    snapshot = k.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise OSError("worker_identity_unavailable")
    matched = False
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        more = k.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.pid == pid:
                matched = pid == launcher_pid or entry.parent == launcher_pid
                break
            more = k.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        k.CloseHandle(snapshot)
    if not matched:
        raise OSError("worker_identity_mismatch")
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    handle = k.OpenProcess(0x100001, False, pid)  # SYNCHRONIZE | PROCESS_TERMINATE.
    if not handle:
        raise OSError("worker_identity_unavailable")
    return k, handle


class ProcessOcrEngine:
    """Native engine behind bounded IPC; private injection is for trusted tests.

    There is no CLI/environment option to select another worker or identity.
    """

    def __init__(
        self, models: LocalModels, *, _command=None, _identity: EngineIdentity | None = None
    ):
        self.models = models
        self.identity = _identity or RapidOcrEngine(models).identity
        self._command = tuple(
            _command or (sys.executable, "-B", "-m", "screenshot_memory.ocr_worker")
        )
        self.last_worker_pid: int | None = None
        self.last_worker_closed = False

    def recognize(self, rgba8: bytes, width: int, height: int, bounds: Bounds) -> EnginePage:
        self.last_worker_pid = None
        self.last_worker_closed = False
        if (
            not math.isfinite(bounds.deadline_s)
            or not 0 < bounds.deadline_s <= MAX_TIMEOUT
            or width * height > min(MAX_IMAGE_PIXELS, bounds.max_decoded_pixels)
            or len(rgba8) != width * height * 4
        ):
            raise OcrEngineError("invalid_worker_bounds")
        nonce = uuid.uuid4().hex
        request = (
            WorkerRequest(
                nonce=nonce,
                config_sha256=self.identity.config_sha256,
                models=tuple(str(p) for p in self.models.paths().values()),
                width=width,
                height=height,
                bounds=bounds,
            )
            .model_dump_json()
            .encode()
            + b"\n"
        )
        if len(request) > MAX_HEADER:
            raise OcrEngineError("worker_header_limit")
        deadline = time.monotonic() + bounds.deadline_s
        job = _WindowsJob() if os.name == "nt" else None
        try:
            process = subprocess.Popen(
                [*self._command, nonce],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=os.name != "nt",
                creationflags=4 if job is not None else 0,  # CREATE_SUSPENDED.
            )
        except Exception:
            if job is not None:
                job.close()
            raise
        hello = threading.Event()
        finished = threading.Event()
        data: dict = {}
        errors = []
        writer = None
        handle = None
        kernel = None

        def read():
            try:
                line = process.stdout.readline(MAX_HEADER + 1)
                if len(line) > MAX_HEADER:
                    raise ValueError("hello_limit")
                data["hello"] = json.loads(line)
                hello.set()
                data["reply"] = process.stdout.read(MAX_REPLY + 1)
            except (OSError, ValueError) as exc:
                errors.append(type(exc).__name__)
            finally:
                hello.set()
                finished.set()

        def write():
            try:
                process.stdin.write(request)
                view = memoryview(rgba8)
                for offset in range(0, len(view), 65536):
                    process.stdin.write(view[offset : offset + 65536])
                process.stdin.close()
            except (OSError, ValueError) as exc:
                errors.append(type(exc).__name__)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            if job is not None:
                job.start(process)
            if not hello.wait(max(0, deadline - time.monotonic())):
                raise TimeoutError
            greeting = data.get("hello", {})
            pid = greeting.get("pid")
            if (
                type(pid) is not int
                or pid <= 0
                or greeting.get("nonce") != nonce
                or greeting.get("containment")
                != ("windows_job" if os.name == "nt" else "process_group")
            ):
                raise OcrEngineError("worker_startup_unavailable")
            if os.name == "nt":
                kernel, handle = _windows_worker_handle(pid, process.pid)
            elif pid != process.pid:
                raise OcrEngineError("worker_identity_mismatch")
            self.last_worker_pid = pid
            writer = threading.Thread(target=write, daemon=True)
            writer.start()
            if not finished.wait(max(0, deadline - time.monotonic())):
                raise TimeoutError
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
            raw = data.get("reply", b"")
            if process.returncode != 0 or errors or len(raw) > MAX_REPLY:
                raise OcrEngineError("worker_output_unavailable")
            reply = WorkerReply.model_validate_json(raw)
            if (
                reply.nonce != nonce
                or reply.config_sha256 != self.identity.config_sha256
                or reply.status != "ok"
                or reply.page is None
            ):
                raise OcrEngineError("worker_output_unavailable")
            return reply.page
        except subprocess.TimeoutExpired:
            raise TimeoutError from None
        finally:
            if job is not None:
                self.last_worker_closed = job.close()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.last_worker_closed = True
            if kernel is not None and handle is not None:
                try:
                    self.last_worker_closed = (
                        self.last_worker_closed and kernel.WaitForSingleObject(handle, 5000) == 0
                    )
                finally:
                    kernel.CloseHandle(handle)
            # No payload is released before the contained worker handshake.
            if writer is None:
                process.stdin.close()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            reader.join(timeout=1)
            if writer is not None:
                writer.join(timeout=1)
            process.stdout.close()
            if not self.last_worker_closed or reader.is_alive() or (writer and writer.is_alive()):
                raise OcrEngineError("worker_cleanup_unavailable")


def run_ocr(
    store: Store,
    collection_id: str,
    item_id: str,
    models: LocalModels | None,
    *,
    timeout_s: float = 30.0,
) -> dict:
    """Process only an explicitly selected admitted local item; never refresh its token."""
    if not math.isfinite(timeout_s) or not 0 < timeout_s <= MAX_TIMEOUT:
        return {"status": "refused", "reason": "ocr_timeout_bounds", "executed": False}
    token = store.token(collection_id, item_id)
    if models is None:
        return {"status": "unavailable", "reason": "ocr_models_not_configured", "executed": False}
    raw = store.get("content", token, DECODE_ROW)
    source = PageSourceResult.model_validate_json(raw or b"{}")
    if source.status != "ok" or len(source.pages) != 1:
        return {"status": "refused", "reason": "decode_not_ready", "executed": False}
    result = StoreOcrAdapter(
        store, token, PillowSourceGridDecoder(), ProcessOcrEngine(models)
    ).recognize(
        source.pages[0],
        Bounds(
            max_pages=1,
            max_encoded_bytes=MAX_IMAGE_BYTES,
            max_decoded_pixels=MAX_IMAGE_PIXELS,
            max_words=5000,
            max_lines=500,
            max_blocks=1,
            max_output_bytes=MAX_REPLY // 2,
            deadline_s=timeout_s,
        ),
    )
    return {
        "status": result.status,
        "executed": result.status == "ok",
        "ocr": result.model_dump(mode="json"),
    }
