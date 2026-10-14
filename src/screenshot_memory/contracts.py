"""Strict, side-effect-free S7 metadata. References confer no source access.

Validation proves internal consistency only, never checkpoint installation,
processing execution, hash authenticity, storage state or deletion completion.
"""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_COLLECTION_BYTES = 100 * 1024 * 1024
MAX_ITEMS = 30
MAX_COUNTER = 2**63 - 1

OpaqueID = Annotated[
    str, StringConstraints(pattern=r"^[a-f0-9]{32}$", min_length=32, max_length=32)
]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$", min_length=64, max_length=64)]
OpaqueRef = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$", min_length=1, max_length=256)
]
Label = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$", min_length=1, max_length=128)
]
Counter = Annotated[int, Field(ge=0, le=MAX_COUNTER)]
Stage = Literal["decode", "ocr", "caption", "text_embeddings", "image_embeddings"]
StageState = Literal[
    "not_run",
    "running",
    "ready",
    "partial",
    "failed",
    "missing",
    "blocked",
    "stale",
    "not_applicable",
]
Reason = Literal[
    "unavailable",
    "dependency_missing",
    "timeout",
    "limit_exceeded",
    "truncated",
    "invalid_output",
    "policy_hold",
    "generation_mismatch",
    "not_applicable",
    "processing_failed",
]


def _digest(domain: str, value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(domain.encode("ascii") + b"\n" + encoded).hexdigest()


def normalization_digest(
    method: Literal["l2", "none"], version: str, dtype: Literal["float32"] = "float32"
) -> str:
    """Identify a declared policy, without normalizing or inspecting any vector."""
    return _digest("s7-normalization/1", {"method": method, "version": version, "dtype": dtype})


class Metadata(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        validate_default=True,
        allow_inf_nan=False,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )
    schema_version: Literal[1] = 1

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_schema_integer(cls, value: object) -> object:
        # Literal[1] alone can accept True/1.0 by equality, even in strict mode.
        if type(value) is not int:
            raise ValueError("schema_version must be an integer, without coercion")
        return value


class Collection(Metadata):
    collection_id: OpaqueID
    generation: Counter
    cap: Annotated[int, Field(ge=1, le=MAX_ITEMS)] = MAX_ITEMS
    item_count: Annotated[int, Field(ge=0, le=MAX_ITEMS)] = 0
    encoded_bytes: Annotated[int, Field(ge=0, le=MAX_COLLECTION_BYTES)] = 0

    @model_validator(mode="after")
    def coherent_totals(self) -> Self:
        if self.item_count > self.cap:
            raise ValueError("item_count exceeds collection cap")
        if self.item_count == 0 and self.encoded_bytes != 0:
            raise ValueError("empty collection cannot declare source bytes")
        if (
            self.item_count
            and not self.item_count <= self.encoded_bytes <= self.item_count * MAX_IMAGE_BYTES
        ):
            raise ValueError("collection bytes inconsistent with bounded nonempty items")
        return self


class StageStatus(Metadata):
    stage: Stage
    status: StageState
    item_generation: Counter
    reason: Reason | None = None
    # Opaque owner/consumer result identities, never parallel Document/Page types.
    processing_revision: OpaqueRef | None = None
    result_sha256: Digest | None = None
    feature_space_id: Digest | None = None
    provenance: Literal["none", "declared", "synthetic", "observed"] = "none"

    @model_validator(mode="after")
    def explicit_outcome(self) -> Self:
        has_output = self.status in {"ready", "partial"}
        if has_output:
            if self.result_sha256 is None or self.processing_revision is None:
                raise ValueError("ready/partial stage requires result and processing identity")
            if self.provenance not in {"synthetic", "observed"}:
                raise ValueError("a declaration alone is not a completed stage")
        elif self.result_sha256 is not None or self.processing_revision is not None:
            raise ValueError("non-output stages cannot expose reusable result identities")
        if self.status in {"partial", "failed", "missing", "blocked", "stale", "not_applicable"}:
            if self.reason is None:
                raise ValueError("incomplete/not-applicable stage requires an explicit reason")
        elif self.reason is not None:
            raise ValueError("ready/not-run/running stages cannot carry failure reasons")
        if self.status == "not_applicable" and self.reason != "not_applicable":
            raise ValueError("not_applicable requires its exact reason")
        if self.status == "stale" and self.reason != "generation_mismatch":
            raise ValueError("stale requires generation_mismatch")
        allowed_reasons = {
            "partial": {"truncated", "limit_exceeded"},
            "failed": {"processing_failed", "invalid_output", "timeout"},
            "missing": {"unavailable", "dependency_missing"},
            "blocked": {"policy_hold", "dependency_missing", "limit_exceeded"},
            "stale": {"generation_mismatch"},
            "not_applicable": {"not_applicable"},
        }
        if self.status in allowed_reasons and self.reason not in allowed_reasons[self.status]:
            raise ValueError("stage reason does not describe its status")
        is_embedding = self.stage in {"text_embeddings", "image_embeddings"}
        if has_output and is_embedding and self.feature_space_id is None:
            raise ValueError("embedding output requires exact feature-space identity")
        if (not is_embedding or not has_output) and self.feature_space_id is not None:
            raise ValueError("feature-space identity belongs only to embedding outputs")
        if not has_output and self.provenance != "none":
            raise ValueError("unavailable output cannot claim feature provenance")
        return self


class Item(Metadata):
    item_id: OpaqueID
    collection_id: OpaqueID
    # Logical handle only: not a path, URL, access capability or file opener.
    source_object_id: OpaqueID
    original_content_sha256: Digest
    raw_source_revision: OpaqueRef
    revision: Counter
    generation: Counter
    collection_generation: Counter
    encoded_bytes: Annotated[int, Field(ge=1, le=MAX_IMAGE_BYTES)]
    width_px: Annotated[int, Field(ge=1, le=MAX_IMAGE_PIXELS)]
    height_px: Annotated[int, Field(ge=1, le=MAX_IMAGE_PIXELS)]
    source_grid_sha256: Digest | None = None
    evidence_artifact_sha256: Digest | None = None
    state: Literal["pending", "partial", "ready", "failed", "deleting", "cleanup_pending"]
    stages: Annotated[tuple[StageStatus, ...], Field(min_length=5, max_length=5)]

    @model_validator(mode="after")
    def coherent_processing(self) -> Self:
        if self.width_px * self.height_px > MAX_IMAGE_PIXELS:
            raise ValueError("decoded image exceeds pixel cap")
        by_stage = {value.stage: value for value in self.stages}
        expected = {"decode", "ocr", "caption", "text_embeddings", "image_embeddings"}
        if set(by_stage) != expected:
            raise ValueError("exactly one status for each of the five stages is required")
        for value in self.stages:
            if value.item_generation > self.generation:
                raise ValueError("stage cannot originate from a future item generation")
            if (
                value.status in {"ready", "partial", "running"}
                and value.item_generation != self.generation
            ):
                raise ValueError("active/reusable stage must match current item generation")
        decode_done = by_stage["decode"].status == "ready"
        ocr_done = by_stage["ocr"].status in {"ready", "partial"}
        if (self.source_grid_sha256 is not None) != decode_done:
            raise ValueError("retained source-grid identity requires a ready decode stage")
        if (self.evidence_artifact_sha256 is not None) != ocr_done:
            raise ValueError("recognized evidence identity requires ready/partial OCR")
        if (
            any(s.status in {"ready", "partial"} for s in self.stages if s.stage != "decode")
            and not decode_done
        ):
            raise ValueError("derived output cannot precede a successful decode")
        states = {s.status for s in self.stages}
        if self.state == "pending" and not states <= {"not_run", "running"}:
            raise ValueError("pending item cannot hide completed or failed stages")
        if self.state == "ready" and not states <= {"ready", "not_applicable"}:
            raise ValueError("ready item cannot contain incomplete stages")
        if self.state == "ready" and not decode_done:
            raise ValueError("ready item requires decoded source")
        if self.state == "ready" and any(
            by_stage[name].status != "ready" for name in ("ocr", "caption", "image_embeddings")
        ):
            raise ValueError(
                "ready item requires OCR/caption/image output; only empty text may be inapplicable"
            )
        if self.state == "failed" and "failed" not in states:
            raise ValueError("failed item needs a failed stage")
        if self.state == "partial":
            if not states & {"ready", "partial"} or states <= {"ready", "not_applicable"}:
                raise ValueError("partial item requires some output and an incomplete stage")
        return self

    def belongs_to(self, collection: Collection) -> bool:
        """Declared scope/generation match only; never access or write authority."""
        return (
            self.collection_id == collection.collection_id
            and self.collection_generation == collection.generation
        )


class FeatureSpaceDescriptor(Metadata):
    modality: Literal["text", "image"]
    provenance: Literal["declared", "synthetic", "observed"]
    provenance_receipt_sha256: Digest | None = None
    model_id: Label
    model_version: Label
    checkpoint_sha256: Digest | None = None
    weights_sha256: Digest | None = None
    implementation_version: Label
    dimensions: Annotated[int, Field(ge=1, le=16384)]
    preprocessing_id: Label
    preprocessing_version: Label
    preprocessing_sha256: Digest
    tokenizer_id: Label | None = None
    tokenizer_version: Label | None = None
    tokenizer_sha256: Digest | None = None
    max_input_tokens: Annotated[int, Field(ge=1, le=32768)] | None = None
    query_prefix: Annotated[str, Field(max_length=512)] = ""
    document_prefix: Annotated[str, Field(max_length=512)] = ""
    dtype: Literal["float32"] = "float32"
    normalization: Literal["l2", "none"]
    normalization_version: Label
    normalization_sha256: Digest

    @field_validator("query_prefix", "document_prefix")
    @classmethod
    def prefix_utf8_bound(cls, value: str) -> str:
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("prefix must be valid UTF8") from exc
        if len(encoded) > 512:
            raise ValueError("prefix exceeds512 UTF8 bytes")
        return value

    @model_validator(mode="after")
    def coherent_descriptor(self) -> Self:
        tokenizer = (
            self.tokenizer_id,
            self.tokenizer_version,
            self.tokenizer_sha256,
            self.max_input_tokens,
        )
        if any(v is not None for v in tokenizer) and not all(v is not None for v in tokenizer):
            raise ValueError("tokenizer identity/version/digest/cap must be supplied together")
        if self.modality == "text" and any(v is None for v in tokenizer):
            raise ValueError("text space requires a complete tokenizer declaration")
        if self.provenance == "observed" and any(
            v is None
            for v in (self.checkpoint_sha256, self.weights_sha256, self.provenance_receipt_sha256)
        ):
            raise ValueError("observed provenance requires checkpoint/weights/receipt references")
        if self.provenance != "observed" and self.provenance_receipt_sha256 is not None:
            raise ValueError("unobserved provenance cannot claim an observation receipt")
        expected = normalization_digest(self.normalization, self.normalization_version, self.dtype)
        if self.normalization_sha256 != expected:
            raise ValueError("normalization descriptor digest mismatch")
        return self


class FeatureSpace(Metadata):
    feature_space_id: Digest
    descriptor: FeatureSpaceDescriptor

    @classmethod
    def from_descriptor(cls, descriptor: FeatureSpaceDescriptor) -> Self:
        return cls(
            feature_space_id=_digest("s7-feature-space/1", descriptor.model_dump(mode="json")),
            descriptor=descriptor,
        )

    @model_validator(mode="after")
    def exact_descriptor_identity(self) -> Self:
        expected = _digest("s7-feature-space/1", self.descriptor.model_dump(mode="json"))
        if self.feature_space_id != expected:
            raise ValueError("feature-space descriptor digest mismatch")
        return self

    def compatible_with(self, other: "FeatureSpace") -> bool:
        """Exact declared-space match only, not successful vector/model validation."""
        return self.feature_space_id == other.feature_space_id
