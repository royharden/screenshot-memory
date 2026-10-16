"""Canonical OCR port with source binding and atomic app-owned publication."""

import hashlib
import re
import time
import uuid
from dataclasses import dataclass
from typing import Literal, Protocol

from screenshot_memory.contracts import StageStatus
from screenshot_memory.regions import (
    ARTIFACT_ROW,
    DECODE_ROW,
    DOCUMENT_ROW,
    SourceGridDecoder,
    processing_revision,
)
from screenshot_memory.shared.docio.identity import (
    artifact_bytes,
    canonical_bytes,
    engine_box_to_source,
    grid_digest,
)
from screenshot_memory.shared.docio.models import (
    AffineTransform,
    Bounds,
    Document,
    EngineBox,
    Line,
    OcrResult,
    Page,
    PageInput,
    PageSourceResult,
    ProcessingArtifact,
    Provenance,
    RecognizedGrid,
    TransformPair,
    Word,
)
from screenshot_memory.shared.vindex import GenerationToken, Store, StoreError

Quad = tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class EngineIdentity:
    producer: str
    version: str
    config_sha256: str
    source_grid_profile: str
    provenance: Literal["observed", "synthetic"]

    def __post_init__(self):
        if (
            not self.producer
            or not self.version
            or not re.fullmatch(r"[0-9a-f]{64}", self.config_sha256)
            or self.provenance not in {"observed", "synthetic"}
        ):
            raise ValueError("invalid_engine_identity")


@dataclass(frozen=True, slots=True)
class EngineWord:
    text: str
    score: float | None
    quad: Quad


@dataclass(frozen=True, slots=True)
class EngineLine:
    text: str
    score: float | None
    quad: Quad
    words: tuple[EngineWord, ...]


@dataclass(frozen=True, slots=True)
class EnginePage:
    lines: tuple[EngineLine, ...]
    confirmed_blank: bool = False


class OcrEngineError(Exception):
    """An unavailable native result, distinct from successful blank recognition."""


class SourceFrameEngine(Protocol):
    identity: EngineIdentity

    def recognize(self, rgba8: bytes, width: int, height: int, bounds: Bounds) -> EnginePage:
        """Return actual source-frame observations; controls must declare synthetic."""
        ...


def _row(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _closed(status, issue):
    return OcrResult(
        status=status,
        page=None,
        issues=(issue,),
        capabilities=(),
        processing_artifact_ref=None,
    )


def _box(quad: Quad, transforms: TransformPair, page: PageInput):
    if (
        type(quad) is not tuple
        or len(quad) != 4
        or any(
            type(point) is not tuple
            or len(point) != 2
            or any(type(value) not in {int, float} for value in point)
            for point in quad
        )
    ):
        raise ValueError("invalid_engine_quad")
    # The native SDK already returns original-input coordinates. Apply one explicit
    # identity mapping through the canonical engine-to-source validator.
    return engine_box_to_source(
        EngineBox(
            x0=min(p[0] for p in quad),
            y0=min(p[1] for p in quad),
            x1=max(p[0] for p in quad),
            y1=max(p[1] for p in quad),
        ),
        transforms,
        page.width_px,
        page.height_px,
    )


class StoreOcrAdapter:
    """Implements Docio OcrAdapter for one trusted, previously issued item token.

    Source reads and publication recheck that token; it is never refreshed here.
    Computation runs outside a database write lock. Failure publishes no output.
    Native calls require a separately bounded worker; deadline checks here cannot
    interrupt native code. The engine port is trusted application configuration.
    """

    def __init__(
        self,
        store: Store,
        token: GenerationToken,
        decoder: SourceGridDecoder,
        engine: SourceFrameEngine,
    ):
        if not isinstance(store, Store) or not isinstance(engine.identity, EngineIdentity):
            raise TypeError("explicit_store_and_engine_required")
        self.store = store
        self.token = GenerationToken.model_validate(token)
        self.decoder = decoder
        self.engine = engine
        self._clock = time.monotonic

    def recognize(self, page: PageInput, bounds: Bounds) -> OcrResult:
        started = self._clock()

        def deadline():
            if self._clock() - started > bounds.deadline_s:
                raise TimeoutError

        try:
            # JSON validation also rejects unvalidated model_copy replacements.
            page = PageInput.model_validate_json(page.model_dump_json())
            bounds = Bounds.model_validate_json(bounds.model_dump_json())
            info = self.engine.identity
            item = self.store.item(self.token)
            stages = {s.stage: s for s in item.stages}
            if stages["ocr"].status in {"ready", "partial"}:
                return _closed("unsupported", "ocr_output_immutable")
            if stages["decode"].status != "ready":
                return _closed("unsupported", "decode_not_ready")
            source_raw = self.store.get("content", self.token, DECODE_ROW)
            if source_raw is None:
                return _closed("invalid", "decode_record_missing")
            source = PageSourceResult.model_validate_json(source_raw)
            if (
                source.status != "ok"
                or len(source.pages) != 1
                or source.pages[0] != page
                or page.source_kind != "screenshot"
                or page.page_index != 0
                or page.document_id != item.item_id
                or page.original_content_sha256 != item.original_content_sha256
                or page.raw_source_revision != item.raw_source_revision
                or page.page_sha256 != item.source_grid_sha256
                or (page.width_px, page.height_px) != (item.width_px, item.height_px)
                or hashlib.sha256(source_raw).hexdigest() != stages["decode"].result_sha256
                or stages["decode"].processing_revision != self.decoder.processing_revision
                or source.provenance.config_sha256 != self.decoder.config_sha256
                or source.provenance.source_grid_profile != self.decoder.grid_policy_id
                or page.grid_policy_id != self.decoder.grid_policy_id
                or page.grid_policy_id != info.source_grid_profile
            ):
                return _closed("invalid", "source_binding_mismatch")
            if (
                item.encoded_bytes > bounds.max_encoded_bytes
                or page.width_px * page.height_px > bounds.max_decoded_pixels
            ):
                return _closed("limit_exceeded", "source_limit_exceeded")
            raw = self.store.read_file(self.token, item.source_object_id)
            if (
                len(raw) != item.encoded_bytes
                or hashlib.sha256(raw).hexdigest() != item.original_content_sha256
            ):
                return _closed("invalid", "source_bytes_mismatch")
            grid = self.decoder.decode(raw)
            if (
                grid.width_px,
                grid.height_px,
                grid_digest(grid.width_px, grid.height_px, grid.rgba8),
            ) != (page.width_px, page.height_px, page.page_sha256):
                return _closed("invalid", "source_grid_mismatch")
            deadline()
            output = self.engine.recognize(grid.rgba8, grid.width_px, grid.height_px, bounds)
            deadline()
            if self.engine.identity != info:
                return _closed("invalid", "engine_identity_changed")
            if type(output) is not EnginePage or type(output.lines) is not tuple:
                return _closed("invalid", "invalid_engine_output")
            if not output.lines and output.confirmed_blank is not True:
                return _closed("unavailable", "blank_not_confirmed")
            if output.lines and output.confirmed_blank:
                return _closed("invalid", "contradictory_blank")
            if len(output.lines) > bounds.max_lines:
                return _closed("limit_exceeded", "line_limit_exceeded")
            if sum(len(line.words) for line in output.lines) > bounds.max_words:
                return _closed("limit_exceeded", "word_limit_exceeded")
            if (
                sum(
                    len(line.text.encode()) + sum(len(word.text.encode()) for word in line.words)
                    for line in output.lines
                )
                > bounds.max_output_bytes
            ):
                return _closed("limit_exceeded", "output_limit_exceeded")
            identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            transforms = TransformPair(
                source_to_engine=AffineTransform(
                    direction="source_to_engine", algorithm="ocr-returned-source/1", matrix=identity
                ),
                engine_to_source=AffineTransform(
                    direction="engine_to_source", algorithm="ocr-returned-source/1", matrix=identity
                ),
            )
            artifact_id = uuid.uuid4().hex
            words, lines = [], []
            common = dict(
                geometry_provenance="measured_ocr",
                source_engine=info.producer,
                source_engine_version=info.version,
            )
            for i, line in enumerate(output.lines):
                if type(line) is not EngineLine or not line.text.strip() or not line.words:
                    return _closed("invalid", "word_geometry_unavailable")
                ids = []
                for word in line.words:
                    if type(word) is not EngineWord or not word.text.strip():
                        return _closed("invalid", "invalid_word")
                    wid = f"{artifact_id}:word:{len(words)}"
                    ids.append(wid)
                    words.append(
                        Word(
                            stable_id=wid,
                            text=word.text,
                            bbox_px=_box(word.quad, transforms, page),
                            ocr_confidence=word.score,
                            **common,
                        )
                    )
                lines.append(
                    Line(
                        stable_id=f"{artifact_id}:line:{i}",
                        text=line.text,
                        bbox_px=_box(line.quad, transforms, page),
                        ocr_confidence=line.score,
                        ordered_child_ids=tuple(ids),
                        **common,
                    )
                )
            fields = {
                key: getattr(page, key)
                for key in RecognizedGrid.model_fields
                if key not in {"words", "lines", "blocks"}
            }
            artifact = ProcessingArtifact(
                **fields,
                words=tuple(words),
                lines=tuple(lines),
                blocks=(),
                artifact_id=artifact_id,
                engine=info.producer,
                engine_version=info.version,
                config_digest=info.config_sha256,
                source_to_engine=transforms.source_to_engine,
                engine_to_source=transforms.engine_to_source,
            )
            recognized = Page(
                **{key: getattr(artifact, key) for key in RecognizedGrid.model_fields},
                source_kind="screenshot",
                processing_ref=artifact_id,
            )
            document = Document(
                document_id=item.item_id,
                original_content_sha256=item.original_content_sha256,
                raw_source_revision=item.raw_source_revision,
                source_kind="screenshot",
                pages=(recognized,),
                provenance=Provenance(
                    producer=info.producer,
                    version=info.version,
                    config_sha256=info.config_sha256,
                    source_grid_profile=page.grid_policy_id,
                ),
            )
            retained = artifact_bytes(artifact)
            payload = [
                ("content", DOCUMENT_ROW, canonical_bytes(document.model_dump(mode="json"))),
                ("content", ARTIFACT_ROW, retained),
            ]
            for table, elements in (("words", words), ("lines", lines)):
                payload.extend(
                    (table, _row(e.stable_id), canonical_bytes(e.model_dump(mode="json")))
                    for e in elements
                )
            fts = [("line_fts", _row(line.stable_id), line.text) for line in lines]
            if lines:
                fts.append(("item_fts", _row("ocr-item/1"), "\n".join(line.text for line in lines)))
            if (
                sum(len(p[2]) for p in payload) + sum(len(f[2].encode()) for f in fts)
                > bounds.max_output_bytes
            ):
                return _closed("limit_exceeded", "output_limit_exceeded")
            digest = hashlib.sha256(retained).hexdigest()
            ocr = StageStatus(
                stage="ocr",
                status="ready",
                item_generation=self.token.item_generation,
                processing_revision=processing_revision(artifact),
                result_sha256=digest,
                provenance=info.provenance,
            )
            new_stages = tuple(ocr if s.stage == "ocr" else s for s in item.stages)
            updated = item.model_copy(
                update={
                    "revision": item.revision + 1,
                    "state": "ready" if all(s.status == "ready" for s in new_stages) else "partial",
                    "evidence_artifact_sha256": digest,
                    "stages": new_stages,
                }
            )
            deadline()
            self.store.publish_stage(
                self.token, item.revision, "ocr", updated, tuple(payload), tuple(fts)
            )
            return OcrResult(
                status="ok",
                page=recognized,
                issues=(),
                capabilities=("source_frame_word_line_geometry", info.provenance + "_ocr"),
                processing_artifact_ref=artifact_id,
            )
        except TimeoutError:
            return _closed("timeout", "ocr_deadline_exceeded")
        except StoreError:
            return _closed("invalid", "source_generation_revision_or_store_unavailable")
        except OcrEngineError:
            return _closed("unavailable", "native_ocr_unavailable")
        except (ValueError, TypeError, AttributeError, OSError):
            return _closed("invalid", "invalid_source_or_output")
        except Exception:
            return _closed("unavailable", "ocr_processing_unavailable")
