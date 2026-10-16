"""S7 source-region binding over unchanged canonical Docio/cited wires.

The injected access port owns caller authentication and previously issued tokens.
The injected decoder owns bounded, qualified source decoding. No default authority,
decoder, OCR engine, semantic region approximation or global registry is installed.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from screenshot_memory.contracts import MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS, Item
from screenshot_memory.shared.cited.models import (
    ArtifactRef,
    BoxPx,
    Pointer,
    RegionLocator,
    Resolution,
    ResolutionContext,
    ResolutionProvenance,
    ScreenshotPointer,
)
from screenshot_memory.shared.cited.registry import Registry
from screenshot_memory.shared.docio.identity import (
    canonical_bytes,
    grid_digest,
    validate_artifact_bytes,
    validate_evidence,
)
from screenshot_memory.shared.docio.models import BoxPx as DocioBox
from screenshot_memory.shared.docio.models import (
    Document,
    PageSourceResult,
    ProcessingArtifact,
    SourceEvidence,
    TransformPair,
)
from screenshot_memory.shared.vindex import GenerationToken, Store, StoreError
from screenshot_memory.shared.vindex.storage import MAX_PAYLOAD

DOMAIN = ("doc:page:bbox", "screenshot_collection", "source_region")
DECODE_ROW = hashlib.sha256(b"decode-source/1").hexdigest()[:32]
DOCUMENT_ROW = hashlib.sha256(b"s7-docio-document/1").hexdigest()[:32]
ARTIFACT_ROW = hashlib.sha256(b"s7-docio-artifact/1").hexdigest()[:32]


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ScreenshotAccess(Protocol):
    def policy_refs(self) -> tuple[ArtifactRef, ArtifactRef]: ...

    def issued_token(
        self, pointer: ScreenshotPointer, context: ResolutionContext
    ) -> GenerationToken | None:
        """Return the previously issued token after caller admission, never refresh it."""
        ...


@dataclass(frozen=True, slots=True)
class DecodedGrid:
    width_px: int
    height_px: int
    rgba8: bytes


class SourceGridDecoder(Protocol):
    grid_policy_id: str
    config_sha256: str
    processing_revision: str

    def decode(self, verified_original: bytes) -> DecodedGrid:
        """Bound before allocating; caller must qualify this actual decoder separately."""
        ...


def processing_revision(artifact: ProcessingArtifact) -> str:
    """App stage identity for the exact engine/config/grid/transform combination."""
    fields = (
        "engine",
        "engine_version",
        "config_digest",
        "grid_policy_id",
        "source_to_engine",
        "engine_to_source",
    )
    data = artifact.model_dump(mode="json")
    return "s7docio/1:" + _sha(canonical_bytes({key: data[key] for key in fields}))


def transform_reference(artifact: ProcessingArtifact) -> ArtifactRef:
    pair = TransformPair(
        source_to_engine=artifact.source_to_engine, engine_to_source=artifact.engine_to_source
    )
    return ArtifactRef(
        artifact_id=artifact.artifact_id,
        artifact_sha256=_sha(canonical_bytes(pair.model_dump(mode="json"))),
        profile_id="docio-transform-pair/1",
    )


def literal_line_pointer(
    document: Document, retained_artifact: bytes, query: str
) -> ScreenshotPointer | None:
    """Propose the first measured literal-line match; resolve it before display.

    This pure construction helper grants no access and authenticates no source.
    It does not select caption/image-only matches or invent missing geometry.
    """
    if type(query) is not str or not 1 <= len(query) <= 1000 or not query.strip():
        raise ValueError("invalid_query")
    document = Document.model_validate_json(canonical_bytes(document.model_dump(mode="json")))
    if (
        document.source_kind != "screenshot"
        or len(document.pages) != 1
        or document.pages[0].source_kind != "screenshot"
        or document.pages[0].page_index != 0
    ):
        return None
    artifact_sha = _sha(retained_artifact)
    artifact = validate_artifact_bytes(retained_artifact, artifact_sha)
    for line in artifact.lines:
        if (
            query.casefold() not in line.text.casefold()
            or line.bbox_px is None
            or line.geometry_provenance not in {"native", "measured_ocr"}
        ):
            continue
        box = line.bbox_px
        locator = RegionLocator(
            document_id=document.document_id,
            page_id=artifact.page_id,
            page_index=artifact.page_index,
            page_sha256=artifact.page_sha256,
            page_digest_algorithm="rgba8-source-grid-v1",
            source_grid_profile=artifact.grid_policy_id,
            width_px=artifact.width_px,
            height_px=artifact.height_px,
            bbox_px=BoxPx(x0=box.x0, y0=box.y0, x1=box.x1, y1=box.y1),
            line_ids=(line.stable_id,),
            excerpt_sha256=_sha(line.text.encode("utf-8")),
            transform_ref=transform_reference(artifact),
        )
        pointer = ScreenshotPointer(
            kind=DOMAIN[0],
            source_type=DOMAIN[1],
            locator_subtype=DOMAIN[2],
            source_id=document.document_id,
            source_sha256=document.original_content_sha256,
            source_revision=document.raw_source_revision,
            evidence_artifact_sha256=artifact_sha,
            locator=locator,
        )
        # Reuse producer occurrence/order/geometry validation; no copied alternate logic.
        validate_evidence(
            _evidence(pointer),
            document,
            retained_artifact,
            require_measured_spatial=True,
            resolved_transforms={
                locator.transform_ref.artifact_id: TransformPair(
                    source_to_engine=artifact.source_to_engine,
                    engine_to_source=artifact.engine_to_source,
                )
            },
        )
        return pointer
    return None


def _evidence(pointer: ScreenshotPointer) -> SourceEvidence:
    loc = pointer.locator
    box = loc.bbox_px
    return SourceEvidence(
        document_id=pointer.source_id,
        original_content_sha256=pointer.source_sha256,
        raw_source_revision=pointer.source_revision,
        page_id=loc.page_id,
        page_index=loc.page_index,
        page_sha256=loc.page_sha256,
        grid_policy_id=loc.source_grid_profile,
        width_px=loc.width_px,
        height_px=loc.height_px,
        evidence_artifact_sha256=pointer.evidence_artifact_sha256,
        bbox_px=None if box is None else DocioBox(x0=box.x0, y0=box.y0, x1=box.x1, y1=box.y1),
        word_ids=loc.word_ids,
        line_ids=loc.line_ids,
        excerpt_sha256=loc.excerpt_sha256,
        transform_ref=None if loc.transform_ref is None else loc.transform_ref.artifact_id,
    )


class ScreenshotResolver:
    def __init__(self, store: Store, access: ScreenshotAccess, decoder: SourceGridDecoder):
        if (
            not isinstance(store, Store)
            or not callable(getattr(access, "policy_refs", None))
            or not callable(getattr(access, "issued_token", None))
            or not callable(getattr(decoder, "decode", None))
        ):
            raise TypeError("explicit Store, trusted admission and bounded decoder required")
        self.store, self.access, self.decoder = store, access, decoder

    def _admit(self, pointer, context):
        try:
            refs = self.access.policy_refs()
            if type(refs) is not tuple or len(refs) != 2:
                raise ValueError("invalid_refs")
            access, generation = (ArtifactRef.model_validate(ref) for ref in refs)
            if (access, generation) != (context.access_policy_ref, context.generation_policy_ref):
                return None
            token = self.access.issued_token(pointer, context)
            if token is None:
                return None
            token = GenerationToken.model_validate(token)
            if (token.collection_id, token.item_id) != (context.namespace_id, pointer.source_id):
                return None
            return token
        except Exception:
            return None

    @staticmethod
    def _content(conn, token, row_id):
        row = conn.execute(
            "SELECT payload FROM content WHERE collection_id=? AND item_id=? "
            "AND generation=? AND row_id=?",
            (token.collection_id, token.item_id, token.item_generation, row_id),
        ).fetchone()
        if row is None:
            raise StoreError("evidence_missing")
        payload = bytes(row[0])
        if not 0 < len(payload) <= MAX_PAYLOAD:
            raise ValueError("evidence_bounds")
        return payload

    def resolve(self, pointer: Pointer, context: ResolutionContext) -> Resolution:
        try:
            pointer = ScreenshotPointer.model_validate(pointer)
            context = ResolutionContext.model_validate(context)
        except ValidationError:
            return Resolution(status="invalid", reason="wire_contract_error")
        token = self._admit(pointer, context)
        if token is None:
            return Resolution(status="unsupported", reason="access_not_allowed")
        if pointer.provenance_ref is not None:
            # No provenance-receipt profile is admitted by this app binding yet.
            return Resolution(status="unsupported", reason="provenance_profile_unavailable")
        try:
            with self.store.transaction() as conn:
                row = self.store._live(conn, token)
                self.store._published(conn, token)
                item = Item.model_validate_json(row["metadata"])
                stages = {stage.stage: stage for stage in item.stages}
                if stages["decode"].status != "ready" or stages["ocr"].status not in {
                    "ready",
                    "partial",
                }:
                    return Resolution(status="unsupported", reason="ocr_not_available")
                result = self._resolve_current(conn, token, item, stages, pointer, context)
                if self._admit(pointer, context) != token:
                    return Resolution(status="unsupported", reason="access_changed")
                return result
        except StoreError as error:
            if str(error) == "generation_mismatch":
                return Resolution(status="stale", reason="generation_mismatch")
            return Resolution(status="missing", reason="retained_source_unavailable")
        except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
            return Resolution(status="invalid", reason="source_or_evidence_mismatch")
        except Exception:
            return Resolution(status="invalid", reason="decoder_or_policy_unavailable")

    def _resolve_current(self, conn, token, item, stages, pointer, context):
        if (pointer.source_sha256, pointer.source_revision) != (
            item.original_content_sha256,
            item.raw_source_revision,
        ):
            raise ValueError("raw_identity")
        original = conn.execute(
            "SELECT * FROM owned_files WHERE collection_id=? AND item_id=? AND object_id=? "
            "AND role='original' AND state='ready'",
            (token.collection_id, token.item_id, item.source_object_id),
        ).fetchone()
        if original is None or (original["expected_sha256"], original["size_bytes"]) != (
            item.original_content_sha256,
            item.encoded_bytes,
        ):
            raise ValueError("original_identity")
        raw = self.store._verified_file(
            self.store.object_path(token.collection_id, token.item_id, item.source_object_id),
            original,
        )
        if not 0 < len(raw) <= MAX_IMAGE_BYTES or _sha(raw) != item.original_content_sha256:
            raise ValueError("original_bounds")
        decoded = self.decoder.decode(raw)
        if (
            type(decoded) is not DecodedGrid
            or type(decoded.width_px) is not int
            or type(decoded.height_px) is not int
            or min(decoded.width_px, decoded.height_px) <= 0
            or decoded.width_px * decoded.height_px > MAX_IMAGE_PIXELS
        ):
            raise ValueError("decoded_grid_bounds")
        grid_sha = grid_digest(decoded.width_px, decoded.height_px, decoded.rgba8)
        loc = pointer.locator
        if (
            (decoded.width_px, decoded.height_px, grid_sha)
            != (item.width_px, item.height_px, item.source_grid_sha256)
            or (loc.width_px, loc.height_px, loc.page_sha256)
            != (decoded.width_px, decoded.height_px, grid_sha)
            or loc.source_grid_profile != self.decoder.grid_policy_id
            or loc.page_index != 0
        ):
            raise ValueError("decoded_identity")
        source_raw = self._content(conn, token, DECODE_ROW)
        source = PageSourceResult.model_validate_json(source_raw)
        if (
            source.status != "ok"
            or len(source.pages) != 1
            or _sha(source_raw) != stages["decode"].result_sha256
            or stages["decode"].processing_revision != self.decoder.processing_revision
            or source.provenance.config_sha256 != self.decoder.config_sha256
            or source.provenance.source_grid_profile != self.decoder.grid_policy_id
        ):
            raise ValueError("decode_stage_identity")
        page_input = source.pages[0]
        if (
            page_input.document_id,
            page_input.original_content_sha256,
            page_input.raw_source_revision,
            page_input.page_id,
            page_input.page_index,
            page_input.page_sha256,
            page_input.width_px,
            page_input.height_px,
            page_input.grid_policy_id,
            page_input.source_kind,
        ) != (
            item.item_id,
            item.original_content_sha256,
            item.raw_source_revision,
            loc.page_id,
            0,
            grid_sha,
            decoded.width_px,
            decoded.height_px,
            self.decoder.grid_policy_id,
            "screenshot",
        ):
            raise ValueError("retained_decode_identity")
        document_raw = self._content(conn, token, DOCUMENT_ROW)
        if canonical_bytes(json.loads(document_raw)) != document_raw:
            raise ValueError("noncanonical_document")
        document = Document.model_validate_json(document_raw)
        artifact_raw = self._content(conn, token, ARTIFACT_ROW)
        artifact = validate_artifact_bytes(artifact_raw, pointer.evidence_artifact_sha256)
        if (
            item.evidence_artifact_sha256 != pointer.evidence_artifact_sha256
            or stages["ocr"].result_sha256 != pointer.evidence_artifact_sha256
            or stages["ocr"].processing_revision != processing_revision(artifact)
            or document.source_kind != "screenshot"
            or len(document.pages) != 1
            or document.provenance.producer != artifact.engine
            or document.provenance.version != artifact.engine_version
            or document.provenance.config_sha256 != artifact.config_digest
            or document.provenance.source_grid_profile != self.decoder.grid_policy_id
        ):
            raise ValueError("ocr_stage_identity")
        transform = loc.transform_ref
        if transform is not None and transform != transform_reference(artifact):
            raise ValueError("transform_identity")
        transforms = TransformPair(
            source_to_engine=artifact.source_to_engine, engine_to_source=artifact.engine_to_source
        )
        excerpt = validate_evidence(
            _evidence(pointer),
            document,
            artifact_raw,
            require_measured_spatial=True,
            resolved_transforms={} if transform is None else {transform.artifact_id: transforms},
        )
        selected = loc.line_ids or loc.word_ids or ()
        elements = {e.stable_id: e for e in (artifact.lines if loc.line_ids else artifact.words)}
        selected_elements = [elements[key] for key in selected]
        geometry = (
            "native"
            if all(e.geometry_provenance == "native" for e in selected_elements)
            else "measured_ocr"
        )
        confidence = selected_elements[0].ocr_confidence if len(selected_elements) == 1 else None
        spatial_only = context.required_scope == "spatial" or not excerpt
        if not excerpt and context.required_scope in {"text", "text_and_spatial"}:
            return Resolution(status="unsupported", reason="empty_excerpt")
        return Resolution(
            status="resolved",
            checked_source_revision=item.raw_source_revision,
            checked_source_sha256=_sha(raw),
            checked_artifact_sha256=_sha(artifact_raw),
            scope="spatial" if spatial_only else "text_and_spatial",
            excerpt=None if spatial_only else excerpt,
            excerpt_sha256=None if spatial_only else _sha(excerpt.encode("utf-8")),
            reason="source_region_verified",
            provenance=ResolutionProvenance(
                geometry_provenance=geometry, ocr_confidence=confidence, view_kind="raw_source"
            ),
        )


def install_screenshot_resolver(
    registry: Registry, store: Store, access: ScreenshotAccess, decoder: SourceGridDecoder
) -> ScreenshotResolver:
    resolver = ScreenshotResolver(store, access, decoder)
    registry.register(DOMAIN, resolver)
    return resolver
