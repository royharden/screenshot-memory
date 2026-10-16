"""Real Pillow images/import/decoder; explicitly hand-built OCR and access ports."""

import hashlib
import io

import pytest
from PIL import Image

from screenshot_memory import workflow
from screenshot_memory.contracts import Item, StageStatus
from screenshot_memory.image_source import (
    GRID_POLICY,
    POLICY_SHA,
    PROCESSING_REVISION,
    ImageDecodeError,
    decode_image_bytes,
)
from screenshot_memory.regions import (
    ARTIFACT_ROW,
    DECODE_ROW,
    DOCUMENT_ROW,
    PillowSourceGridDecoder,
    install_screenshot_resolver,
    literal_line_pointer,
    processing_revision,
)
from screenshot_memory.shared.cited.models import ArtifactRef, ResolutionContext, ScreenshotPointer
from screenshot_memory.shared.cited.registry import Registry
from screenshot_memory.shared.docio.identity import artifact_bytes, canonical_bytes, grid_digest
from screenshot_memory.shared.docio.models import (
    BoxPx,
    Document,
    Line,
    Page,
    PageSourceResult,
    ProcessingArtifact,
    Provenance,
    RecognizedGrid,
    Word,
)
from screenshot_memory.shared.vindex import Deleter, GenerationToken, Store
from screenshot_memory.shared.vindex.deletion import STORES


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class IssuedControl:
    """Typed admission control, not production authentication."""

    def __init__(self, token: GenerationToken):
        self.token = token
        self.refs = tuple(
            ArtifactRef(artifact_id=name, artifact_sha256=digest * 64, profile_id="test-only/1")
            for name, digest in (("admission", "a"), ("issued-token", "b"))
        )

    def policy_refs(self) -> tuple[ArtifactRef, ArtifactRef]:
        return self.refs

    def issued_token(
        self, pointer: ScreenshotPointer, context: ResolutionContext
    ) -> GenerationToken:
        return self.token


def handbuilt_ocr(item: Item, source: PageSourceResult) -> tuple[Document, bytes]:
    """Synthetic text/geometry; this function neither recognizes nor measures pixels."""
    page = source.pages[0]
    fields = {
        key: getattr(page, key)
        for key in RecognizedGrid.model_fields
        if key not in {"words", "lines", "blocks"}
    }
    common = dict(
        text="anonymous-control",
        bbox_px=BoxPx(x0=0.0, y0=1.0, x1=3.0, y1=4.0),
        ocr_confidence=None,
        geometry_provenance="measured_ocr",
        source_engine="handbuilt-ocr-control",
        source_engine_version="1",
    )
    artifact = ProcessingArtifact(
        **fields,
        words=(Word(stable_id="word-control", **common),),
        lines=(Line(stable_id="line-control", ordered_child_ids=("word-control",), **common),),
        blocks=(),
        artifact_id="handbuilt-artifact",
        engine="handbuilt-ocr-control",
        engine_version="1",
        config_digest="c" * 64,
        source_to_engine=page.transforms.source_to_engine,
        engine_to_source=page.transforms.engine_to_source,
    )
    document = Document(
        document_id=item.item_id,
        original_content_sha256=item.original_content_sha256,
        raw_source_revision=item.raw_source_revision,
        source_kind="screenshot",
        pages=(
            Page(
                **{key: getattr(artifact, key) for key in RecognizedGrid.model_fields},
                source_kind="screenshot",
                processing_ref=artifact.artifact_id,
            ),
        ),
        provenance=Provenance(
            producer=artifact.engine,
            version=artifact.engine_version,
            config_sha256=artifact.config_digest,
            source_grid_profile=GRID_POLICY,
        ),
    )
    return document, artifact_bytes(artifact)


@pytest.mark.parametrize("format", ["PNG", "JPEG"])
def test_real_image_import_native_decode_synthetic_ocr_resolution_and_all_store_delete(
    tmp_path, format
):
    path = tmp_path / ("anonymous.png" if format == "PNG" else "anonymous.jpg")
    with Image.new("RGBA" if format == "PNG" else "RGB", (8, 6), (10, 20, 30)) as image:
        if format == "PNG":
            image.putalpha(40)
            image.save(path)
        else:
            exif = image.getexif()
            exif[274] = 6  # Decode policy preserves encoded axes, not EXIF display axes.
            image.save(path, exif=exif)
    raw = path.read_bytes()
    store = Store(tmp_path / "private")
    cid = workflow.create_collection(store)
    (item,) = workflow.import_images(store, cid, (path,))
    issued = store.token(cid, item.item_id)  # Issue once, before querying; resolver cannot refresh.
    access = IssuedControl(issued)
    context = ResolutionContext(
        namespace_id=cid,
        access_policy_ref=access.refs[0],
        generation_policy_ref=access.refs[1],
        required_scope="text_and_spatial",
    )
    decoder = PillowSourceGridDecoder()
    actual = decoder.decode(raw)
    assert (actual.width_px, actual.height_px) == (8, 6)
    assert grid_digest(8, 6, actual.rgba8) == item.source_grid_sha256
    if format == "PNG":
        assert actual.rgba8 == bytes((10, 20, 30, 40)) * 48
    source = PageSourceResult.model_validate_json(store.get("content", issued, DECODE_ROW))
    assert source.provenance.config_sha256 == POLICY_SHA == decoder.config_sha256
    assert item.stages[0].processing_revision == PROCESSING_REVISION
    assert item.stages[0].provenance == "observed"
    document, retained = handbuilt_ocr(item, source)
    pointer = literal_line_pointer(document, retained, "anonymous")
    assert pointer is not None
    registry = Registry()
    install_screenshot_resolver(registry, store, access, decoder)
    missing_ocr = registry.resolve(pointer, context)
    assert missing_ocr.status == "unsupported" and missing_ocr.excerpt is None
    artifact = ProcessingArtifact.model_validate_json(retained)
    ocr = StageStatus(
        stage="ocr",
        status="ready",
        item_generation=issued.item_generation,
        processing_revision=processing_revision(artifact),
        result_sha256=sha(retained),
        provenance="synthetic",
    )
    updated = item.model_copy(
        update={
            "revision": item.revision + 1,
            "evidence_artifact_sha256": sha(retained),
            "stages": (item.stages[0], ocr, *item.stages[2:]),
        }
    )
    store.publish_stage(
        issued,
        item.revision,
        "ocr",
        updated,
        (
            ("content", DOCUMENT_ROW, canonical_bytes(document.model_dump(mode="json"))),
            ("content", ARTIFACT_ROW, retained),
        ),
    )
    result = registry.resolve(pointer, context)
    assert result.status == "resolved" and result.excerpt == "anonymous-control"
    assert result.checked_source_sha256 == sha(raw)
    assert result.checked_artifact_sha256 == sha(retained)
    assert result.provenance.ocr_confidence is None
    assert workflow.query(store, cid, "anonymous")["executed"] is False
    receipt = Deleter(store).delete(cid, item.item_id)
    assert receipt.status == "deleted" and receipt.stores_verified == STORES
    assert receipt.files_absent == receipt.files_planned == 1
    with store.connection() as conn:
        assert all(
            conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0 for table in STORES
        )
    assert registry.resolve(pointer, context).status == "stale"
    assert path.read_bytes() == raw


def test_native_decoder_refuses_pixel_overflow_before_loading(tmp_path, monkeypatch):
    path = tmp_path / "anonymous.png"
    with Image.new("RGB", (8, 6), "blue") as image:
        image.save(path)

    def unexpected_load(*args, **kwargs):
        raise AssertionError("pixel allocation must not occur")

    monkeypatch.setattr(Image.Image, "load", unexpected_load)
    with pytest.raises(ImageDecodeError, match="image_pixel_limit"):
        decode_image_bytes(path.read_bytes(), pixel_limit=47)


@pytest.mark.parametrize("raw", [b"", b"unknown", b"\x89PNG\r\n\x1a\ncorrupt"])
def test_native_decoder_refuses_invalid_encoded_bytes(raw):
    with pytest.raises(ImageDecodeError):
        PillowSourceGridDecoder().decode(raw)


def test_native_decoder_refuses_animation_and_increased_policy_bound():
    stream = io.BytesIO()
    with Image.new("RGB", (2, 2), "red") as a, Image.new("RGB", (2, 2), "blue") as b:
        a.save(stream, format="PNG", save_all=True, append_images=[b], duration=10)
    with pytest.raises(ImageDecodeError, match="unsupported_image"):
        decode_image_bytes(stream.getvalue())
    with pytest.raises(ImageDecodeError, match="image_pixel_limit"):
        decode_image_bytes(stream.getvalue(), pixel_limit=20_000_001)
