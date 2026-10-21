"""Direct host/source joins and framing controls; no listener or native OCR execution."""

import hashlib
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image
from search.test_native_regions import handbuilt_ocr
from test_api import ORIGIN, TOKEN, collection, image, request, upload
from test_api import api as api

from screenshot_memory.contracts import MAX_IMAGE_BYTES, StageStatus
from screenshot_memory.ocr_records import (
    ARTIFACT_ROW,
    DECODE_ROW,
    DOCUMENT_ROW,
    processing_revision,
)
from screenshot_memory.shared.docio.identity import canonical_bytes
from screenshot_memory.shared.docio.models import PageSourceResult, ProcessingArtifact
from screenshot_memory.viewer_host import (
    ASSETS,
    DeadlineInput,
    LocalRequestHandler,
    ReadDeadline,
    ViewerApplication,
    load_assets,
)


def test_fixed_public_assets_have_no_session_token_and_private_routes_keep_admission(api):
    _, store = api
    assets = {name: b"public-code-only" for name, _ in ASSETS.values()}
    app = ViewerApplication(store, token=TOKEN, origin=ORIGIN, assets=assets)
    for path in ASSETS:
        result = request(
            app,
            "GET",
            path,
            omit=("HTTP_ORIGIN",),
            HTTP_AUTHORIZATION="",
            HTTP_SEC_FETCH_SITE="none",
        )
        assert result["status"] == 200
        assert TOKEN.encode() not in result["body"]
        assert "frame-ancestors 'none'" in result["headers"]["Content-Security-Policy"]
    for overrides in (
        {"HTTP_HOST": "evil.invalid"},
        {"REMOTE_ADDR": "192.0.2.1"},
        {"HTTP_ORIGIN": "null"},
        {"HTTP_SEC_FETCH_SITE": "cross-site"},
        {"QUERY_STRING": "token=not-admitted"},
    ):
        assert request(app, "GET", "/", **overrides)["status"] == 403
    assert request(app, "POST", "/collections", HTTP_AUTHORIZATION="")["status"] == 403
    assert request(app, "GET", "/assets/../private", HTTP_AUTHORIZATION="")["status"] == 403
    assert request(app, "POST", "/collections")["status"] == 201


def test_built_assets_require_complete_manifest_and_exact_bytes(tmp_path):
    assets = {name: b"public" for name, _ in ASSETS.values()}
    manifest = {
        "node_version": "v24.18.0",
        "source_profile": "utf8-lf/1",
        "sources": {},
        "assets": {name: hashlib.sha256(raw).hexdigest() for name, raw in assets.items()},
    }
    for name, raw in assets.items():
        (tmp_path / name).write_bytes(raw)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert load_assets(tmp_path) == assets
    (tmp_path / "viewer.mjs").write_bytes(b"changed")
    with pytest.raises(ValueError, match="viewer_build_mismatch"):
        load_assets(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"assets": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="viewer_build_required"):
        load_assets(tmp_path)


class ConnectionControl:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, timeout):
        self.timeouts.append(timeout)


def test_connection_reads_keep_framing_and_absolute_header_body_deadline():
    clock = [0.0]
    connection = ConnectionControl()
    stream = DeadlineInput(
        io.BytesIO(b"POST / HTTP/1.1\r\nHost: local\r\n\r\nabcNEXT"),
        connection,
        20,
        clock=lambda: clock[0],
    )
    assert stream.readline() == b"POST / HTTP/1.1\r\n"
    assert stream.readline() == b"Host: local\r\n"
    assert stream.readline() == b"\r\n"
    assert stream.read(3) == b"abc"  # No application read past Content-Length.
    assert connection.timeouts and max(connection.timeouts) <= 5
    clock[0] = 20
    with pytest.raises(ReadDeadline):
        stream.read(1)  # Even already-buffered bytes cannot refresh an expired phase.
    with pytest.raises(ReadDeadline):
        stream.readline()
    huge = DeadlineInput(io.BytesIO(b"X" * 17000 + b"\n"), ConnectionControl(), 20, clock=lambda: 0)
    with pytest.raises(ReadDeadline):
        huge.readline(65537)
    with pytest.raises(ReadDeadline):
        DeadlineInput(io.BytesIO(), ConnectionControl(), 20, clock=lambda: 0).read(
            MAX_IMAGE_BYTES + 1
        )


def parse_headers(raw):
    handler = object.__new__(LocalRequestHandler)
    handler.raw_requestline = b"POST /collections HTTP/1.1\r\n"
    handler.rfile = io.BytesIO(raw + b"\r\n")
    handler.server = SimpleNamespace(server_port=23456)
    errors = []
    handler.send_error = lambda code, *args, **kwargs: errors.append(code)
    return handler.parse_request(), errors


def test_http_host_and_ambiguous_framing_refuse_before_application_dispatch():
    assert parse_headers(b"Host: 127.0.0.1:23456\r\nContent-Length: 3\r\n") == (True, [])
    cases = [b"", b"Host: evil.invalid\r\n", b"Host: 127.0.0.1:23456\r\nHost: 127.0.0.1:23456\r\n"]
    host = b"Host: 127.0.0.1:23456\r\n"
    cases.extend(
        host + value
        for value in [
            b"Content-Length: 1\r\nContent-Length: 1\r\n",
            b"Content-Length: 1,1\r\n",
            b"Content-Length: -1\r\n",
            b"Content-Length: 8388609\r\n",
            b"Transfer-Encoding: chunked\r\n",
            b"Authorization: a\r\nAuthorization: b\r\n",
            b"Origin: a\r\nOrigin: a\r\n",
        ]
    )
    for value in cases:
        accepted, errors = parse_headers(value)
        assert not accepted and errors, value


def test_view_source_uses_real_grid_not_jpeg_exif_display_axes_and_missing_ocr_is_explicit(api):
    app, _ = api
    encoded = io.BytesIO()
    with Image.new("RGB", (8, 6), (10, 20, 30)) as value:
        exif = value.getexif()
        exif[274] = 6
        value.save(encoded, format="JPEG", exif=exif)
    path, item = upload(app, collection(app), encoded.getvalue(), "image/jpeg")
    detail = request(app, "GET", path + "/detail")["body"]
    assert detail["overlay_status"] == "ocr_not_run"
    assert detail["lines"] == detail["words"] == []
    rendered = request(app, "GET", path + "/render")
    assert rendered["status"] == 200
    with Image.open(io.BytesIO(rendered["body"])) as value:
        assert value.size == (item["width_px"], item["height_px"]) == (8, 6)
        assert value.getexif().get(274) is None
    assert request(app, "GET", path + "/original")["body"] == encoded.getvalue()


def publish_control(store, item):
    """Hand-built observed-tag control for binding checks, NOT observed native OCR."""
    token = store.token(item["collection_id"], item["item_id"])
    before = store.item(token)
    source = PageSourceResult.model_validate_json(store.get("content", token, DECODE_ROW))
    document, raw = handbuilt_ocr(before, source)
    artifact = ProcessingArtifact.model_validate_json(raw)
    sha = hashlib.sha256(raw).hexdigest()
    stage = StageStatus(
        stage="ocr",
        status="ready",
        item_generation=token.item_generation,
        processing_revision=processing_revision(artifact),
        result_sha256=sha,
        provenance="observed",
    )
    updated = before.model_copy(
        update={
            "revision": before.revision + 1,
            "evidence_artifact_sha256": sha,
            "stages": (before.stages[0], stage, *before.stages[2:]),
        }
    )
    store.publish_stage(
        token,
        before.revision,
        "ocr",
        updated,
        (
            ("content", DOCUMENT_ROW, canonical_bytes(document.model_dump(mode="json"))),
            ("content", ARTIFACT_ROW, raw),
        ),
    )


def test_viewer_regions_are_bound_to_real_source_then_refuse_foreign_tampered_deleted(api):
    app, store = api
    base, foreign = collection(app), collection(app)
    path, item = upload(app, base)
    publish_control(store, item)
    detail = request(app, "GET", path + "/detail")["body"]
    assert detail["overlay_status"] == "verified_retained_regions"
    assert detail["lines"][0]["box"] == [0.0, 1.0, 3.0, 4.0]
    assert detail["lines"][0]["text"] == "anonymous-control"
    assert detail["words"][0]["confidence"] is None
    for suffix in ("/detail", "/render"):
        assert request(app, "GET", foreign + "/" + item["item_id"] + suffix)["status"] == 409
    with store.transaction() as conn:
        conn.execute(
            "UPDATE content SET payload=? WHERE collection_id=? AND row_id=?",
            (b"tampered", item["collection_id"], ARTIFACT_ROW),
        )
    invalid = request(app, "GET", path + "/detail")["body"]
    assert invalid["overlay_status"] == "source_evidence_unavailable"
    assert invalid["lines"] == invalid["words"] == []
    assert request(app, "DELETE", path, b'{"confirm":true}')["body"]["status"] == "deleted"
    for suffix in ("/detail", "/render"):
        assert request(app, "GET", path + suffix)["status"] == 409


def test_display_encoding_bound_refuses_without_partial_image_or_original_loss(api, monkeypatch):
    from screenshot_memory import viewer_source

    app, _ = api
    path, _ = upload(app, collection(app))
    monkeypatch.setattr(viewer_source, "MAX_IMAGE_BYTES", 32)
    assert request(app, "GET", path + "/render")["status"] == 409
    assert request(app, "GET", path + "/original")["body"] == image()
