"""Explicit synthetic pixel-only worker for CLI orchestration tests, never a CLI mode."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from screenshot_memory.adapters.ocr import EngineLine, EnginePage, EngineWord
from screenshot_memory.ocr_command import (
    MAX_HEADER,
    WorkerReply,
    WorkerRequest,
    enter_worker_containment,
)

mode, marker, release, nonce = sys.argv[1:]
containment = enter_worker_containment()
print(json.dumps({"pid": os.getpid(), "nonce": nonce, "containment": containment}), flush=True)
request = WorkerRequest.model_validate_json(sys.stdin.buffer.readline(MAX_HEADER + 1))
pixels = sys.stdin.buffer.read(request.width * request.height * 4 + 1)
assert len(pixels) == request.width * request.height * 4
assert request.width == 32 and request.height == 20
if mode in {"hang", "child"}:
    descendant = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(120)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    Path(marker).write_text(json.dumps({"worker": os.getpid(), "child": descendant.pid}))
    if mode == "hang":
        time.sleep(120)
elif mode == "pause":
    Path(marker).write_text("pixel-only worker running")
    deadline = time.monotonic() + 25
    while not Path(release).exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert Path(release).exists()
if mode == "garbage":
    print("invalid-json", flush=True)
    raise SystemExit(0)
if mode == "oversize":
    sys.stdout.buffer.write(b"x" * (1024 * 1024 + 1))
    sys.stdout.buffer.flush()
    raise SystemExit(0)
quad = ((2.0, 2.0), (12.0, 2.0), (12.0, 8.0), (2.0, 8.0))
page = (
    EnginePage((), confirmed_blank=True)
    if mode == "blank"
    else EnginePage((EngineLine("Café", 0.73, quad, (EngineWord("Café", None, quad),)),))
)
reply = WorkerReply(
    nonce="0" * 32 if mode == "wrong-nonce" else nonce,
    config_sha256=request.config_sha256,
    status="ok",
    page=page,
)
sys.stdout.buffer.write(reply.model_dump_json().encode("utf-8"))
sys.stdout.buffer.flush()
