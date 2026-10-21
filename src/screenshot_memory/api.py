"""Explicit local WSGI collection lifecycle; importing starts no server or model."""

import hmac
import json
import re
import sqlite3
import tempfile
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from screenshot_memory.contracts import MAX_IMAGE_BYTES
from screenshot_memory.shared.vindex import Deleter, Store, StoreError
from screenshot_memory.workflow import create_collection, import_images, inspect_items

_ID = r"[0-9a-f]{32}"
_ITEMS = re.compile(rf"/collections/({_ID})/items(?:/({_ID})(/original|/detail|/render)?)?\Z")
_HEADERS = (
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
)


class _Refused(Exception):
    def __init__(self, status: int, reason: str):
        self.status, self.reason = status, reason


def _body(environ, limit: int) -> bytes:
    length = environ.get("CONTENT_LENGTH", "")
    if (
        type(length) is not str
        or re.fullmatch(r"0|[1-9][0-9]{0,8}", length) is None
        or environ.get("HTTP_TRANSFER_ENCODING")
    ):
        raise _Refused(400, "invalid_body_framing")
    count = int(length)
    if count > limit:
        raise _Refused(413, "body_limit")
    # WSGI owns HTTP framing. Reading past Content-Length can block a real socket.
    raw = environ["wsgi.input"].read(count)
    if type(raw) is not bytes or len(raw) != count:
        raise _Refused(400, "incomplete_body")
    return raw


def _empty(environ):
    if environ.get("CONTENT_LENGTH", "") == "" and not environ.get("HTTP_TRANSFER_ENCODING"):
        return
    if _body(environ, 0):
        raise _Refused(400, "unexpected_body")


class CollectionAPI:
    """One trusted private Store and a secret shared by its local clients.

    The embedding WSGI host must bind only the configured loopback authority and
    enforce connection/read deadlines. This callable neither starts a listener
    nor configures a public deployment. All requests require Bearer; mutations
    additionally require an exact Origin. See the read policy below.
    """

    def __init__(self, store: Store, *, token: str, origin: str):
        url = urlsplit(origin)
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or url.username is not None
            or url.password is not None
            or url.path
            or url.query
            or url.fragment
            or url.port is None
            or not 1 <= url.port <= 65535
            or origin != f"http://{url.netloc}"
        ):
            raise ValueError("exact_loopback_origin_required")
        if (
            type(token) is not str
            or not 32 <= len(token) <= 256
            or re.fullmatch(r"[A-Za-z0-9_-]+", token) is None
        ):
            raise ValueError("strong_bearer_token_required")
        self._store = store
        self._authorization = "Bearer " + token
        self._origin, self._host = origin, url.netloc

    def __call__(self, environ, start_response):
        try:
            # No storage, body read or URL interpretation before caller admission.
            authorization = environ.get("HTTP_AUTHORIZATION", "")
            read = environ.get("REQUEST_METHOD") == "GET"
            # Browsers normally omit Origin on same-origin GET. Absence is distinct
            # from an explicitly empty/null/foreign value. Metadata adds a refusal
            # signal, never a replacement for the secret or trusted host binding.
            origin_ok = environ.get("HTTP_ORIGIN") == self._origin or (
                read and "HTTP_ORIGIN" not in environ
            )
            fetch_ok = not read or (
                "HTTP_SEC_FETCH_SITE" not in environ
                or environ["HTTP_SEC_FETCH_SITE"] == "same-origin"
            )
            if (
                environ.get("HTTP_HOST") != self._host
                or not origin_ok
                or not fetch_ok
                or environ.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"}
                or environ.get("wsgi.url_scheme") != "http"
                or type(authorization) is not str
                or not authorization.isascii()
                or not hmac.compare_digest(authorization, self._authorization)
            ):
                raise _Refused(403, "caller_refused")
            if environ.get("QUERY_STRING", "") or environ.get("SCRIPT_NAME", ""):
                raise _Refused(400, "unsupported_url")
            status, payload, media = self._dispatch(environ)
        except _Refused as error:
            status, payload, media = (
                error.status,
                {"status": "refused", "reason": error.reason},
                None,
            )
        except StoreError:
            # Do not expose filesystem paths, SQLite messages or foreign IDs.
            status, payload, media = 409, {"status": "refused", "reason": "store_refused"}, None
        except (OSError, sqlite3.Error, ValidationError):
            status, payload, media = (
                503,
                {"status": "refused", "reason": "local_operation_failed"},
                None,
            )
        if media is None:
            payload = json.dumps(payload, allow_nan=False, sort_keys=True).encode("utf-8")
            media = "application/json"
        start_response(
            f"{status} {HTTPStatus(status).phrase}",
            [("Content-Type", media), ("Content-Length", str(len(payload))), *_HEADERS],
        )
        return [payload]

    def _dispatch(self, environ):
        method, path = environ.get("REQUEST_METHOD"), environ.get("PATH_INFO", "")
        if path == "/collections":
            if method != "POST":
                raise _Refused(405, "method_refused")
            _empty(environ)
            return 201, {"status": "created", "collection_id": create_collection(self._store)}, None
        match = _ITEMS.fullmatch(path)
        if match is None:
            raise _Refused(404, "route_not_found")
        collection, item_id, original = match.groups()
        if method == "GET":
            _empty(environ)
            if original == "/detail":
                from screenshot_memory.viewer_source import source_detail

                return 200, source_detail(self._store, collection, item_id), None
            if original == "/render":
                from screenshot_memory.viewer_source import source_png

                return 200, source_png(self._store, collection, item_id), "image/png"
            items = inspect_items(self._store, collection, item_id)
            if original:
                item = items[0]
                token = self._store.token(collection, item.item_id)
                raw = self._store.read_file(token, item.source_object_id)
                media = "image/png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
                return 200, raw, media
            return 200, {"status": "ok", "items": [i.model_dump(mode="json") for i in items]}, None
        if method == "POST" and item_id is None:
            media = environ.get("CONTENT_TYPE")
            if media not in {"image/png", "image/jpeg"}:
                raise _Refused(415, "png_or_jpeg_required")
            raw = _body(environ, MAX_IMAGE_BYTES)
            signature = b"\x89PNG\r\n\x1a\n" if media == "image/png" else b"\xff\xd8\xff"
            if not raw.startswith(signature):
                raise _Refused(400, "image_signature_mismatch")
            # Private temporary upload is never a caller path or managed original.
            # Existing import revalidates actual decoding and transactional quotas.
            with tempfile.TemporaryDirectory(prefix="smem-upload-") as directory:
                source = Path(directory) / "upload"
                source.write_bytes(raw)
                items = import_images(self._store, collection, (source,))
            return (
                201,
                {
                    "status": "imported_partial",
                    "items": [i.model_dump(mode="json") for i in items],
                    "model_execution": False,
                },
                None,
            )
        if method == "DELETE" and item_id is not None and original is None:
            if environ.get("CONTENT_TYPE") != "application/json":
                raise _Refused(415, "json_confirmation_required")
            raw = _body(environ, 64)
            # A closed confirmation wire avoids duplicate-key/coercion ambiguity.
            try:
                pairs = json.loads(raw, object_pairs_hook=list)
            except (ValueError, UnicodeError):
                raise _Refused(400, "delete_confirmation_required") from None
            if pairs != [("confirm", True)] or type(pairs[0][1]) is not bool:
                raise _Refused(400, "delete_confirmation_required")
            receipt = Deleter(self._store).delete(collection, item_id)
            status = {"deleted": 200, "cleanup_pending": 202, "not_found": 404}[receipt.status]
            return status, receipt.model_dump(mode="json"), None
        raise _Refused(405, "method_refused")
