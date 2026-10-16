"""SQLite/CLI metadata controls only: no images, decoding or model observations."""

import hashlib
import json

import pytest

from screenshot_memory.cli import main
from screenshot_memory.contracts import Collection, Item, StageStatus
from screenshot_memory.keyword_query import query_keywords
from screenshot_memory.ocr_records import ARTIFACT_ROW, processing_revision
from screenshot_memory.shared.docio.identity import artifact_bytes
from screenshot_memory.shared.docio.models import AffineTransform, ProcessingArtifact, Word
from screenshot_memory.shared.vindex import Deleter, Store, StoreError
from screenshot_memory.shared.vindex.search import keyword_search, keyword_snapshot

C = "a" * 32
D = "b" * 32


@pytest.fixture(autouse=True)
def no_image_or_model_execution(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"rapidocr", "onnxruntime", "onnx", "cv2", "numpy", "PIL"}:
            raise AssertionError("native SDK import forbidden in metadata-only checks")
        return real_import(name, *args, **kwargs)

    def image_forbidden(*args, **kwargs):
        raise AssertionError("image operations forbidden in metadata-only checks")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(Store, "read_file", image_forbidden)


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "private")
    for cid in (C, D):
        result.create_collection(Collection(collection_id=cid, generation=0))
    return result


def item(store, n, collection=C, *, synthetic=False, artifact=None):
    # Hand-authored metadata controls, never decoded images or engine output.
    if artifact is not None:
        synthetic = True
    digest = hashlib.sha256(artifact_bytes(artifact)).hexdigest() if artifact else "3" * 64
    stages = tuple(
        StageStatus(
            stage=stage,
            status="ready",
            item_generation=0,
            processing_revision=processing_revision(artifact)
            if artifact and stage == "ocr"
            else "metadata-control/1",
            result_sha256=digest if artifact and stage == "ocr" else "1" * 64,
            provenance="synthetic",
        )
        if synthetic and stage in {"decode", "ocr"}
        else StageStatus(stage=stage, status="not_run", item_generation=0)
        for stage in ("decode", "ocr", "caption", "text_embeddings", "image_embeddings")
    )
    value = Item(
        collection_id=collection,
        item_id=f"{n:032x}",
        source_object_id=f"{n + 100:032x}",
        original_content_sha256=hashlib.sha256(b"metadata-control").hexdigest(),
        raw_source_revision="metadata-control/1",
        revision=0,
        generation=0,
        collection_generation=store.collection(collection).generation,
        encoded_bytes=1,
        width_px=1,
        height_px=1,
        state="partial" if synthetic else "pending",
        source_grid_sha256="2" * 64 if synthetic else None,
        evidence_artifact_sha256=digest if synthetic else None,
        stages=stages,
    )
    token = store.admit(value)
    if artifact is not None:
        store.put("content", token, ARTIFACT_ROW, artifact_bytes(artifact))
    return token


def empty_ocr(n=1, **updates):
    """Canonical synthetic wire only; no source pixels or OCR engine execution."""
    matrix = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    return ProcessingArtifact(
        **(
            dict(
                artifact_id="empty-control",
                document_id=f"{n:032x}",
                raw_source_revision="metadata-control/1",
                page_id=f"{n:032x}:page:0",
                page_index=0,
                width_px=1,
                height_px=1,
                page_sha256="2" * 64,
                grid_policy_id="metadata-grid/1",
                words=(),
                lines=(),
                blocks=(),
                engine="synthetic-empty-control",
                engine_version="1",
                config_digest="4" * 64,
                source_to_engine=AffineTransform(
                    direction="source_to_engine", algorithm="identity", matrix=matrix
                ),
                engine_to_source=AffineTransform(
                    direction="engine_to_source", algorithm="identity", matrix=matrix
                ),
            )
            | updates
        )
    )


def projection(store, token, text, row="f" * 32):
    store.put_fts("item_fts", token, row, text)


def test_reopened_cli_ranked_keyword_ids_and_delete_no_return(store, capsys):
    token = item(store, 1, synthetic=True)
    projection(store, token, "café settings")
    other = item(store, 2, D)
    projection(store, other, "cafe settings")
    args = ["--root", str(store.root), "--collection", C]
    assert main(["query", *args, "cafe", "--mode", "keyword"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ok" and result["executed"] is True
    assert result["coverage"] == {
        "visible_items": 1,
        "indexed_items": 1,
        "empty_ocr_items": 0,
        "unindexed_items": 0,
    }
    (hit,) = result["hits"]
    assert hit["item_id"] == token.item_id and hit["rank"] == 1
    assert hit["declared_text_provenance"] == {"ocr": "synthetic"}
    assert result["metadata_only"] and result["regions"] == "not_resolved"
    assert "snippet" not in hit and "bbox" not in hit and "pointer" not in hit
    assert Deleter(store).delete(C, token.item_id).status == "deleted"
    assert main(["query", *args, "cafe", "--mode", "keyword"]) == 0
    assert json.loads(capsys.readouterr().out)["hits"] == []
    assert keyword_search(store, D, "cafe")[0].token.item_id == other.item_id


def test_missing_projection_blank_success_and_no_match_are_distinct(store):
    token = item(store, 1)
    missing = query_keywords(store, C, "anything")
    assert missing["status"] == "unavailable" and missing["executed"] is False
    assert missing["reason"] == "keyword_index_not_ready"
    with pytest.raises(StoreError, match="invalid_payload"):
        projection(store, token, "")
    assert query_keywords(store, C, "anything")["status"] == "unavailable"
    # A genuine retained empty artifact is complete without an empty FTS row.
    Deleter(store).delete(C, token.item_id)
    token = item(store, 2, artifact=empty_ocr(2))
    blank = query_keywords(store, C, "anything")
    assert blank["status"] == "ok" and blank["executed"] is True and blank["hits"] == []
    assert blank["coverage"]["empty_ocr_items"] == 1
    token = item(store, 3)
    projection(store, token, "present", "e" * 32)
    assert query_keywords(store, C, "absent")["hits"] == []
    assert query_keywords(store, C, "present")["hits"][0]["declared_text_provenance"] == {}


@pytest.mark.parametrize(
    "updates",
    [
        {"document_id": "foreign"},
        {"raw_source_revision": "foreign/1"},
        {"page_id": "foreign-page"},
        {"page_index": 1},
        {"page_sha256": "5" * 64},
        {"width_px": 2},
        {"height_px": 2},
    ],
)
def test_empty_artifact_from_another_source_cannot_hide_missing_projection(store, updates):
    item(store, 1, artifact=empty_ocr(**updates))
    result = query_keywords(store, C, "anything")
    assert result["status"] == "unavailable" and result["executed"] is False
    assert result["coverage"]["empty_ocr_items"] == 0
    assert result["coverage"]["unindexed_items"] == 1


@pytest.mark.parametrize("retained", [None, b"not-json", b"{}"])
def test_missing_or_corrupted_empty_artifact_is_unavailable(store, retained):
    token = item(store, 1, artifact=empty_ocr())
    value = store.item(token).model_dump(mode="json")
    with store.transaction() as conn:
        if retained is None:
            conn.execute("DELETE FROM content WHERE item_id=?", (token.item_id,))
        else:
            conn.execute("UPDATE content SET payload=? WHERE item_id=?", (retained, token.item_id))
            # Bind the corrupted bytes honestly so validation must reject their
            # content rather than merely detecting an old byte digest.
            digest = hashlib.sha256(retained).hexdigest()
            value["evidence_artifact_sha256"] = digest
            value["stages"][1]["result_sha256"] = digest
            conn.execute(
                "UPDATE items SET metadata=? WHERE item_id=?",
                (json.dumps(value), token.item_id),
            )
    assert query_keywords(store, C, "anything")["status"] == "unavailable"


@pytest.mark.parametrize("change", ["processing_revision", "result_sha256", "partial"])
def test_empty_ocr_requires_complete_matching_stage_metadata(store, change):
    token = item(store, 1, artifact=empty_ocr())
    value = store.item(token).model_dump(mode="json")
    if change == "partial":
        value["stages"][1].update(status="partial", reason="truncated")
    else:
        value["stages"][1][change] = "different/1" if change == "processing_revision" else "6" * 64
    with store.transaction() as conn:
        conn.execute(
            "UPDATE items SET metadata=? WHERE item_id=?", (json.dumps(value), token.item_id)
        )
    assert query_keywords(store, C, "anything")["status"] == "unavailable"


def test_nonempty_ocr_without_text_projection_is_not_a_blank_success(store):
    word = Word(
        stable_id="word-control",
        text="alpha",
        bbox_px=None,
        ocr_confidence=None,
        geometry_provenance="none",
        source_engine="synthetic-empty-control",
        source_engine_version="1",
    )
    item(store, 1, artifact=empty_ocr(words=(word,)))
    result = query_keywords(store, C, "alpha")
    assert result["status"] == "unavailable" and result["hits"] == []
    assert result["coverage"]["empty_ocr_items"] == 0


def test_empty_ocr_mixed_coverage_and_delete_cannot_return_deleted_id(store):
    empty = item(store, 1, artifact=empty_ocr())
    text = item(store, 2)
    projection(store, text, "alpha")
    item(store, 3)
    result = query_keywords(store, C, "alpha")
    assert result["status"] == "partial" and result["executed"] is True
    assert result["coverage"] == {
        "visible_items": 3,
        "indexed_items": 1,
        "empty_ocr_items": 1,
        "unindexed_items": 1,
    }
    assert [hit["item_id"] for hit in result["hits"]] == [text.item_id]
    assert Deleter(store).delete(C, empty.item_id).status == "deleted"
    assert Deleter(store).delete(C, text.item_id).status == "deleted"
    after = query_keywords(store, C, "alpha")
    assert after["status"] == "unavailable" and after["hits"] == []
    assert after["coverage"]["visible_items"] == 1


def test_coverage_same_snapshot_deduplicates_rows_and_excludes_staging(store):
    first = item(store, 1)
    item(store, 2)
    projection(store, first, "alpha")
    projection(store, first, "alpha alpha", "e" * 32)
    pending = item(store, 3)
    with store.transaction() as conn:
        conn.execute("INSERT INTO import_batches VALUES(?,?,?,?)", ("d" * 32, C, 1, "staging"))
        conn.execute("INSERT INTO import_members VALUES(?,?,?)", ("d" * 32, C, pending.item_id))
    projection(store, pending, "alpha")
    snapshot = keyword_snapshot(store, C, "alpha")
    assert snapshot.visible_items == 2 and snapshot.indexed_items == 1
    result = query_keywords(store, C, "alpha")
    assert result["status"] == "partial" and result["executed"] is True
    assert result["coverage"]["unindexed_items"] == 1 and len(result["hits"]) == 1


def test_delete_between_search_and_materialization_refuses_all_metadata(store, monkeypatch):
    import screenshot_memory.keyword_query as consumer

    token = item(store, 1)
    projection(store, token, "alpha")
    real = consumer.keyword_snapshot

    def race(*args):
        snapshot = real(*args)
        Deleter(store).delete(C, token.item_id)
        return snapshot

    monkeypatch.setattr(consumer, "keyword_snapshot", race)
    with pytest.raises(StoreError, match="generation_mismatch"):
        query_keywords(store, C, "alpha")


def test_delete_after_item_check_invalidates_snapshot_even_for_last_hit(store, monkeypatch):
    token = item(store, 1)
    projection(store, token, "alpha")
    real = store.item

    def race(value):
        result = real(value)
        Deleter(store).delete(C, token.item_id)
        return result

    monkeypatch.setattr(store, "item", race)
    with pytest.raises(StoreError, match="generation_mismatch"):
        query_keywords(store, C, "alpha")


@pytest.mark.parametrize("text", ["", " ", "x" * 1001, None, 1, True])
def test_invalid_queries_refuse_before_any_results(store, text):
    with pytest.raises(StoreError, match="invalid_query"):
        query_keywords(store, C, text)


def test_default_cli_remains_explicitly_unavailable_and_bad_mode_refuses(store, capsys):
    token = item(store, 1)
    projection(store, token, "alpha")
    args = ["--root", str(store.root), "--collection", C]
    assert main(["query", *args, "alpha"]) == 2
    assert json.loads(capsys.readouterr().out)["executed"] is False
    from screenshot_memory.keyword_query import query

    with pytest.raises(StoreError, match="invalid_query_mode"):
        query(store, C, "alpha", mode="implicit-fallback")
