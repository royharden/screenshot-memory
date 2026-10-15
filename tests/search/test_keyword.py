"""Literal search and collection/deletion controls on actual SQLite FTS5."""

import hashlib

import pytest

from screenshot_memory.contracts import Collection, Item, StageStatus
from screenshot_memory.shared.vindex import Deleter, Store, StoreError
from screenshot_memory.shared.vindex.search import keyword_search

C = "a" * 32
D = "b" * 32


def add(store, n, body, collection=C):
    token = store.admit(
        Item(
            collection_id=collection,
            item_id=f"{n:032x}",
            source_object_id=f"{n + 100:032x}",
            original_content_sha256=hashlib.sha256(b"x").hexdigest(),
            raw_source_revision="toy/1",
            revision=0,
            generation=0,
            collection_generation=store.collection(collection).generation,
            encoded_bytes=1,
            width_px=1,
            height_px=1,
            state="pending",
            stages=tuple(
                StageStatus(stage=s, status="not_run", item_generation=0)
                for s in ("decode", "ocr", "caption", "text_embeddings", "image_embeddings")
            ),
        )
    )
    store.put_fts("item_fts", token, f"{n + 200:032x}", body)
    return token


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "private")
    for cid in (C, D):
        result.create_collection(Collection(collection_id=cid, generation=0))
    return result


def ids(hits):
    return tuple(h.token.item_id for h in hits)


def test_full_collection_thirtieth_candidate_and_stable_ties(store):
    for n in range(1, 31):
        add(store, n, "shared lastcanary" if n == 30 else "shared")
    assert ids(keyword_search(store, C, "lastcanary")) == (f"{30:032x}",)
    hits = keyword_search(store, C, "shared")
    assert len(hits) == 30
    # Same-length equal-frequency documents are ordered by opaque ID.
    assert ids(hits)[:29] == tuple(f"{n:032x}" for n in range(1, 30))
    assert len(set(ids(hits))) == 30


@pytest.mark.parametrize(
    "query",
    [
        "alpha OR beta",
        "alpha NOT beta",
        '"alpha"',
        "alpha*",
        "alpha:beta",
        "(alpha NEAR beta)",
        "alpha - beta",
    ],
)
def test_operator_syntax_is_literal_token_or_not_executed_grammar(store, query):
    add(store, 1, "alpha")
    add(store, 2, "beta")
    found = set(ids(keyword_search(store, C, query)))
    assert f"{1:032x}" in found
    if "beta" in query:
        assert f"{2:032x}" in found


@pytest.mark.parametrize("query", [" !!! ", '"()*:', "🙂"])
def test_empty_actual_tokenization_returns_empty(store, query):
    add(store, 1, "alpha")
    assert keyword_search(store, C, query) == ()


def test_unicode61_accent_case_cjk_and_query_deduplication(store):
    add(store, 1, "ộ CAFÉ 東京")
    assert ids(keyword_search(store, C, "o")) == (f"{1:032x}",)
    assert ids(keyword_search(store, C, "cafe")) == (f"{1:032x}",)
    assert ids(keyword_search(store, C, "東京")) == (f"{1:032x}",)
    assert keyword_search(store, C, "café café CAFE") == keyword_search(store, C, "cafe")


def test_foreign_rows_cannot_change_own_scores_or_results(store):
    add(store, 1, "alpha beta")
    add(store, 2, "alpha alpha")
    before = keyword_search(store, C, "alpha")
    for n in range(3, 25):
        add(store, n, "alpha " * n, D)
    assert keyword_search(store, C, "alpha") == before
    assert keyword_search(store, C, "absent") == ()


def test_best_row_one_vote_and_returned_tokens_current(store):
    token = add(store, 1, "alpha")
    store.put_fts("item_fts", token, "f" * 32, "alpha alpha")
    hits = keyword_search(store, C, "alpha")
    assert len(hits) == 1
    assert store.item(hits[0].token).item_id == token.item_id


def test_mark_delete_hides_and_invalidates_all_previous_result_tokens(store):
    first = add(store, 1, "alpha")
    add(store, 2, "alpha")
    old = keyword_search(store, C, "alpha")
    deleter = Deleter(store)
    deleter.begin(C, first.item_id)
    assert ids(keyword_search(store, C, "alpha")) == (f"{2:032x}",)
    for hit in old:
        with pytest.raises(StoreError, match="generation_mismatch"):
            store.item(hit.token)
    assert deleter.delete(C, first.item_id).status == "deleted"
    assert ids(keyword_search(store, C, "alpha")) == (f"{2:032x}",)


def test_stale_fts_generation_never_appears(store):
    token = add(store, 1, "canary")
    with store.transaction() as conn:
        conn.execute("UPDATE items SET generation=1 WHERE item_id=?", (token.item_id,))
    assert keyword_search(store, C, "canary") == ()


@pytest.mark.parametrize("query", ["", "x" * 1001, None, 1, True])
def test_invalid_query_bounds(store, query):
    with pytest.raises(StoreError, match="invalid_query"):
        keyword_search(store, C, query)


def test_collection_identity_and_absence(store):
    with pytest.raises(StoreError, match="invalid_id"):
        keyword_search(store, "../escape", "alpha")
    with pytest.raises(StoreError, match="collection_missing"):
        keyword_search(store, "c" * 32, "alpha")
