"""Direct WSGI/core joins with real synthetic images; no listener or native model."""

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from screenshot_memory import workflow
from screenshot_memory.api import CollectionAPI
from screenshot_memory.contracts import MAX_IMAGE_BYTES, Collection
from screenshot_memory.shared.vindex import Store
from screenshot_memory.shared.vindex.deletion import STORES

TOKEN = "a" * 43
ORIGIN = "http://127.0.0.1:23456"


def request(app, method, path, body=b"", *, media="application/json", omit=(), **overrides):
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "HTTP_HOST": "127.0.0.1:23456",
        "HTTP_ORIGIN": ORIGIN,
        "HTTP_AUTHORIZATION": "Bearer " + TOKEN,
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.url_scheme": "http",
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": media,
        "wsgi.input": io.BytesIO(body),
        **overrides,
    }
    for key in omit:
        environ.pop(key, None)
    response = {}

    def start(status, headers):
        response.update(status=int(status.split()[0]), headers=dict(headers))

    raw = b"".join(app(environ, start))
    response["body"] = (
        json.loads(raw) if response["headers"]["Content-Type"] == "application/json" else raw
    )
    assert response["headers"]["Cache-Control"] == "no-store"
    assert response["headers"]["X-Content-Type-Options"] == "nosniff"
    assert "Access-Control-Allow-Origin" not in response["headers"]
    assert int(response["headers"]["Content-Length"]) == len(raw)
    return response


@pytest.fixture
def api(tmp_path):
    store = Store(tmp_path / "private")
    return CollectionAPI(store, token=TOKEN, origin=ORIGIN), store


def image(format="PNG"):
    stream = io.BytesIO()
    with Image.new("RGB", (16, 12), "blue") as value:
        value.save(stream, format=format)
    return stream.getvalue()


def collection(app):
    result = request(app, "POST", "/collections")
    assert result["status"] == 201
    return "/collections/" + result["body"]["collection_id"] + "/items"


def upload(app, base, raw=None, media="image/png"):
    result = request(app, "POST", base, image() if raw is None else raw, media=media)
    assert result["status"] == 201, result
    assert result["body"]["status"] == "imported_partial"
    assert result["body"]["model_execution"] is False
    item = result["body"]["items"][0]
    assert all(stage["status"] == "not_run" for stage in item["stages"][1:])
    return base + "/" + item["item_id"], item


@pytest.mark.parametrize("format,media", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
def test_real_upload_original_confirmed_all_store_delete_and_retry(api, format, media):
    app, store = api
    base = collection(app)
    raw = image(format)
    path, item = upload(app, base, raw, media)
    assert request(app, "GET", base)["body"]["items"][0]["item_id"] == item["item_id"]
    original = request(app, "GET", path + "/original", CONTENT_LENGTH="")
    assert original["status"] == 200
    assert original["body"] == raw
    assert original["headers"]["Content-Type"] == media
    receipt = request(app, "DELETE", path, b'{"confirm":true}')
    assert receipt["status"] == 200
    assert receipt["body"]["status"] == "deleted"
    assert tuple(receipt["body"]["stores_verified"]) == STORES
    assert receipt["body"]["files_absent"] == receipt["body"]["files_planned"] == 1
    assert not store.object_path(
        item["collection_id"], item["item_id"], item["source_object_id"]
    ).exists()
    assert request(app, "GET", path + "/original")["status"] == 409
    assert request(app, "GET", base)["body"]["items"] == []
    assert request(app, "DELETE", path, b'{"confirm":true}')["body"] == receipt["body"]
    with store.connection() as conn:
        for table in STORES:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_cross_collection_reads_and_delete_refuse_identical_foreign_item(api):
    app, _ = api
    first, second = collection(app), collection(app)
    path, a = upload(app, first)
    other, b = upload(app, second)
    foreign = first + "/" + b["item_id"]
    for suffix in ("", "/original"):
        assert request(app, "GET", foreign + suffix)["status"] == 409
    assert request(app, "DELETE", foreign, b'{"confirm":true}')["status"] == 404
    assert request(app, "GET", other + "/original")["body"] == image()
    assert request(app, "DELETE", path, b'{"confirm":true}')["status"] == 200
    assert request(app, "GET", other)["body"]["items"][0]["item_id"] == b["item_id"]
    assert a["original_content_sha256"] == b["original_content_sha256"]


def test_delete_requires_closed_explicit_boolean_confirmation(api):
    app, store = api
    path, item = upload(app, collection(app))
    bodies = [
        b"",
        b"{}",
        b'{"confirm":false}',
        b'{"confirm":1}',
        b'{"confirm":true,"confirm":true}',
        b'{"confirm":true,"extra":1}',
        b"null",
        b"[]",
        b"bad",
        b"\xff",
    ]
    for body in bodies:
        assert request(app, "DELETE", path, body)["status"] == 400, body
        assert store.item(store.token(item["collection_id"], item["item_id"])).state == "partial"
        assert (
            store.read_file(
                store.token(item["collection_id"], item["item_id"]), item["source_object_id"]
            )
            == image()
        )
    assert request(app, "GET", path + "/original")["status"] == 200


def test_authentication_refuses_before_storage_or_body_read(api, monkeypatch):
    app, store = api

    def forbidden(*args, **kwargs):
        raise AssertionError("refused caller accessed storage/body")

    class NoRead:
        read = forbidden

    monkeypatch.setattr(store, "create_collection", forbidden)
    cases = [
        {"HTTP_HOST": "attacker.invalid:23456"},
        {"HTTP_HOST": "127.0.0.1:23457"},
        {"HTTP_ORIGIN": "http://evil.invalid"},
        {"HTTP_ORIGIN": "null"},
        {"HTTP_ORIGIN": ""},
        {"HTTP_AUTHORIZATION": ""},
        {"HTTP_AUTHORIZATION": "Bearer " + "b" * 43},
        {"HTTP_AUTHORIZATION": "Bearer \u00e9"},
        {"REMOTE_ADDR": "192.0.2.1"},
        {"wsgi.url_scheme": "https"},
    ]
    for overrides in cases:
        result = request(app, "POST", "/collections", **{"wsgi.input": NoRead(), **overrides})
        assert result["status"] == 403, overrides
        with store.connection() as conn:
            assert conn.execute("SELECT count(*) FROM collections").fetchone()[0] == 0


def test_upload_framing_refusal_cannot_admit_items(api):
    app, store = api
    base = collection(app)
    cases = [
        ({"CONTENT_LENGTH": str(MAX_IMAGE_BYTES + 1)}, 413),
        ({"CONTENT_LENGTH": ""}, 400),
        ({"CONTENT_LENGTH": "-1"}, 400),
        ({"CONTENT_LENGTH": "1,1"}, 400),
        ({"CONTENT_LENGTH": "01"}, 400),
        ({"HTTP_TRANSFER_ENCODING": "chunked"}, 400),
        ({"CONTENT_LENGTH": "999"}, 400),
    ]
    for overrides, status in cases:
        result = request(app, "POST", base, image(), media="image/png", **overrides)
        assert result["status"] == status, overrides
        assert store.collection(base.split("/")[2]).item_count == 0


def test_upload_media_and_actual_decode_refusals(api):
    app, store = api
    base = collection(app)
    cases = [
        (b"bad", "image/png", 400),
        (image(), "image/jpeg", 400),
        (image(), "text/html", 415),
        (b"\x89PNG\r\n\x1a\ntruncated", "image/png", 409),
    ]
    for raw, media, status in cases:
        assert request(app, "POST", base, raw, media=media)["status"] == status, (raw, media)
        assert store.collection(base.split("/")[2]).item_count == 0


def test_count_pixels_and_collection_bytes_still_use_canonical_import_bounds(api, monkeypatch):
    app, store = api
    cid = "c" * 32
    store.create_collection(Collection(collection_id=cid, generation=0, cap=1))
    base = f"/collections/{cid}/items"
    upload(app, base)
    assert request(app, "POST", base, image(), media="image/png")["status"] == 409
    assert store.collection(cid).item_count == 1
    for limit in ("MAX_IMAGE_PIXELS", "MAX_COLLECTION_BYTES"):
        with monkeypatch.context() as patch:
            patch.setattr(workflow, limit, 1)
            target = collection(app)
            assert request(app, "POST", target, image(), media="image/png")["status"] == 409
            assert store.collection(target.split("/")[2]).item_count == 0


def test_failed_unlink_is_pending_hidden_then_verified_by_explicit_retry(api, monkeypatch):
    app, store = api
    path, item = upload(app, collection(app))
    original = store.object_path(item["collection_id"], item["item_id"], item["source_object_id"])
    unlink = Path.unlink

    def fail_target(self, *args, **kwargs):
        if self == original:
            raise PermissionError("test-owned locked original")
        return unlink(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_target)
        result = request(app, "DELETE", path, b'{"confirm":true}')
        assert result["status"] == 202
        assert result["body"]["status"] == "cleanup_pending"
        assert request(app, "GET", path + "/original")["status"] == 409
        assert original.exists()
    assert request(app, "DELETE", path, b'{"confirm":true}')["body"]["status"] == "deleted"
    assert not original.exists()


def test_unrecognized_paths_never_become_filesystem_paths(api):
    app, store = api
    for path in ("/collections/../items", "/collections/x/items", "/collections?x=1"):
        assert request(app, "GET", path)["status"] == 404, path
        with store.connection() as conn:
            assert conn.execute("SELECT count(*) FROM collections").fetchone()[0] == 0


def test_nonlocal_or_inexact_configuration_refuses(api):
    _, store = api
    for origin in (
        "https://127.0.0.1:23456",
        "http://evil.invalid:23456",
        "http://127.0.0.1",
        "http://127.0.0.1:23456/",
        "http://user@127.0.0.1:23456",
    ):
        with pytest.raises(ValueError):
            CollectionAPI(store, token=TOKEN, origin=origin)
        with store.connection() as conn:
            assert conn.execute("SELECT count(*) FROM collections").fetchone()[0] == 0


def test_browser_shaped_metadata_original_reads_without_origin_do_not_mutate(api):
    app, store = api
    base = collection(app)
    path, item = upload(app, base)
    before = store.collection(item["collection_id"])
    headers = [
        {"omit": ("HTTP_ORIGIN",)},
        {"omit": ("HTTP_ORIGIN",), "HTTP_SEC_FETCH_SITE": "same-origin"},
        {"HTTP_SEC_FETCH_SITE": "same-origin"},
    ]
    for options in headers:
        for route in (base, path):
            result = request(app, "GET", route, **options)
            assert result["status"] == 200
            assert result["body"]["items"][0]["item_id"] == item["item_id"]
        assert request(app, "GET", path + "/original", **options)["body"] == image()
        assert store.collection(item["collection_id"]) == before
        assert store.item(store.token(item["collection_id"], item["item_id"])).state == "partial"


def test_browser_read_refusals_precede_dispatch_and_body_io(api, monkeypatch):
    app, _ = api

    def forbidden(*args, **kwargs):
        raise AssertionError("refused browser read reached dispatch or body IO")

    class NoRead:
        read = forbidden

    monkeypatch.setattr(app, "_dispatch", forbidden)
    cases = [
        {"HTTP_AUTHORIZATION": "Bearer " + "b" * 43},
        {"HTTP_AUTHORIZATION": ""},
        {"HTTP_HOST": "evil.invalid:23456"},
        {"REMOTE_ADDR": "192.0.2.1"},
        {"wsgi.url_scheme": "https"},
        {"HTTP_ORIGIN": "null"},
        {"HTTP_ORIGIN": ""},
        {"HTTP_ORIGIN": "http://evil.invalid"},
        {"HTTP_SEC_FETCH_SITE": "cross-site"},
        {"HTTP_SEC_FETCH_SITE": "same-site"},
        {"HTTP_SEC_FETCH_SITE": "none"},
        {"HTTP_SEC_FETCH_SITE": ""},
        {"HTTP_ORIGIN": ORIGIN, "HTTP_SEC_FETCH_SITE": "cross-site"},
    ]
    for case in cases:
        options = {"HTTP_SEC_FETCH_SITE": "same-origin", "wsgi.input": NoRead(), **case}
        omitted = () if "HTTP_ORIGIN" in case else ("HTTP_ORIGIN",)
        result = request(app, "GET", "/collections/" + "a" * 32 + "/items", omit=omitted, **options)
        assert result["status"] == 403, case


def test_mutations_still_require_explicit_exact_origin_before_io(api, monkeypatch):
    app, _ = api

    def forbidden(*args, **kwargs):
        raise AssertionError("Origin-free mutation reached dispatch")

    monkeypatch.setattr(app, "_dispatch", forbidden)
    base = "/collections/" + "a" * 32 + "/items"
    for method, path, body in (
        ("POST", "/collections", b""),
        ("POST", base, image()),
        ("DELETE", base + "/" + "b" * 32, b'{"confirm":true}'),
    ):
        result = request(
            app, method, path, body, omit=("HTTP_ORIGIN",), HTTP_SEC_FETCH_SITE="same-origin"
        )
        assert result["status"] == 403, (method, path)


def test_browser_reads_keep_collection_isolation_and_deleted_original_refusal(api):
    app, _ = api
    first, second = collection(app), collection(app)
    path, a = upload(app, first)
    other, b = upload(app, second)
    headers = {"omit": ("HTTP_ORIGIN",), "HTTP_SEC_FETCH_SITE": "same-origin"}
    for suffix in ("", "/original"):
        assert request(app, "GET", first + "/" + b["item_id"] + suffix, **headers)["status"] == 409
    assert request(app, "DELETE", path, b'{"confirm":true}')["status"] == 200
    assert request(app, "GET", path + "/original", **headers)["status"] == 409
    assert request(app, "GET", other + "/original", **headers)["body"] == image()
    assert a["original_content_sha256"] == b["original_content_sha256"]
