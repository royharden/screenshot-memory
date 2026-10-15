"""Closed source-grid and recognized-artifact wires. No decoding or source lookup."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

OpaqueId = Annotated[str, Field(min_length=1, max_length=512)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
Probability = Annotated[float, Field(ge=0, le=1)]
SourceKind = Literal["image", "pdf", "native_text", "screenshot"]
GeometryOrigin = Literal["measured_ocr", "native", "model_claimed", "none"]
Status = Literal["ok", "unsupported", "unavailable", "invalid", "limit_exceeded", "timeout"]


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)
    schema_version: Literal[1] = 1

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version must be the integer 1")
        return value


class Provenance(Wire):
    producer: OpaqueId
    version: OpaqueId
    config_sha256: Sha256
    source_grid_profile: OpaqueId
    refs: tuple[OpaqueId, ...] = ()


class BoxPx(Wire):
    units: Literal["px"] = "px"
    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not (0 <= self.x0 < self.x1 and 0 <= self.y0 < self.y1):
            raise ValueError("box must have positive extent in source pixels")
        return self

    def within(self, width: int, height: int) -> None:
        if self.x1 > width or self.y1 > height:
            raise ValueError("box exceeds source grid")


class EngineBox(BoxPx):
    frame: Literal["engine"] = "engine"


class NormalizedBox(Wire):
    units: Literal["normalized"] = "normalized"
    originating_width_px: PositiveInt
    originating_height_px: PositiveInt
    x0: Annotated[float, Field(ge=0, le=1)]
    y0: Annotated[float, Field(ge=0, le=1)]
    x1: Annotated[float, Field(ge=0, le=1)]
    y1: Annotated[float, Field(ge=0, le=1)]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("normalized box must have positive extent")
        return self


Matrix = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]


class AffineTransform(Wire):
    direction: Literal["source_to_engine", "engine_to_source"]
    algorithm: OpaqueId
    matrix: Matrix

    @model_validator(mode="after")
    def invertible_affine(self) -> Self:
        m = self.matrix
        if m[2] != (0, 0, 1) or m[0][0] * m[1][1] - m[0][1] * m[1][0] == 0:
            raise ValueError("finite invertible affine 3x3 required")
        return self


class TransformPair(Wire):
    source_to_engine: AffineTransform
    engine_to_source: AffineTransform

    @model_validator(mode="after")
    def inverse_pair(self) -> Self:
        if self.source_to_engine.direction != "source_to_engine":
            raise ValueError("wrong forward direction")
        if self.engine_to_source.direction != "engine_to_source":
            raise ValueError("wrong inverse direction")
        a, b = self.source_to_engine.matrix, self.engine_to_source.matrix
        for i in range(3):
            for j in range(3):
                if abs(sum(a[i][k] * b[k][j] for k in range(3)) - (i == j)) > 1e-8:
                    raise ValueError("inconsistent inverse matrices")
        return self


class Word(Wire):
    stable_id: OpaqueId
    text: str
    bbox_px: BoxPx | None
    ocr_confidence: Probability | None
    geometry_provenance: GeometryOrigin
    source_engine: OpaqueId
    source_engine_version: OpaqueId

    @field_validator("bbox_px", mode="before")
    @classmethod
    def source_frame_only(cls, value: object) -> object:
        if isinstance(value, EngineBox):
            raise ValueError("persisted geometry must already be in source frame")
        return value

    @model_validator(mode="after")
    def honest_geometry(self) -> Self:
        if self.geometry_provenance == "none" and self.bbox_px is not None:
            raise ValueError("unattributed geometry")
        if self.geometry_provenance == "model_claimed" and self.ocr_confidence is not None:
            raise ValueError("vision assertion cannot supply OCR confidence")
        return self


class Line(Word):
    ordered_child_ids: tuple[OpaqueId, ...]


class Block(Word):
    ordered_child_ids: tuple[OpaqueId, ...]


class RecognizedGrid(Wire):
    document_id: OpaqueId
    raw_source_revision: OpaqueId
    page_id: OpaqueId
    page_index: NonnegativeInt
    width_px: PositiveInt
    height_px: PositiveInt
    page_sha256: Sha256
    grid_policy_id: OpaqueId
    words: tuple[Word, ...]
    lines: tuple[Line, ...]
    blocks: tuple[Block, ...]

    @model_validator(mode="after")
    def hierarchy(self) -> Self:
        elements = (*self.words, *self.lines, *self.blocks)
        ids = [item.stable_id for item in elements]
        if len(set(ids)) != len(ids):
            raise ValueError("artifact element IDs must be unique")
        for item in elements:
            if item.bbox_px:
                item.bbox_px.within(self.width_px, self.height_px)
        words = {w.stable_id: w for w in self.words}
        lines = {line.stable_id: line for line in self.lines}
        for parents, children in ((self.lines, words), (self.blocks, lines)):
            assigned: set[str] = set()
            for parent in parents:
                child_ids = parent.ordered_child_ids
                if len(set(child_ids)) != len(child_ids):
                    raise ValueError("duplicate child")
                if not set(child_ids) <= children.keys() or assigned.intersection(child_ids):
                    raise ValueError("foreign or multiply assigned child")
                if tuple(item for item in children if item in child_ids) != child_ids:
                    raise ValueError("children must preserve artifact reading order")
                assigned.update(child_ids)
        return self


class Page(RecognizedGrid):
    source_kind: SourceKind
    processing_ref: OpaqueId


class Document(Wire):
    document_id: OpaqueId
    original_content_sha256: Sha256
    raw_source_revision: OpaqueId
    source_kind: SourceKind
    pages: tuple[Page, ...]
    provenance: Provenance

    @model_validator(mode="after")
    def source_binding(self) -> Self:
        from .identity import raw_revision

        if self.raw_source_revision != raw_revision(self.document_id, self.original_content_sha256):
            raise ValueError("raw revision differs from original raw identity")
        if len({p.page_id for p in self.pages}) != len(self.pages):
            raise ValueError("duplicate page ID")
        if len({p.page_index for p in self.pages}) != len(self.pages):
            raise ValueError("duplicate zero-based page index")
        for page in self.pages:
            if (page.document_id, page.raw_source_revision, page.source_kind) != (
                self.document_id,
                self.raw_source_revision,
                self.source_kind,
            ):
                raise ValueError("page/raw source mismatch")
        return self


class ProcessingArtifact(RecognizedGrid):
    artifact_id: OpaqueId
    engine: OpaqueId
    engine_version: OpaqueId
    config_digest: Sha256
    source_to_engine: AffineTransform
    engine_to_source: AffineTransform
    text_order_policy: Literal["docio-text/1"] = "docio-text/1"

    @model_validator(mode="after")
    def engine_binding(self) -> Self:
        TransformPair(
            source_to_engine=self.source_to_engine, engine_to_source=self.engine_to_source
        )
        for item in (*self.words, *self.lines, *self.blocks):
            if (item.source_engine, item.source_engine_version) != (
                self.engine,
                self.engine_version,
            ):
                raise ValueError("element engine provenance differs from artifact")
        return self


class SourceEvidence(Wire):
    """Neutral producer evidence; deliberately not the external tagged Pointer union."""

    document_id: OpaqueId
    original_content_sha256: Sha256
    raw_source_revision: OpaqueId
    page_id: OpaqueId
    page_index: NonnegativeInt
    page_sha256: Sha256
    grid_policy_id: OpaqueId
    width_px: PositiveInt
    height_px: PositiveInt
    evidence_artifact_sha256: Sha256
    bbox_px: BoxPx | None
    word_ids: tuple[OpaqueId, ...] | None
    line_ids: tuple[OpaqueId, ...] | None
    excerpt_sha256: Sha256 | None
    transform_ref: OpaqueId | None

    _source_frame = field_validator("bbox_px", mode="before")(Word.source_frame_only.__func__)

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if not (self.bbox_px or self.word_ids or self.line_ids):
            raise ValueError("box or nonempty word/line set required")
        for ids in (self.word_ids, self.line_ids):
            if ids is not None and (not ids or len(set(ids)) != len(ids)):
                raise ValueError("empty or duplicate evidence IDs")
        if self.bbox_px:
            self.bbox_px.within(self.width_px, self.height_px)
        return self


class Bounds(Wire):
    max_pages: PositiveInt
    max_encoded_bytes: PositiveInt
    max_decoded_pixels: PositiveInt
    max_words: PositiveInt
    max_lines: PositiveInt
    max_blocks: PositiveInt
    max_output_bytes: PositiveInt
    deadline_s: Annotated[float, Field(gt=0)]


class PageInput(Wire):
    execution_ref: OpaqueId
    document_id: OpaqueId
    original_content_sha256: Sha256
    raw_source_revision: OpaqueId
    page_id: OpaqueId
    page_index: NonnegativeInt
    page_sha256: Sha256
    width_px: PositiveInt
    height_px: PositiveInt
    grid_policy_id: OpaqueId
    source_kind: SourceKind
    transforms: TransformPair

    @model_validator(mode="after")
    def raw_binding(self) -> Self:
        from .identity import raw_revision

        if self.raw_source_revision != raw_revision(self.document_id, self.original_content_sha256):
            raise ValueError("input raw source identity mismatch")
        return self


class PageSourceResult(Wire):
    status: Status
    pages: tuple[PageInput, ...]
    issues: tuple[OpaqueId, ...]
    capabilities: tuple[OpaqueId, ...]
    provenance: Provenance

    @model_validator(mode="after")
    def success_branch(self) -> Self:
        if self.status != "ok" and self.pages:
            raise ValueError("failed source cannot claim successful pages")
        return self


class OcrResult(Wire):
    status: Status
    page: Page | None
    issues: tuple[OpaqueId, ...]
    capabilities: tuple[OpaqueId, ...]
    processing_artifact_ref: OpaqueId | None

    @model_validator(mode="after")
    def success_branch(self) -> Self:
        if self.status == "ok" and (self.page is None or self.processing_artifact_ref is None):
            raise ValueError("ok needs a recognized Page, including genuine blank pages")
        if self.status != "ok" and (
            self.page is not None or self.processing_artifact_ref is not None
        ):
            raise ValueError("failed recognition cannot claim success page/artifact")
        return self


WIRE_MODELS = (
    Document,
    Page,
    ProcessingArtifact,
    SourceEvidence,
    Bounds,
    PageInput,
    PageSourceResult,
    OcrResult,
    NormalizedBox,
    EngineBox,
)
