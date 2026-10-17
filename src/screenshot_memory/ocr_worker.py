"""Private pixel-only native worker. No store, item token, downloads or fallback."""

import json
import os
import sys


def main() -> int:
    # Imports/containment precede the handshake; no native SDK or model runs here.
    from screenshot_memory.ocr_command import (
        MAX_HEADER,
        MAX_REPLY,
        WorkerReply,
        WorkerRequest,
        enter_worker_containment,
    )

    if len(sys.argv) != 2:
        return 2
    nonce = sys.argv[1]
    try:
        containment = enter_worker_containment()
    except OSError:
        return 2
    print(json.dumps({"pid": os.getpid(), "nonce": nonce, "containment": containment}), flush=True)
    try:
        from contextlib import redirect_stderr, redirect_stdout
        from pathlib import Path

        from screenshot_memory.adapters.rapidocr import LocalModels, RapidOcrEngine
        from screenshot_memory.contracts import MAX_IMAGE_PIXELS

        header = sys.stdin.buffer.readline(MAX_HEADER + 1)
        if len(header) > MAX_HEADER:
            return 2
        request = WorkerRequest.model_validate_json(header)
        count = request.width * request.height * 4
        if request.nonce != nonce or request.width * request.height > min(
            MAX_IMAGE_PIXELS, request.bounds.max_decoded_pixels
        ):
            return 2
        pixels = sys.stdin.buffer.read(count + 1)
        if len(pixels) != count:
            return 2
        engine = RapidOcrEngine(LocalModels(*(Path(p) for p in request.models)))
        if engine.identity.config_sha256 != request.config_sha256:
            return 2
        with open(os.devnull, "w") as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
            page = engine.recognize(pixels, request.width, request.height, request.bounds)
        reply = WorkerReply(
            nonce=nonce, config_sha256=request.config_sha256, status="ok", page=page
        )
    except Exception:
        # No exception payload, local path, model log or fabricated blank result.
        return 2
    payload = reply.model_dump_json().encode()
    if len(payload) > MAX_REPLY:
        return 2
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
