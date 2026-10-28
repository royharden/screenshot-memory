"""Keyword HTTP boundary controls; retained synthetic text is not native OCR."""

import json

import pytest
from test_api import ORIGIN, TOKEN, collection, request, upload
from test_api import api as api

from screenshot_memory.api import CollectionAPI
from screenshot_memory.contracts import MAX_COUNTER
from screenshot_memory.shared.vindex import Deleter


def search(app, collection_id, text):
    return request(
        app, "POST", f"/collections/{collection_id}/query", json.dumps({"query": text}).encode()
    )


def test_keyword_route_preserves_missing_coverage_and_literal_collection_isolation(api):
    # Catches a route that invents feature coverage or searches another collection.
    app, store = api
    base = collection(app)
    cid = base.split("/")[2]
    _, item = upload(app, base)
    missing = search(app, cid, "café")
    assert missing["status"] == 200
    assert missing["body"]["status"] == "unavailable"
    assert missing["body"]["executed"] is False
    assert missing["body"]["coverage"]["unindexed_items"] == 1
    token = store.token(cid, item["item_id"])
    store.put_fts("item_fts", token, "d" * 32, "café literal retained control")
    found = search(app, cid, 'CAFÉ OR "')
    assert found["status"] == 200
    assert found["body"]["hits"][0]["item_id"] == item["item_id"]
    assert found["body"]["hits"][0]["declared_text_provenance"] == {}
    assert found["body"]["unavailable_legs"] == ["text_embeddings", "image_embeddings", "reranking"]
    foreign = collection(app).split("/")[2]
    assert search(app, foreign, "café")["body"]["hits"] == []


def test_query_hit_source_preserves_exact_large_token_and_refuses_after_delete(api, monkeypatch):
    # Catches JavaScript counter rounding and refreshing a stale hit to a new token.
    app, store = api
    base = collection(app)
    cid = base.split("/")[2]
    path, item = upload(app, base)
    with store.transaction() as conn:
        conn.execute(
            "UPDATE collections SET generation=? WHERE collection_id=?", (MAX_COUNTER - 1, cid)
        )
    token = store.token(cid, item["item_id"])
    store.put_fts("item_fts", token, "e" * 32, "needle")
    result = search(app, cid, "needle")["body"]
    wire = result["hits"][0]["generation_token"]
    assert wire["collection_generation"] == str(MAX_COUNTER - 1)
    body = json.dumps({"generation_token": wire}).encode()

    def no_refresh(*args):
        raise AssertionError("query-hit source must not obtain a replacement token")

    monkeypatch.setattr(store, "token", no_refresh)
    detail = request(app, "POST", path + "/detail", body)
    assert detail["status"] == 200 and detail["body"]["overlay_status"] == "ocr_not_run"
    assert request(app, "POST", path + "/render", body)["status"] == 200
    assert request(app, "POST", path + "/original", body)["status"] == 200
    receipt = Deleter(store).delete(cid, item["item_id"])
    assert receipt.status == "deleted"
    for suffix in ("/detail", "/render", "/original"):
        assert request(app, "POST", path + suffix, body)["status"] == 409


@pytest.mark.parametrize(
    "body",
    [
        b'{"query":""}',
        b'{"query":" "}',
        b'{"query":null}',
        b'{"query":[]}',
        b'{"query":"x","query":"y"}',
        b'{"query":"x","mode":"semantic"}',
        b'{"query":"\\ud800"}',
        json.dumps({"query": "x" * 1001}).encode(),
    ],
)
def test_query_closed_body_and_character_bounds(api, body):
    # Catches duplicate/coerced/oversized queries entering SQLite or selecting a model leg.
    app, _ = api
    cid = collection(app).split("/")[2]
    assert request(app, "POST", f"/collections/{cid}/query", body)["status"] == 400


def test_nested_query_json_refuses_before_storage_or_query(monkeypatch):
    # Catches decoder recursion escaping the API for a body below the byte cap.
    class NoStore:
        def __getattribute__(self, name):
            raise AssertionError("malformed JSON must not access storage")

    def no_query(*args, **kwargs):
        raise AssertionError("malformed JSON must not invoke keyword query")

    monkeypatch.setattr("screenshot_memory.api.query", no_query)
    app = CollectionAPI(NoStore(), token=TOKEN, origin=ORIGIN)
    body = b'{"query":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}"
    assert len(body) == 4011 < 8192
    result = request(app, "POST", f"/collections/{'a' * 32}/query", body)
    assert result["status"] == 400
    assert result["body"] == {"status": "refused", "reason": "invalid_request"}


def test_keyword_boundary_retains_auth_origin_media_and_body_limits(api):
    app, _ = api
    route = f"/collections/{collection(app).split('/')[2]}/query"
    body = b'{"query":"x"}'
    assert request(app, "POST", route, body, omit=("HTTP_AUTHORIZATION",))["status"] == 403
    assert request(app, "POST", route, body, HTTP_ORIGIN="http://foreign.invalid")["status"] == 403
    assert request(app, "POST", route, body, media="text/plain")["status"] == 415
    assert request(app, "POST", route, b"x" * 8193)["status"] == 413
    assert request(app, "GET", route)["status"] == 405
    assert TOKEN not in json.dumps(search(app, route.split("/")[2], "x")["body"])


def test_hit_source_rejects_foreign_numeric_or_duplicate_generation_tokens(api):
    app, store = api
    base = collection(app)
    cid = base.split("/")[2]
    path, item = upload(app, base)
    wire = store.token(cid, item["item_id"]).model_dump(mode="json")
    wire.update(
        collection_generation=str(wire["collection_generation"]),
        item_generation=str(wire["item_generation"]),
    )
    for changed in (
        {**wire, "collection_id": "f" * 32},
        {**wire, "item_generation": 0},
        {**wire, "item_generation": "00"},
        {**wire, "item_generation": str(MAX_COUNTER + 1)},
    ):
        assert (
            request(
                app, "POST", path + "/detail", json.dumps({"generation_token": changed}).encode()
            )["status"]
            == 400
        )
    duplicate = (
        json.dumps({"generation_token": wire})
        .replace('"item_generation":', '"item_generation":"0","item_generation":')
        .encode()
    )
    assert request(app, "POST", path + "/detail", duplicate)["status"] == 400
