"""Explicit metadata-only keyword query over existing literal index projections."""

from screenshot_memory.errors import WorkflowError
from screenshot_memory.ocr_records import ARTIFACT_ROW, processing_revision
from screenshot_memory.shared.docio.identity import validate_artifact_bytes
from screenshot_memory.shared.vindex import GenerationToken, Store, StoreError
from screenshot_memory.shared.vindex.search import keyword_snapshot


def query(store: Store, collection_id: str, text: str, *, mode: str = "construction") -> dict:
    if type(text) is not str or not 1 <= len(text) <= 1000 or not text.strip():
        raise WorkflowError("invalid_query")
    if mode == "keyword":
        return query_keywords(store, collection_id, text)
    if mode != "construction":
        raise WorkflowError("invalid_query_mode")
    store.collection(collection_id)
    return {
        "status": "unavailable",
        "reason": "ocr_caption_and_vectors_not_implemented",
        "executed": False,
        "hits": [],
        "mode": "local_construction",
    }


def query_keywords(store: Store, collection_id: str, text: str) -> dict:
    if type(text) is not str or not 1 <= len(text) <= 1000 or not text.strip():
        raise StoreError("invalid_query")
    snapshot = keyword_snapshot(store, collection_id, text)
    empty_ocr = sum(_empty_ocr(store, token) for token in snapshot.unindexed_tokens)
    hits = []
    for rank, hit in enumerate(snapshot.hits, 1):
        # Never obtain a replacement token that could refresh a stale result.
        item = store.item(hit.token)
        hits.append(
            {
                "item_id": item.item_id,
                "generation_token": hit.token.model_dump(mode="json"),
                "rank": rank,
                "sqlite_bm25": hit.sqlite_bm25,
                "declared_text_provenance": {
                    stage.stage: stage.provenance
                    for stage in item.stages
                    if stage.stage in {"ocr", "caption"} and stage.status in {"ready", "partial"}
                },
            }
        )
    if store.collection(collection_id).generation != snapshot.collection_generation:
        raise StoreError("generation_mismatch")
    missing = snapshot.visible_items - snapshot.indexed_items - empty_ocr
    unavailable = snapshot.visible_items > 0 and snapshot.indexed_items + empty_ocr == 0
    result = {
        "status": "unavailable" if unavailable else "partial" if missing else "ok",
        "executed": not unavailable,
        "mode": "keyword",
        "ranking": "sqlite_fts5_bm25_ordering_not_probability",
        "coverage": {
            "visible_items": snapshot.visible_items,
            "indexed_items": snapshot.indexed_items,
            "empty_ocr_items": empty_ocr,
            "unindexed_items": missing,
        },
        "hits": hits,
        "metadata_only": True,
        "regions": "not_resolved",
        "unavailable_legs": ["text_embeddings", "image_embeddings", "reranking"],
    }
    if unavailable:
        result["reason"] = "keyword_index_not_ready"
    return result


def _empty_ocr(store: Store, token: GenerationToken) -> bool:
    """Recognize a retained empty output; never treat missing FTS as blank OCR."""
    item = store.item(token)
    stage = next(stage for stage in item.stages if stage.stage == "ocr")
    if stage.status != "ready" or stage.result_sha256 != item.evidence_artifact_sha256:
        return False
    try:
        raw = store.get("content", token, ARTIFACT_ROW)
    except StoreError as error:
        if str(error) == "invalid_payload":
            return False
        raise
    if raw is None:
        return False
    try:
        artifact = validate_artifact_bytes(raw, stage.result_sha256)
    except (ValueError, TypeError):
        return False
    return (
        not (artifact.words or artifact.lines or artifact.blocks)
        and artifact.document_id == item.item_id
        and artifact.raw_source_revision == item.raw_source_revision
        and artifact.page_id == item.item_id + ":page:0"
        and artifact.page_index == 0
        and artifact.page_sha256 == item.source_grid_sha256
        and (artifact.width_px, artifact.height_px) == (item.width_px, item.height_px)
        and processing_revision(artifact) == stage.processing_revision
    )
