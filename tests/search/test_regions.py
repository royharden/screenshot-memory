"""Synthetic Docio geometry/decoder controls, real SQLite/files/generations.

No OCR/model or native decoder quality is established by these hand-built inputs.
"""

import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from screenshot_memory.contracts import Collection, Item, StageStatus
from screenshot_memory.regions import (
    ARTIFACT_ROW,
    DECODE_ROW,
    DOCUMENT_ROW,
    DOMAIN,
    DecodedGrid,
    install_screenshot_resolver,
    literal_line_pointer,
    processing_revision,
)
from screenshot_memory.shared.cited.models import ArtifactRef, ResolutionContext, ScreenshotPointer
from screenshot_memory.shared.cited.models import BoxPx as CitedBox
from screenshot_memory.shared.cited.registry import DuplicateResolverError, Registry
from screenshot_memory.shared.docio.identity import (
    artifact_bytes,
    canonical_bytes,
    grid_digest,
    raw_revision,
)
from screenshot_memory.shared.docio.models import (
    AffineTransform,
    BoxPx,
    Document,
    Line,
    Page,
    PageInput,
    PageSourceResult,
    ProcessingArtifact,
    Provenance,
    RecognizedGrid,
    TransformPair,
    Word,
)
from screenshot_memory.shared.vindex import Deleter, GenerationToken, Store

C, ITEM, OBJECT = "a" * 32, "b" * 32, "c" * 32
RAW = b"anonymous synthetic encoded source; not PNG, native OCR or a model"
RGBA = b"\x10\x20\x30\xff" * 48
W, H = 8, 6
NAMES = ("decode", "ocr", "caption", "text_embeddings", "image_embeddings")


def sha(value):
    return hashlib.sha256(value).hexdigest()


class SyntheticDecoder:
    grid_policy_id = "synthetic-source-grid/1"
    config_sha256 = "d" * 64
    processing_revision = "synthetic-decode/1"

    def __init__(self) -> None:
        self.calls = 0
        self.hook: Callable[[], None] = lambda: None
        self.result = DecodedGrid(W, H, RGBA)

    def decode(self, raw: bytes) -> DecodedGrid:
        assert raw == RAW
        self.calls += 1
        self.hook()
        return self.result


class IssuedAccess:
    access_ref = ArtifactRef(
        artifact_id="caller-session", artifact_sha256="e" * 64, profile_id="test-access/1"
    )
    generation_ref = ArtifactRef(
        artifact_id="issued-before-query",
        artifact_sha256="f" * 64,
        profile_id="test-issued-token/1",
    )

    def __init__(self, token: GenerationToken) -> None:
        self.token = token
        self.allow = True
        self.calls = 0

    def policy_refs(self) -> tuple[ArtifactRef, ArtifactRef]:
        return self.access_ref, self.generation_ref

    def issued_token(
        self, pointer: ScreenshotPointer, context: ResolutionContext
    ) -> GenerationToken | None:
        self.calls += 1
        return self.token if self.allow else None


@dataclass
class Case:
    store: Store
    decoder: SyntheticDecoder
    access: IssuedAccess
    context: ResolutionContext
    registry: Registry
    pointer: ScreenshotPointer | None
    document: Document
    artifact: bytes


def setup(
    tmp_path, *, cid=C, item_id=ITEM, geometry="measured_ocr", rotated=False, confidence=None
):
    decoder = SyntheticDecoder()
    store = Store(tmp_path / "private", busy_ms=250)
    store.create_collection(Collection(collection_id=cid, generation=0))
    raw_sha = sha(RAW)
    revision = raw_revision(item_id, raw_sha)
    item = Item(
        collection_id=cid,
        item_id=item_id,
        source_object_id=OBJECT,
        original_content_sha256=raw_sha,
        raw_source_revision=revision,
        revision=0,
        generation=0,
        collection_generation=0,
        encoded_bytes=len(RAW),
        width_px=W,
        height_px=H,
        state="pending",
        stages=tuple(StageStatus(stage=n, status="not_run", item_generation=0) for n in NAMES),
    )
    token = store.admit(item)
    store.put_file(token, "original", RAW)
    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    pair = TransformPair(
        source_to_engine=AffineTransform(
            direction="source_to_engine", algorithm="identity/1", matrix=identity
        ),
        engine_to_source=AffineTransform(
            direction="engine_to_source", algorithm="identity/1", matrix=identity
        ),
    )
    grid = grid_digest(W, H, RGBA)
    page_id = item_id + ":page:0"
    source = PageSourceResult(
        status="ok",
        pages=(
            PageInput(
                execution_ref="synthetic-grid-control",
                document_id=item_id,
                original_content_sha256=raw_sha,
                raw_source_revision=revision,
                page_id=page_id,
                page_index=0,
                page_sha256=grid,
                width_px=W,
                height_px=H,
                grid_policy_id=decoder.grid_policy_id,
                source_kind="screenshot",
                transforms=pair,
            ),
        ),
        issues=(),
        capabilities=("synthetic-decoder-control",),
        provenance=Provenance(
            producer="synthetic-grid",
            version="1",
            config_sha256=decoder.config_sha256,
            source_grid_profile=decoder.grid_policy_id,
        ),
    )
    source_raw = canonical_bytes(source.model_dump(mode="json"))
    decoded_stage = StageStatus(
        stage="decode",
        status="ready",
        item_generation=0,
        processing_revision=decoder.processing_revision,
        result_sha256=sha(source_raw),
        provenance="synthetic",
    )
    item = item.model_copy(
        update={
            "revision": 1,
            "state": "partial",
            "source_grid_sha256": grid,
            "stages": (decoded_stage, *item.stages[1:]),
        }
    )
    store.publish_stage(token, 0, "decode", item, (("content", DECODE_ROW, source_raw),))
    box_a = BoxPx(x0=0.0, y0=1.0, x1=2.0, y1=2.0)
    box_b = BoxPx(x0=3.0, y0=1.0, x1=6.0, y1=2.0)
    if geometry == "none":
        box_a = box_b = None
    engine = {
        "ocr_confidence": confidence,
        "geometry_provenance": geometry,
        "source_engine": "synthetic-ocr",
        "source_engine_version": "1",
    }
    words = (
        Word(stable_id="word-a", text="Café", bbox_px=box_a, **engine),
        Word(stable_id="word-b", text="café", bbox_px=box_b, **engine),
    )
    lines = (
        Line(
            stable_id="line-a",
            text=words[0].text,
            bbox_px=box_a,
            ordered_child_ids=("word-a",),
            **engine,
        ),
        Line(
            stable_id="line-b",
            text=words[1].text,
            bbox_px=box_b,
            ordered_child_ids=("word-b",),
            **engine,
        ),
    )
    if rotated:
        pair = TransformPair(
            source_to_engine=AffineTransform(
                direction="source_to_engine",
                algorithm="rotate90/1",
                matrix=((0.0, -1.0, 6.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            ),
            engine_to_source=AffineTransform(
                direction="engine_to_source",
                algorithm="rotate90-inverse/1",
                matrix=((0.0, 1.0, 0.0), (-1.0, 0.0, 6.0), (0.0, 0.0, 1.0)),
            ),
        )
    artifact = ProcessingArtifact(
        document_id=item_id,
        raw_source_revision=revision,
        page_id=page_id,
        page_index=0,
        width_px=W,
        height_px=H,
        page_sha256=grid,
        grid_policy_id=decoder.grid_policy_id,
        words=words,
        lines=lines,
        blocks=(),
        artifact_id="artifact-control",
        engine="synthetic-ocr",
        engine_version="1",
        config_digest="1" * 64,
        source_to_engine=pair.source_to_engine,
        engine_to_source=pair.engine_to_source,
    )
    page = Page(
        **{key: getattr(artifact, key) for key in RecognizedGrid.model_fields},
        source_kind="screenshot",
        processing_ref=artifact.artifact_id,
    )
    document = Document(
        document_id=item_id,
        original_content_sha256=raw_sha,
        raw_source_revision=revision,
        source_kind="screenshot",
        pages=(page,),
        provenance=Provenance(
            producer=artifact.engine,
            version=artifact.engine_version,
            config_sha256=artifact.config_digest,
            source_grid_profile=decoder.grid_policy_id,
        ),
    )
    retained = artifact_bytes(artifact)
    ocr = StageStatus(
        stage="ocr",
        status="ready",
        item_generation=0,
        processing_revision=processing_revision(artifact),
        result_sha256=sha(retained),
        provenance="synthetic",
    )
    item = item.model_copy(
        update={
            "revision": 2,
            "evidence_artifact_sha256": sha(retained),
            "stages": (decoded_stage, ocr, *item.stages[2:]),
        }
    )
    store.publish_stage(
        token,
        1,
        "ocr",
        item,
        (
            ("content", DOCUMENT_ROW, canonical_bytes(document.model_dump(mode="json"))),
            ("content", ARTIFACT_ROW, retained),
        ),
    )
    access = IssuedAccess(token)
    context = ResolutionContext(
        namespace_id=cid,
        access_policy_ref=access.access_ref,
        generation_policy_ref=access.generation_ref,
        required_scope="text_and_spatial",
    )
    registry = Registry()
    install_screenshot_resolver(registry, store, access, decoder)
    pointer = (
        literal_line_pointer(document, retained, "Café") if geometry != "model_claimed" else None
    )
    return Case(store, decoder, access, context, registry, pointer, document, retained)


def test_actual_stores_and_synthetic_decoder_join_preserves_unicode_and_null_confidence(tmp_path):
    case = setup(tmp_path)
    result = case.registry.resolve(case.pointer, case.context)
    assert result.status == "resolved"
    assert result.excerpt == "Café" and result.excerpt_sha256 == sha("Café".encode())
    assert result.provenance.geometry_provenance == "measured_ocr"
    assert result.provenance.ocr_confidence is None
    assert result.checked_source_sha256 == sha(RAW)
    assert result.checked_artifact_sha256 == sha(case.artifact)
    assert case.decoder.calls == 1 and case.access.calls == 2
    assert case.registry.installed_domains == frozenset({DOMAIN})
    with pytest.raises(DuplicateResolverError):
        install_screenshot_resolver(case.registry, case.store, case.access, case.decoder)


@pytest.mark.parametrize(
    "kind", ["denied", "namespace", "access_ref", "generation_ref", "foreign_item"]
)
def test_context_or_policy_cannot_grant_access_or_read_source(tmp_path, kind):
    case = setup(tmp_path)
    if kind == "denied":
        case.access.allow = False
    elif kind == "namespace":
        case.context = case.context.model_copy(update={"namespace_id": "2" * 32})
    elif kind in {"access_ref", "generation_ref"}:
        field = "access_policy_ref" if kind == "access_ref" else "generation_policy_ref"
        case.context = case.context.model_copy(
            update={
                field: ArtifactRef(
                    artifact_id="wrong", artifact_sha256="3" * 64, profile_id="wrong/1"
                )
            }
        )
    else:
        case.access.token = case.access.token.model_copy(update={"item_id": "4" * 32})
    result = case.registry.resolve(case.pointer, case.context)
    assert result.status != "resolved" and result.excerpt is None
    assert case.decoder.calls == 0


def test_stale_issued_token_is_not_refreshed_after_collection_generation_change(
    tmp_path, monkeypatch
):
    case = setup(tmp_path)
    assert Deleter(case.store).delete(C, ITEM).status == "deleted"
    monkeypatch.setattr(
        Store,
        "token",
        lambda *_: (_ for _ in ()).throw(AssertionError("never refresh issued token")),
    )
    result = case.registry.resolve(case.pointer, case.context)
    assert result.status == "stale" and result.excerpt is None


@pytest.mark.parametrize(
    "kind",
    [
        "pixels",
        "dimensions",
        "policy",
        "config",
        "decode_revision",
        "owned_original",
        "artifact",
        "document",
        "stage_revision",
        "transform",
    ],
)
def test_actual_source_and_retained_identity_mismatches_fail_closed(tmp_path, kind):
    case = setup(tmp_path)
    if kind == "pixels":
        case.decoder.result = DecodedGrid(W, H, b"\0" * len(RGBA))
    elif kind == "dimensions":
        case.decoder.result = DecodedGrid(W + 1, H, RGBA)
    elif kind == "policy":
        case.decoder.grid_policy_id = "different/1"
    elif kind == "config":
        case.decoder.config_sha256 = "2" * 64
    elif kind == "decode_revision":
        case.decoder.processing_revision = "wrong/1"
    elif kind == "owned_original":
        case.store.object_path(C, ITEM, OBJECT).write_bytes(b"replaced source")
    elif kind == "transform":
        ref = case.pointer.locator.transform_ref.model_copy(update={"artifact_sha256": "3" * 64})
        case.pointer = case.pointer.model_copy(
            update={"locator": case.pointer.locator.model_copy(update={"transform_ref": ref})}
        )
    else:
        with case.store.transaction() as conn:
            if kind == "stage_revision":
                row = conn.execute("SELECT metadata FROM items").fetchone()[0]
                data = json.loads(row)
                data["stages"][1]["processing_revision"] = "wrong/1"
                conn.execute("UPDATE items SET metadata=?", (json.dumps(data),))
            else:
                key = ARTIFACT_ROW if kind == "artifact" else DOCUMENT_ROW
                conn.execute("UPDATE content SET payload=? WHERE row_id=?", (b"{}", key))
    result = case.registry.resolve(case.pointer, case.context)
    assert result.status != "resolved" and result.excerpt is None and result.scope is None


def test_canonical_validator_owns_reading_order_unicode_enclosure_and_missing_ids(tmp_path):
    case = setup(tmp_path)
    for update in (
        {"line_ids": ("line-b", "line-a")},
        {"line_ids": ("absent",)},
        {"excerpt_sha256": sha("Café".encode())},
        {"word_ids": ("word-b",)},
        {"bbox_px": CitedBox(x0=3.0, y0=1.0, x1=6.0, y1=2.0)},
    ):
        pointer = case.pointer.model_copy(
            update={"locator": case.pointer.locator.model_copy(update=update)}
        )
        assert case.registry.resolve(pointer, case.context).status != "resolved"


def test_same_bytes_in_another_collection_do_not_authorize_a_foreign_pointer(tmp_path):
    first = setup(tmp_path / "first")
    second = setup(tmp_path / "second", cid="2" * 32, item_id="3" * 32)
    assert first.pointer.source_sha256 == second.pointer.source_sha256
    result = second.registry.resolve(first.pointer, second.context)
    assert result.status != "resolved" and result.excerpt is None
    assert second.decoder.calls == 0


def test_unknown_provenance_profile_is_refused_instead_of_silently_ignored(tmp_path):
    case = setup(tmp_path)
    pointer = case.pointer.model_copy(update={"provenance_ref": case.access.access_ref})
    result = case.registry.resolve(pointer, case.context)
    assert result.status == "unsupported" and result.excerpt is None
    assert case.decoder.calls == 0


def test_canonical_multiple_line_excerpt_keeps_order_and_does_not_average_confidence(tmp_path):
    case = setup(tmp_path, confidence=0.8)
    text = "Café\ncafé"
    assert case.registry.resolve(case.pointer, case.context).provenance.ocr_confidence == 0.8
    pointer = case.pointer.model_copy(
        update={
            "locator": case.pointer.locator.model_copy(
                update={
                    "line_ids": ("line-a", "line-b"),
                    "bbox_px": CitedBox(x0=0.0, y0=1.0, x1=6.0, y1=2.0),
                    "excerpt_sha256": sha(text.encode()),
                }
            )
        }
    )
    result = case.registry.resolve(pointer, case.context)
    assert result.status == "resolved" and result.excerpt == text
    assert result.provenance.ocr_confidence is None


def test_rotated_transform_does_not_retransform_source_geometry_and_spatial_only_has_no_excerpt(
    tmp_path,
):
    case = setup(tmp_path, rotated=True)
    box = case.pointer.locator.bbox_px
    assert (box.x0, box.y0, box.x1, box.y1) == (0.0, 1.0, 2.0, 2.0)
    context = case.context.model_copy(update={"required_scope": "spatial"})
    result = case.registry.resolve(case.pointer, context)
    assert result.status == "resolved" and result.scope == "spatial" and result.excerpt is None


def test_image_only_and_model_claimed_hits_do_not_invent_regions(tmp_path):
    case = setup(tmp_path)
    assert literal_line_pointer(case.document, case.artifact, "visual icon without text") is None
    claimed = setup(tmp_path / "claimed", geometry="model_claimed")
    assert literal_line_pointer(claimed.document, claimed.artifact, "Café") is None
    forged = case.pointer.model_copy(update={"evidence_artifact_sha256": sha(claimed.artifact)})
    result = claimed.registry.resolve(forged, claimed.context)
    assert result.status != "resolved" and result.excerpt is None
    missing = setup(tmp_path / "missing", geometry="none")
    assert literal_line_pointer(missing.document, missing.artifact, "Café") is None
    forged = case.pointer.model_copy(update={"evidence_artifact_sha256": sha(missing.artifact)})
    assert missing.registry.resolve(forged, missing.context).status != "resolved"


def test_policy_revocation_during_decode_does_not_release_excerpt(tmp_path):
    case = setup(tmp_path)
    case.decoder.hook = lambda: setattr(case.access, "allow", False)
    result = case.registry.resolve(case.pointer, case.context)
    assert (
        result.status == "unsupported"
        and result.reason == "access_changed"
        and result.excerpt is None
    )


def test_concurrent_delete_waits_for_read_transaction_then_subsequent_lookup_refuses(tmp_path):
    case = setup(tmp_path)
    decoding, release, deleted = threading.Event(), threading.Event(), threading.Event()
    results = {}

    def pause():
        decoding.set()
        assert release.wait(3)

    case.decoder.hook = pause

    def resolve():
        results["resolve"] = case.registry.resolve(case.pointer, case.context)

    def delete():
        results["delete"] = Deleter(case.store).delete(C, ITEM)
        deleted.set()

    reader = threading.Thread(target=resolve)
    reader.start()
    assert decoding.wait(3)
    writer = threading.Thread(target=delete)
    writer.start()
    time.sleep(0.02)
    assert not deleted.is_set()
    release.set()
    reader.join(3)
    writer.join(3)
    assert not reader.is_alive() and not writer.is_alive()
    assert results["resolve"].status == "resolved" and results["delete"].status == "deleted"
    assert case.registry.resolve(case.pointer, case.context).status != "resolved"
