"""Explicit keyless local image journey. No OCR, embeddings or provider fallback."""

import hashlib
import os
import sqlite3
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from screenshot_memory.contracts import (
    MAX_COLLECTION_BYTES,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    Collection,
    Item,
    StageStatus,
)
from screenshot_memory.image_source import (
    GRID_POLICY,
    POLICY_SHA,
    PROCESSING_REVISION,
    ImageDecodeError,
    decode_image_bytes,
    pillow_version,
)
from screenshot_memory.shared.docio.identity import canonical_bytes, grid_digest, raw_revision
from screenshot_memory.shared.docio.models import (
    AffineTransform,
    PageInput,
    PageSourceResult,
    Provenance,
    TransformPair,
)
from screenshot_memory.shared.vindex import Deleter, Store, StoreError
from screenshot_memory.shared.vindex.storage import is_link

STAGES = ("decode", "ocr", "caption", "text_embeddings", "image_embeddings")


class WorkflowError(StoreError):
    def __init__(self, reason: str, cleanup=()):
        super().__init__(reason)
        self.cleanup = cleanup


@dataclass(frozen=True)
class Decoded:
    raw: bytes
    width: int
    height: int
    grid_sha256: str


def decode_selected(path: Path) -> Decoded:
    """Read one explicit regular file; bound before decoding, retain no RGBA batch."""
    path = Path(path)
    if ".." in path.parts:
        raise WorkflowError("invalid_image_path")
    path = path.absolute()
    try:
        if any(is_link(part) for part in (path, *path.parents)):
            raise WorkflowError("invalid_image_path")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        with os.fdopen(os.open(path, flags), "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise WorkflowError("invalid_image_path")
            if not 0 < before.st_size <= MAX_IMAGE_BYTES:
                raise WorkflowError("image_byte_limit")
            raw = source.read(MAX_IMAGE_BYTES + 1)
            after = os.fstat(source.fileno())
        current = path.stat(follow_symlinks=False)

        def identity(info):
            return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

        if identity(before) != identity(after) or identity(after) != identity(current):
            raise WorkflowError("image_changed_during_read")
        if len(raw) != before.st_size:
            raise WorkflowError("image_changed_during_read")
    except OSError:
        raise WorkflowError("invalid_image_path") from None
    try:
        grid = decode_image_bytes(raw, pixel_limit=MAX_IMAGE_PIXELS)
    except ImageDecodeError as error:
        raise WorkflowError(str(error)) from None
    return Decoded(raw, grid.width, grid.height, grid_digest(grid.width, grid.height, grid.rgba8))


def _source_record(item: Item, decoded: Decoded) -> bytes:
    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    result = PageSourceResult(
        status="ok",
        pages=(
            PageInput(
                execution_ref=uuid.uuid4().hex,
                document_id=item.item_id,
                original_content_sha256=item.original_content_sha256,
                raw_source_revision=item.raw_source_revision,
                page_id=item.item_id + ":page:0",
                page_index=0,
                page_sha256=decoded.grid_sha256,
                width_px=decoded.width,
                height_px=decoded.height,
                grid_policy_id=GRID_POLICY,
                source_kind="screenshot",
                transforms=TransformPair(
                    source_to_engine=AffineTransform(
                        direction="source_to_engine", algorithm="identity/1", matrix=identity
                    ),
                    engine_to_source=AffineTransform(
                        direction="engine_to_source", algorithm="identity/1", matrix=identity
                    ),
                ),
            ),
        ),
        issues=(),
        capabilities=("decode_png_jpeg_rgba8",),
        provenance=Provenance(
            producer="Pillow",
            version=pillow_version,
            config_sha256=POLICY_SHA,
            source_grid_profile=GRID_POLICY,
        ),
    )
    return canonical_bytes(result.model_dump(mode="json"))


def create_collection(store: Store) -> str:
    collection_id = uuid.uuid4().hex
    store.create_collection(Collection(collection_id=collection_id, generation=0))
    return collection_id


def import_images(store: Store, collection_id: str, paths: tuple[Path, ...]) -> tuple[Item, ...]:
    if type(paths) is not tuple or not 1 <= len(paths) <= 30:
        raise WorkflowError("invalid_batch")
    # Metadata cap/byte checks are repeated under the store's writer lock.
    collection = store.collection(collection_id)
    if collection.item_count + len(paths) > collection.cap:
        raise WorkflowError("collection_full")
    decoded = []
    encoded_bytes = collection.encoded_bytes
    for path in paths:
        value = decode_selected(path)
        encoded_bytes += len(value.raw)
        if encoded_bytes > MAX_COLLECTION_BYTES:
            raise WorkflowError("collection_bytes_full")
        decoded.append(value)
    items = []
    for value in decoded:
        item_id = uuid.uuid4().hex
        raw_sha = hashlib.sha256(value.raw).hexdigest()
        items.append(
            Item(
                item_id=item_id,
                collection_id=collection_id,
                source_object_id=uuid.uuid4().hex,
                original_content_sha256=raw_sha,
                raw_source_revision=raw_revision(item_id, raw_sha),
                revision=0,
                generation=0,
                collection_generation=collection.generation,
                encoded_bytes=len(value.raw),
                width_px=value.width,
                height_px=value.height,
                state="pending",
                stages=tuple(
                    StageStatus(stage=s, status="not_run", item_generation=0) for s in STAGES
                ),
            )
        )
    batch_id, tokens = store.begin_import(tuple(items))
    published = []
    try:
        for token, item, value in zip(tokens, items, decoded, strict=True):
            store.put_file(token, "original", value.raw)
            record = _source_record(item, value)
            stage = StageStatus(
                stage="decode",
                status="ready",
                item_generation=0,
                processing_revision=PROCESSING_REVISION,
                result_sha256=hashlib.sha256(record).hexdigest(),
                provenance="observed",
            )
            updated = item.model_copy(
                update={
                    "revision": 1,
                    "state": "partial",
                    "source_grid_sha256": value.grid_sha256,
                    "stages": (stage, *item.stages[1:]),
                }
            )
            published.append(
                store.publish_stage(
                    token,
                    0,
                    "decode",
                    updated,
                    (("content", hashlib.sha256(b"decode-source/1").hexdigest()[:32], record),),
                )
            )
        store.complete_import(batch_id, tokens)
    except BaseException as error:
        cleanup = _rollback_imports(store, collection_id, batch_id)
        if not isinstance(error, Exception):
            raise
        reason = (
            "import_failed"
            if all(r and r.status == "deleted" for r in cleanup)
            else "cleanup_pending"
        )
        raise WorkflowError(reason, tuple(cleanup)) from None
    return tuple(published)


def _rollback_imports(store: Store, collection_id: str, batch_id: str | None = None):
    """Abort staging durably before cleanup, including after an abrupt process exit."""
    store.collection(collection_id)
    with store.transaction() as conn:
        predicate = "collection_id=?" + (" AND batch_id=?" if batch_id is not None else "")
        params = (collection_id,) if batch_id is None else (collection_id, batch_id)
        conn.execute(f"UPDATE import_batches SET status='aborting' WHERE {predicate}", params)
        ids = {
            r[0]
            for r in conn.execute(f"SELECT item_id FROM import_members WHERE {predicate}", params)
        }
        if batch_id is None:
            ids.update(
                r[0]
                for r in conn.execute(
                    "SELECT item_id FROM delete_jobs WHERE collection_id=? AND status!='deleted'",
                    (collection_id,),
                )
            )
    cleanup = []
    for item_id in sorted(ids):
        try:
            cleanup.append(Deleter(store).delete(collection_id, item_id))
        except (OSError, StoreError, sqlite3.Error):
            # The visibility barrier survives even if deletion cannot acquire its writer lock.
            cleanup.append(None)
    with store.transaction() as conn:
        conn.execute(
            f"DELETE FROM import_batches WHERE {predicate} AND NOT EXISTS "
            "(SELECT 1 FROM import_members m WHERE m.batch_id=import_batches.batch_id)",
            params,
        )
    return tuple(cleanup)


def recover_imports(store: Store, collection_id: str):
    """Explicitly cancel incomplete imports and resume deletion in this collection only."""
    return _rollback_imports(store, collection_id)


def inspect_items(store: Store, collection_id: str, item_id: str | None = None) -> tuple[Item, ...]:
    if item_id is None:
        return store.list_items(collection_id)
    token = store.token(collection_id, item_id)
    item = store.item(token)
    store.read_file(token, item.source_object_id)
    return (item,)


def query(store: Store, collection_id: str, text: str) -> dict:
    if type(text) is not str or not 1 <= len(text) <= 1000 or not text.strip():
        raise WorkflowError("invalid_query")
    store.collection(collection_id)
    return {
        "status": "unavailable",
        "reason": "ocr_caption_and_vectors_not_implemented",
        "executed": False,
        "hits": [],
        "mode": "local_construction",
    }
