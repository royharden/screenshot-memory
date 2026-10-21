"""Explicit foreground loopback host. Importing this module opens no socket."""

import getpass
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from wsgiref.simple_server import ServerHandler, WSGIRequestHandler, make_server

from screenshot_memory.api import CollectionAPI
from screenshot_memory.contracts import MAX_IMAGE_BYTES
from screenshot_memory.shared.vindex import Store

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assets/viewer.mjs": ("viewer.mjs", "text/javascript; charset=utf-8"),
    "/assets/client.mjs": ("client.mjs", "text/javascript; charset=utf-8"),
    "/assets/model.mjs": ("model.mjs", "text/javascript; charset=utf-8"),
    "/assets/style.css": ("style.css", "text/css; charset=utf-8"),
}
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src blob:; "
    "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
)
READ_SECONDS = 20.0
HEADER_BYTES = 16 * 1024


def load_assets(directory=None):
    directory = (
        Path(directory) if directory is not None else Path(__file__).parent / "viewer_assets"
    )
    if directory.is_symlink():
        raise ValueError("unsafe_viewer_assets")
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 16384:
        raise ValueError("unsafe_viewer_manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {name for name, _ in ASSETS.values()}
    if (
        type(manifest) is not dict
        or set(manifest) != {"node_version", "source_profile", "sources", "assets"}
        or manifest["source_profile"] != "utf8-lf/1"
        or manifest["node_version"] != "v24.18.0"
        or type(manifest["assets"]) is not dict
        or set(manifest["assets"]) != expected
    ):
        raise ValueError("viewer_build_required")
    result = {}
    for name in expected:
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 128 * 1024:
            raise ValueError("unsafe_viewer_asset")
        raw = path.read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(raw).hexdigest() != manifest["assets"][name]:
            raise ValueError("viewer_build_mismatch")
        result[name] = raw
    return result


class ViewerApplication:
    """Public code-only fixed assets; every private route uses CollectionAPI admission."""

    def __init__(self, store, *, token, origin, assets):
        self.api = CollectionAPI(store, token=token, origin=origin)
        if set(assets) != {name for name, _ in ASSETS.values()}:
            raise ValueError("complete_assets_required")
        self.assets = assets

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path not in ASSETS:
            return self.api(environ, start_response)
        valid = (
            environ.get("REQUEST_METHOD") == "GET"
            and environ.get("HTTP_HOST") == self.api._host
            and environ.get("REMOTE_ADDR") == "127.0.0.1"
            and environ.get("wsgi.url_scheme") == "http"
            and not environ.get("QUERY_STRING", "")
            and not environ.get("SCRIPT_NAME", "")
            and ("HTTP_ORIGIN" not in environ or environ["HTTP_ORIGIN"] == self.api._origin)
            and (
                "HTTP_SEC_FETCH_SITE" not in environ
                or environ["HTTP_SEC_FETCH_SITE"] in {"none", "same-origin"}
            )
            and environ.get("CONTENT_LENGTH", "") in {"", "0"}
            and not environ.get("HTTP_TRANSFER_ENCODING")
        )
        if not valid:
            raw, status, media = b'{"status":"refused"}', "403 Forbidden", "application/json"
        else:
            name, media = ASSETS[path]
            raw, status = self.assets[name], "200 OK"
        start_response(
            status,
            [
                ("Content-Type", media),
                ("Content-Length", str(len(raw))),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
                ("Cross-Origin-Resource-Policy", "same-origin"),
                ("Content-Security-Policy", CSP),
            ],
        )
        return [raw]


class ReadDeadline(TimeoutError):
    pass


class DeadlineInput:
    """Bound request-line/header/body reads by one absolute connection deadline."""

    def __init__(self, raw, connection, deadline, *, clock=time.monotonic):
        self.raw, self.connection, self.deadline, self.clock = raw, connection, deadline, clock
        self.buffer = bytearray()
        self.header_bytes = 0

    def _fill(self, maximum):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise ReadDeadline("request_read_deadline")
        self.connection.settimeout(min(5.0, remaining))
        value = self.raw.read1(min(4096, maximum))
        self.buffer.extend(value)
        return bool(value)

    def read(self, count=-1):
        if self.clock() >= self.deadline:
            raise ReadDeadline("request_read_deadline")
        if type(count) is not int or not 0 <= count <= MAX_IMAGE_BYTES:
            raise ReadDeadline("unbounded_body_read")
        chunks, remaining = [], count
        while remaining:
            if not self.buffer and not self._fill(remaining):
                break
            size = min(remaining, len(self.buffer))
            chunks.append(bytes(self.buffer[:size]))
            del self.buffer[:size]
            remaining -= size
        if self.clock() >= self.deadline:
            raise ReadDeadline("request_read_deadline")
        return b"".join(chunks)

    def readline(self, limit=-1):
        if self.clock() >= self.deadline:
            raise ReadDeadline("request_read_deadline")
        limit = min(limit if limit >= 0 else HEADER_BYTES + 1, HEADER_BYTES + 1)
        while True:
            position = self.buffer.find(b"\n", 0, limit)
            size = position + 1 if position >= 0 else min(len(self.buffer), limit)
            if position >= 0 or size == limit:
                break
            if not self._fill(limit - len(self.buffer)):
                size = len(self.buffer)
                break
        self.header_bytes += size
        if self.header_bytes > HEADER_BYTES:
            raise ReadDeadline("request_header_limit")
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result

    def close(self):
        self.raw.close()


class _DiscardLog:
    def write(self, value):
        return len(value)

    def flush(self):
        pass


class _DeadlineResponse(ServerHandler):
    def _write(self, data):
        remaining = self.request_handler.deadline - time.monotonic()
        if remaining <= 0:
            raise ReadDeadline("connection_deadline")
        self.request_handler.connection.settimeout(min(5.0, remaining))
        return super()._write(data)


class LocalRequestHandler(WSGIRequestHandler):
    protocol_version = "HTTP/1.0"  # One request per connection; no pipelined-body ambiguity.

    def setup(self):
        super().setup()
        self.deadline = time.monotonic() + READ_SECONDS
        self.rfile = DeadlineInput(self.rfile, self.connection, self.deadline)

    def log_message(self, format, *args):
        pass  # No URLs, headers, bearer values, body content or tracebacks in logs.

    def get_stderr(self):
        return _DiscardLog()

    def send_error(self, code, message=None, explain=None):
        raw = b'{"status":"refused","reason":"http_request_refused"}'
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def parse_request(self):
        if not super().parse_request():
            return False
        self.close_connection = True
        if (
            len(self.headers.get_all("Host", [])) != 1
            or self.headers["Host"] != f"127.0.0.1:{self.server.server_port}"
            or any(
                len(self.headers.get_all(name, [])) > 1
                for name in (
                    "Content-Length",
                    "Content-Type",
                    "Authorization",
                    "Origin",
                    "Sec-Fetch-Site",
                )
            )
            or self.headers.get("Transfer-Encoding") is not None
        ):
            self.send_error(400)
            return False
        length = self.headers.get("Content-Length")
        if length is not None and (
            re.fullmatch(r"0|[1-9][0-9]{0,8}", length) is None or int(length) > MAX_IMAGE_BYTES
        ):
            self.send_error(413)
            return False
        return True

    def handle(self):
        try:
            self.raw_requestline = self.rfile.readline(HEADER_BYTES + 1)
            if not self.raw_requestline:
                return
            if not self.parse_request():
                return
            handler = _DeadlineResponse(
                self.rfile, self.wfile, self.get_stderr(), self.get_environ(), multithread=False
            )
            handler.request_handler = self
            handler.run(self.server.get_app())
        except OSError:
            self.close_connection = True


def serve(root, port):
    """Foreground only. Operators must allocate the owned loopback port before use."""
    root = Path(root).absolute()
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("explicit_valid_port_required")
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise ValueError("storage_inside_repository")
    assets = load_assets()  # Missing/mismatched build refuses before opening the listener.
    token = os.environ.pop("SMEM_VIEWER_TOKEN", "")
    if not token:
        if not sys.stdin.isatty():
            raise ValueError("viewer_token_required")
        token = getpass.getpass("Viewer token (hidden): ")
    app = ViewerApplication(
        Store(root), token=token, origin=f"http://127.0.0.1:{port}", assets=assets
    )
    with make_server("127.0.0.1", port, app, handler_class=LocalRequestHandler) as server:
        print(f"Viewer: http://127.0.0.1:{port} (foreground; Ctrl-C stops)")
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
    return 0
