"""Exact byte preimages and pure checks of supplied retained evidence. No effects."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import (
        BoxPx,
        Document,
        EngineBox,
        ProcessingArtifact,
        SourceEvidence,
        TransformPair,
    )


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def raw_revision(document_id: str, original_content_sha256: str) -> str:
    from pydantic import TypeAdapter

    from .models import OpaqueId, Sha256

    TypeAdapter(OpaqueId, config={"strict": True}).validate_python(document_id)
    TypeAdapter(Sha256, config={"strict": True}).validate_python(original_content_sha256)
    preimage = {
        "algorithm_version": 1,
        "document_id": document_id,
        "original_content_sha256": original_content_sha256,
    }
    return "docraw/1:" + hashlib.sha256(canonical_bytes(preimage)).hexdigest()


def grid_preimage(width_px: int, height_px: int, rgba8: bytes) -> bytes:
    if type(width_px) is not int or type(height_px) is not int or min(width_px, height_px) <= 0:
        raise ValueError("positive integer grid dimensions required")
    if type(rgba8) is not bytes or len(rgba8) != width_px * height_px * 4:
        raise ValueError("retained RGBA8 row-major bytes do not match dimensions")
    header = {
        "algorithm": "rgba8-source-grid-v1",
        "width_px": width_px,
        "height_px": height_px,
        "mode": "RGBA8",
        "row_order": "top-to-bottom",
        "channel_order": "RGBA",
    }
    return canonical_bytes(header) + b"\n" + rgba8


def grid_digest(width_px: int, height_px: int, rgba8: bytes) -> str:
    return hashlib.sha256(grid_preimage(width_px, height_px, rgba8)).hexdigest()


def artifact_bytes(artifact: ProcessingArtifact) -> bytes:
    return canonical_bytes(artifact.model_dump(mode="json"))


def validate_artifact_bytes(retained: bytes, expected_sha256: str) -> ProcessingArtifact:
    from .models import ProcessingArtifact

    if type(retained) is not bytes or hashlib.sha256(retained).hexdigest() != expected_sha256:
        raise ValueError("retained artifact hash mismatch")
    artifact = ProcessingArtifact.model_validate_json(retained)
    # Preserve the original finite JSON number representation; typed float fields
    # may interpret integer2 as2.0 without changing the retained artifact identity.
    if canonical_bytes(json.loads(retained)) != retained:
        raise ValueError("artifact must retain exact canonical wire bytes")
    return artifact


def engine_box_to_source(
    box: EngineBox, transforms: TransformPair, width_px: int, height_px: int
) -> BoxPx:
    """Map an engine-frame box once; return a source-frame box."""
    from .models import BoxPx, EngineBox

    if type(box) is not EngineBox:
        raise ValueError("only an engine-frame box may be mapped once")
    m = transforms.engine_to_source.matrix
    points = [
        (m[0][0] * x + m[0][1] * y + m[0][2], m[1][0] * x + m[1][1] * y + m[1][2])
        for x in (box.x0, box.x1)
        for y in (box.y0, box.y1)
    ]
    mapped = BoxPx(
        x0=min(p[0] for p in points),
        y0=min(p[1] for p in points),
        x1=max(p[0] for p in points),
        y1=max(p[1] for p in points),
    )
    mapped.within(width_px, height_px)
    return mapped


def validate_evidence(
    ref: SourceEvidence,
    document: Document,
    retained_artifact: bytes,
    *,
    require_measured_spatial: bool = False,
    resolved_transforms: Mapping[str, TransformPair] | None = None,
) -> str | None:
    """Check supplied evidence and return docio-text/1. Caller owns access/lifetime."""
    artifact = validate_artifact_bytes(retained_artifact, ref.evidence_artifact_sha256)
    if (ref.document_id, ref.original_content_sha256, ref.raw_source_revision) != (
        document.document_id,
        document.original_content_sha256,
        document.raw_source_revision,
    ):
        raise ValueError("raw document mismatch")
    pages = [p for p in document.pages if p.page_id == ref.page_id]
    if len(pages) != 1:
        raise ValueError("unknown page")
    page = pages[0]
    for field in (
        "document_id",
        "raw_source_revision",
        "page_id",
        "page_index",
        "page_sha256",
        "width_px",
        "height_px",
        "grid_policy_id",
    ):
        if getattr(ref, field) != getattr(page, field) or getattr(ref, field) != getattr(
            artifact, field
        ):
            raise ValueError("page/grid/artifact binding mismatch")
    if page.processing_ref != artifact.artifact_id:
        raise ValueError("page references another immutable artifact")
    if (page.words, page.lines, page.blocks) != (artifact.words, artifact.lines, artifact.blocks):
        raise ValueError("recognized page differs from its retained artifact")
    if ref.transform_ref is not None:
        from .models import TransformPair

        bound = TransformPair(
            source_to_engine=artifact.source_to_engine, engine_to_source=artifact.engine_to_source
        )
        if resolved_transforms is None or resolved_transforms.get(ref.transform_ref) != bound:
            raise ValueError("missing or inconsistent retained transform reference")
    words, lines = (
        {w.stable_id: w for w in artifact.words},
        {line.stable_id: line for line in artifact.lines},
    )
    selected_words = ref.word_ids or ()
    selected_lines = ref.line_ids or ()
    for selected, mapping in ((selected_words, words), (selected_lines, lines)):
        if any(item not in mapping for item in selected):
            raise ValueError("foreign/stale evidence ID")
        if tuple(item for item in mapping if item in selected) != selected:
            raise ValueError("IDs must preserve retained artifact reading order")
    line_words = tuple(w for item in selected_lines for w in lines[item].ordered_child_ids)
    if selected_lines and selected_words and selected_words != line_words:
        raise ValueError("mixed IDs must describe the same ordered occurrence")
    elements = (
        [lines[item] for item in selected_lines]
        if selected_lines
        else [words[item] for item in selected_words]
    )
    excerpt = (
        (
            "\n".join(item.text for item in elements)
            if selected_lines
            else " ".join(item.text for item in elements)
        )
        if elements
        else None
    )
    if ref.excerpt_sha256 is not None:
        if (
            excerpt is None
            or hashlib.sha256(excerpt.encode("utf-8")).hexdigest() != ref.excerpt_sha256
        ):
            raise ValueError("excerpt must match exact retained Unicode/text order")
    geometric = bool(elements) and all(item.bbox_px is not None for item in elements)
    measured = geometric and all(
        item.geometry_provenance in ("native", "measured_ocr") for item in elements
    )
    if require_measured_spatial and not measured:
        raise ValueError("no measured/native spatial evidence")
    if ref.bbox_px is not None and elements:
        if not geometric:
            raise ValueError("cannot verify box/IDs without artifact geometry")
        boxes = [item.bbox_px for item in elements if item.bbox_px is not None]
        enclosure = (
            min(b.x0 for b in boxes),
            min(b.y0 for b in boxes),
            max(b.x1 for b in boxes),
            max(b.y1 for b in boxes),
        )
        actual = (ref.bbox_px.x0, ref.bbox_px.y0, ref.bbox_px.x1, ref.bbox_px.y1)
        if any(abs(a - b) > 1 for a, b in zip(actual, enclosure, strict=True)):
            raise ValueError("box contradicts selected artifact enclosure")
    return excerpt
