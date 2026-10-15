"""Bounded float32 vectors and explicit ordered cross-modal declarations.

No import performs IO, model loading or inference. Metadata and opaque receipt
validation establish consistency only; they cannot authenticate a checkpoint,
capability or observation. Native model admission is a separate obligation.
"""

import math
import struct
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from screenshot_memory.contracts import Digest, FeatureSpace, Label, Metadata, _digest

L2_ABSOLUTE_TOLERANCE = 1e-5


class VectorError(ValueError):
    """Invalid vector or incompatible declared feature spaces; no input content."""


def _space(value: FeatureSpace) -> FeatureSpace:
    # Revalidate even constructed/copied objects at every public entrypoint.
    return FeatureSpace.model_validate(value)


def decode_float32(payload: bytes, space: FeatureSpace) -> tuple[float, ...]:
    """Validate exact little-endian float32 bytes; never silently normalize."""
    descriptor = _space(space).descriptor
    if type(payload) is not bytes or len(payload) != 4 * descriptor.dimensions:
        raise VectorError("vector must be exact bounded float32 bytes")
    values = struct.unpack(f"<{descriptor.dimensions}f", payload)
    if not all(math.isfinite(value) for value in values):
        raise VectorError("vector must be finite")
    norm = math.hypot(*values)
    if norm == 0:
        raise VectorError("zero vector is not searchable")
    if descriptor.normalization == "l2" and abs(norm - 1) > L2_ABSOLUTE_TOLERANCE:
        raise VectorError("vector violates declared l2 normalization")
    return values


def normalize_float32(values: tuple[float, ...], space: FeatureSpace) -> bytes:
    """Explicit float32 cast then L2 normalization; no model/feature provenance claim.

    Only an already bounded tuple of finite Python floats is accepted. SDK
    adapters must explicitly convert their outputs and bind the actual space.
    The output is validated after float32 rounding, including underflow to zero.
    """
    descriptor = _space(space).descriptor
    if descriptor.normalization != "l2":
        raise VectorError("explicit l2 normalization requires an l2 feature space")
    if type(values) is not tuple or len(values) != descriptor.dimensions:
        raise VectorError("wrong vector dimensions or input container")
    if any(type(value) is not float or not math.isfinite(value) for value in values):
        raise VectorError("normalization requires finite floats without coercion")
    try:
        cast = struct.unpack(f"<{len(values)}f", struct.pack(f"<{len(values)}f", *values))
    except (OverflowError, struct.error) as exc:
        raise VectorError("input exceeds float32 representation") from exc
    if not all(math.isfinite(value) for value in cast):
        raise VectorError("input exceeds float32 representation")
    norm = math.hypot(*cast)
    if norm == 0:
        raise VectorError("zero vector after float32 cast")
    payload = struct.pack(f"<{len(cast)}f", *(value / norm for value in cast))
    decode_float32(payload, space)
    return payload


def _admit_provenance(spaces: tuple[FeatureSpace, ...], require_observed: bool) -> None:
    if type(require_observed) is not bool:
        raise VectorError("require_observed must be an explicit boolean")
    if require_observed and any(space.descriptor.provenance != "observed" for space in spaces):
        raise VectorError("unobserved spaces require explicit synthetic/declaration opt-in")
    if any(space.descriptor.normalization != "l2" for space in spaces):
        raise VectorError("search cosine requires explicit l2 spaces")


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    # Normalize by measured norms as well, avoiding tiny float32 unit-norm drift.
    ln, rn = math.hypot(*left), math.hypot(*right)
    value = math.fsum((a / ln) * (b / rn) for a, b in zip(left, right, strict=True))
    return max(-1.0, min(1.0, value))


def cosine_within(
    query: bytes,
    query_space: FeatureSpace,
    target: bytes,
    target_space: FeatureSpace,
    *,
    require_observed: bool = True,
) -> float:
    """Exact-space cosine; observed declarations still need external admission."""
    query_space, target_space = _space(query_space), _space(target_space)
    if not query_space.compatible_with(target_space):
        raise VectorError("different feature spaces")
    _admit_provenance((query_space, target_space), require_observed)
    return _cosine(decode_float32(query, query_space), decode_float32(target, target_space))


class CrossModalAlignmentDescriptor(Metadata):
    """Complete ordered metadata binding; not verification of the referenced proof."""

    query_space: FeatureSpace
    target_space: FeatureSpace
    dimensions: Annotated[int, Field(ge=512, le=512)] = 512
    joint_checkpoint_id: Label
    joint_checkpoint_sha256: Digest
    text_export_revision: Label
    image_export_revision: Label
    text_config_sha256: Digest
    image_config_sha256: Digest
    paired_source_metadata_sha256: Digest
    provenance: Literal["declared", "synthetic", "observed"]
    capability_receipt_sha256: Digest | None = None

    @model_validator(mode="after")
    def coherent_pair(self) -> Self:
        query, target = self.query_space.descriptor, self.target_space.descriptor
        if query.modality != "text" or target.modality != "image":
            raise ValueError("alignment requires ordered text-query/image-target spaces")
        if query.dimensions != self.dimensions or target.dimensions != self.dimensions:
            raise ValueError("alignment dimensions differ from paired spaces")
        if query.normalization != "l2" or target.normalization != "l2":
            raise ValueError("alignment requires l2 normalization")
        if query.normalization_sha256 != target.normalization_sha256:
            raise ValueError("alignment requires identical normalization policy identities")
        if any(
            value is None
            for value in (
                query.checkpoint_sha256,
                query.weights_sha256,
                target.checkpoint_sha256,
                target.weights_sha256,
            )
        ):
            raise ValueError("alignment requires both exact exported checkpoint/weights identities")
        if query.model_version != self.text_export_revision:
            raise ValueError("text export revision does not match query descriptor")
        if target.model_version != self.image_export_revision:
            raise ValueError("image export revision does not match target descriptor")
        if query.provenance != self.provenance or target.provenance != self.provenance:
            raise ValueError("alignment provenance cannot promote paired spaces")
        if self.provenance == "observed":
            if self.capability_receipt_sha256 is None:
                raise ValueError(
                    "observed alignment requires an actual capability receipt reference"
                )
        elif self.capability_receipt_sha256 is not None:
            raise ValueError("unobserved alignment cannot carry an observation receipt")
        return self


class CrossModalAlignment(Metadata):
    alignment_id: Digest
    descriptor: CrossModalAlignmentDescriptor

    @classmethod
    def from_descriptor(cls, descriptor: CrossModalAlignmentDescriptor) -> Self:
        descriptor = CrossModalAlignmentDescriptor.model_validate(descriptor)
        return cls(
            alignment_id=_digest("s7-cross-modal-alignment/1", descriptor.model_dump(mode="json")),
            descriptor=descriptor,
        )

    @model_validator(mode="after")
    def exact_alignment_identity(self) -> Self:
        expected = _digest("s7-cross-modal-alignment/1", self.descriptor.model_dump(mode="json"))
        if self.alignment_id != expected:
            raise ValueError("cross-modal alignment descriptor digest mismatch")
        return self


def cosine_aligned(
    query: bytes,
    query_space: FeatureSpace,
    target: bytes,
    target_space: FeatureSpace,
    alignment: CrossModalAlignment,
    *,
    require_observed: bool = True,
) -> float:
    """Cosine only for the explicitly bound ordered pair; no dimension fallback."""
    query_space, target_space = _space(query_space), _space(target_space)
    alignment = CrossModalAlignment.model_validate(alignment)
    bound = alignment.descriptor
    if (
        query_space.feature_space_id != bound.query_space.feature_space_id
        or target_space.feature_space_id != bound.target_space.feature_space_id
    ):
        raise VectorError("spaces do not match ordered alignment")
    _admit_provenance((query_space, target_space), require_observed)
    if require_observed and bound.provenance != "observed":
        raise VectorError("unobserved alignment requires explicit opt-in")
    return _cosine(decode_float32(query, query_space), decode_float32(target, target_space))
