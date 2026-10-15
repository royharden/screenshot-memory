"""Actual SQLite/file transactional controls; synthetic bytes are not decoder output."""

import hashlib
import sqlite3

import pytest

from screenshot_memory.contracts import Collection, Item, StageStatus
from screenshot_memory.shared.vindex import Deleter, Store, StoreError

C, ITEM, OBJECT = "a" * 32, "b" * 32, "c" * 32
RAW = b"synthetic owned bytes, not an actual image"
NAMES = ("decode", "ocr", "caption", "text_embeddings", "image_embeddings")


def setup(tmp_path, *, original=True):
    store = Store(tmp_path / "private")
    store.create_collection(Collection(collection_id=C, generation=0))
    token = store.admit(
        Item(
            collection_id=C,
            item_id=ITEM,
            source_object_id=OBJECT,
            original_content_sha256=hashlib.sha256(RAW).hexdigest(),
            raw_source_revision="synthetic/1",
            revision=0,
            generation=0,
            collection_generation=0,
            encoded_bytes=len(RAW),
            width_px=1,
            height_px=1,
            state="pending",
            stages=tuple(StageStatus(stage=n, status="not_run", item_generation=0) for n in NAMES),
        )
    )
    if original:
        store.put_file(token, "original", RAW)
    return store, token


def output(old, name="decode"):
    fields = dict(
        revision=old.revision + 1,
        state="partial",
        stages=tuple(
            StageStatus(
                stage=name,
                status="ready",
                item_generation=old.generation,
                processing_revision="synthetic/1",
                result_sha256="d" * 64,
                provenance="synthetic",
            )
            if s.stage == name
            else s
            for s in old.stages
        ),
    )
    fields["source_grid_sha256" if name == "decode" else "evidence_artifact_sha256"] = "e" * 64
    return old.model_copy(update=fields)


def test_output_commits_one_revision_projection_stage_and_invalidates_cache(tmp_path):
    store, token = setup(tmp_path)
    store.put_cache("f" * 32, (token,), b"old cache")
    following = output(store.item(token))
    assert (
        store.publish_stage(token, 0, "decode", following, (("content", "1" * 32, b"x"),))
        == following
    )
    assert store.item(token).revision == 1
    assert store.get("content", token, "1" * 32) == b"x"
    with store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM stages").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM cache_entries").fetchone()[0] == 0


@pytest.mark.parametrize(
    "kind", ["stale_revision", "skip_revision", "bool_revision", "identity", "state"]
)
def test_invalid_update_cannot_change_metadata_or_payloads(tmp_path, kind):
    store, token = setup(tmp_path)
    before = store.item(token)
    following = output(before)
    expected = 0
    if kind == "stale_revision":
        expected = 1
    elif kind == "bool_revision":
        expected = False
    elif kind == "skip_revision":
        following = following.model_copy(update={"revision": 2})
    elif kind == "identity":
        following = following.model_copy(update={"width_px": 2})
    else:
        following = following.model_copy(update={"state": "deleting"})
    with pytest.raises(StoreError):
        store.publish_stage(token, expected, "decode", following, (("content", "1" * 32, b"x"),))
    assert store.item(token) == before
    assert store.get("content", token, "1" * 32) is None


def test_other_stage_change_refused_and_completed_output_is_immutable(tmp_path):
    store, token = setup(tmp_path)
    following = output(store.item(token))
    stages = tuple(
        StageStatus(stage="ocr", status="missing", reason="unavailable", item_generation=0)
        if s.stage == "ocr"
        else s
        for s in following.stages
    )
    with pytest.raises(StoreError, match="stage_identity_mismatch"):
        store.publish_stage(token, 0, "decode", following.model_copy(update={"stages": stages}))
    store.publish_stage(token, 0, "decode", following)
    with pytest.raises(StoreError, match="stage_output_immutable"):
        store.publish_stage(token, 1, "decode", output(following))


@pytest.mark.parametrize("original", [False, True])
def test_missing_or_modified_owned_original_refuses(tmp_path, original):
    store, token = setup(tmp_path, original=original)
    if original:
        store.object_path(C, ITEM, OBJECT).write_bytes(b"changed")
    with pytest.raises(StoreError):
        store.publish_stage(token, 0, "decode", output(store.item(token)))
    assert store.item(token).revision == 0


def test_deletion_prevents_late_publication(tmp_path):
    store, token = setup(tmp_path)
    following = output(store.item(token))
    Deleter(store).begin(C, ITEM)
    with pytest.raises(StoreError, match="generation_mismatch"):
        store.publish_stage(token, 0, "decode", following)


@pytest.mark.parametrize(
    "writes,fts",
    [
        ((("vectors", "1" * 32, b"x"),), ()),
        ((("content", "1" * 32, b"x"), ("content", "1" * 32, b"y")), ()),
        ((), (("item_fts", "1" * 32, "x"),)),
        ([("content", "1" * 32, b"x")], ()),
    ],
)
def test_closed_tables_duplicate_rows_and_tuple_bounds(tmp_path, writes, fts):
    store, token = setup(tmp_path)
    with pytest.raises(StoreError):
        store.publish_stage(token, 0, "decode", output(store.item(token)), writes, fts)
    assert store.item(token).revision == 0


def test_ocr_mid_transaction_failure_rolls_back_payload_fts_stage_and_revision(tmp_path):
    store, token = setup(tmp_path)
    store.publish_stage(token, 0, "decode", output(store.item(token)))
    before = store.item(token)
    with store.connection() as conn:
        conn.execute(
            "CREATE TRIGGER fail_publish BEFORE UPDATE OF metadata ON items "
            "BEGIN SELECT RAISE(ABORT,'synthetic fault'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.publish_stage(
            token,
            1,
            "ocr",
            output(before, "ocr"),
            (("lines", "1" * 32, b"synthetic line"),),
            (("line_fts", "1" * 32, "synthetic line"),),
        )
    assert store.item(token) == before
    with store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM lines").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM line_fts").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM stages").fetchone()[0] == 1


def test_projection_collision_cannot_replace_another_stage_or_manual_payload(tmp_path):
    store, token = setup(tmp_path)
    store.put("content", token, "1" * 32, b"original slot")
    with pytest.raises(StoreError, match="stage_row_collision"):
        store.publish_stage(
            token, 0, "decode", output(store.item(token)), (("content", "1" * 32, b"replacement"),)
        )
    assert store.get("content", token, "1" * 32) == b"original slot"
    assert store.item(token).revision == 0
