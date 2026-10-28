"""Authenticated viewer call-site bridge to the existing source-region resolver.

No OCR is run here. Caller admission happens in CollectionAPI before this module
is called; each resolver receives one previously issued, collection-bound token.
"""

import hashlib
import io

from PIL import Image

from screenshot_memory.contracts import MAX_IMAGE_BYTES
from screenshot_memory.regions import (
    ARTIFACT_ROW,
    DOCUMENT_ROW,
    PillowSourceGridDecoder,
    ScreenshotResolver,
    transform_reference,
)
from screenshot_memory.shared.cited.models import (
    ArtifactRef,
    BoxPx,
    RegionLocator,
    ResolutionContext,
    ScreenshotPointer,
)
from screenshot_memory.shared.docio.identity import grid_digest, validate_artifact_bytes
from screenshot_memory.shared.docio.models import Document
from screenshot_memory.shared.vindex import StoreError


def _ref(name):
    return ArtifactRef(
        artifact_id=name,
        artifact_sha256=hashlib.sha256(name.encode()).hexdigest(),
        profile_id="smem-viewer-request/1",
    )


class _RequestAccess:
    def __init__(self, token):
        self.token = token
        self.refs = (_ref("api-bearer-admitted"), _ref("issued-before-region-lookup"))

    def policy_refs(self):
        return self.refs

    def issued_token(self, pointer, context):
        if (context.namespace_id, pointer.source_id) == (
            self.token.collection_id,
            self.token.item_id,
        ):
            return self.token
        return None


class _RequestDecoder(PillowSourceGridDecoder):
    def __init__(self, raw):
        self.raw_sha = hashlib.sha256(raw).digest()
        self.grid = super().decode(raw)

    def decode(self, raw):
        if hashlib.sha256(raw).digest() != self.raw_sha:
            raise ValueError("source_changed")
        return self.grid


def _source(store, collection_id, item_id, token=None):
    if token is None:
        token = store.token(collection_id, item_id)
    elif (token.collection_id, token.item_id) != (collection_id, item_id):
        raise StoreError("foreign_source_token")
    item = store.item(token)
    raw = store.read_file(token, item.source_object_id)
    return token, item, raw


def source_detail(store, collection_id, item_id, *, token=None):
    """Return only retained, canonically resolved geometry, with explicit provenance."""
    token, item, raw = _source(store, collection_id, item_id, token)
    stage = next(s for s in item.stages if s.stage == "ocr")
    result = {
        "status": "ok",
        "item": item.model_dump(mode="json"),
        "lines": [],
        "words": [],
        "overlay_status": "ocr_" + stage.status,
        "truncated": False,
    }
    if stage.status not in {"ready", "partial"} or stage.provenance != "observed":
        return result
    try:
        document_raw = store.get("content", token, DOCUMENT_ROW)
        artifact_raw = store.get("content", token, ARTIFACT_ROW)
        if document_raw is None or artifact_raw is None or item.evidence_artifact_sha256 is None:
            raise ValueError("missing_evidence")
        document = Document.model_validate_json(document_raw)
        artifact = validate_artifact_bytes(artifact_raw, item.evidence_artifact_sha256)
        access = _RequestAccess(token)
        context = ResolutionContext(
            namespace_id=collection_id,
            access_policy_ref=access.refs[0],
            generation_policy_ref=access.refs[1],
            required_scope="spatial",
        )
        resolver = ScreenshotResolver(store, access, _RequestDecoder(raw))
        for kind in ("lines", "words"):
            all_elements = tuple(
                e
                for e in getattr(artifact, kind)
                if e.bbox_px is not None and e.geometry_provenance in {"native", "measured_ocr"}
            )
            elements = all_elements[:500]
            result["truncated"] |= len(all_elements) > len(elements)
            if not elements:
                continue
            boxes = [e.bbox_px for e in elements]
            locator = RegionLocator(
                document_id=item.item_id,
                page_id=artifact.page_id,
                page_index=0,
                page_sha256=artifact.page_sha256,
                page_digest_algorithm="rgba8-source-grid-v1",
                source_grid_profile=artifact.grid_policy_id,
                width_px=artifact.width_px,
                height_px=artifact.height_px,
                bbox_px=BoxPx(
                    x0=min(b.x0 for b in boxes),
                    y0=min(b.y0 for b in boxes),
                    x1=max(b.x1 for b in boxes),
                    y1=max(b.y1 for b in boxes),
                ),
                **{
                    "line_ids" if kind == "lines" else "word_ids": tuple(
                        e.stable_id for e in elements
                    )
                },
                transform_ref=transform_reference(artifact),
            )
            pointer = ScreenshotPointer(
                kind="doc:page:bbox",
                source_type="screenshot_collection",
                locator_subtype="source_region",
                source_id=document.document_id,
                source_sha256=document.original_content_sha256,
                source_revision=document.raw_source_revision,
                evidence_artifact_sha256=item.evidence_artifact_sha256,
                locator=locator,
            )
            resolution = resolver.resolve(pointer, context)
            if resolution.status != "resolved":
                raise ValueError("source_region_unavailable")
            result[kind] = [
                {
                    "id": e.stable_id,
                    "text": e.text,
                    "box": [e.bbox_px.x0, e.bbox_px.y0, e.bbox_px.x1, e.bbox_px.y1],
                    "geometry_provenance": e.geometry_provenance,
                    "confidence": e.ocr_confidence,
                }
                for e in elements
            ]
        if store.item(token).revision != item.revision:
            raise StoreError("source_changed")
        result["overlay_status"] = (
            "verified_retained_regions"
            if result["lines"] or result["words"]
            else "no_measured_regions"
        )
        result["engine"] = {
            "name": artifact.engine,
            "version": artifact.engine_version,
            "stage_provenance": stage.provenance,
        }
        return result
    except (ValueError, TypeError, KeyError):
        # No unvalidated text or geometry is returned on any binding failure.
        result.update(lines=[], words=[], overlay_status="source_evidence_unavailable")
        return result


class _BoundedPNG(io.BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_IMAGE_BYTES:
            raise StoreError("display_encoding_limit")
        return super().write(data)


def source_png(store, collection_id, item_id, *, token=None):
    """Render the verified source pixel grid; remove EXIF display-axis ambiguity."""
    token, item, raw = _source(store, collection_id, item_id, token)
    try:
        grid = PillowSourceGridDecoder().decode(raw)
        if (
            grid.width_px,
            grid.height_px,
            grid_digest(grid.width_px, grid.height_px, grid.rgba8),
        ) != (item.width_px, item.height_px, item.source_grid_sha256):
            raise StoreError("source_grid_mismatch")
        with (
            _BoundedPNG() as output,
            Image.frombytes("RGBA", (grid.width_px, grid.height_px), grid.rgba8) as image,
        ):
            image.save(output, format="PNG")
            png = output.getvalue()
        if store.item(token).revision != item.revision:
            raise StoreError("source_changed")
        return png
    except ValueError:
        raise StoreError("source_decode_unavailable") from None
