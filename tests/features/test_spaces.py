"""Labelled synthetic vector controls; no installed checkpoint or feature inference."""

import hashlib
import json
import math
import struct
import unittest

from pydantic import ValidationError

from screenshot_memory.contracts import FeatureSpace, FeatureSpaceDescriptor, normalization_digest
from screenshot_memory.shared.vindex.spaces import (
    CrossModalAlignment,
    CrossModalAlignmentDescriptor,
    VectorError,
    cosine_aligned,
    cosine_within,
    decode_float32,
    normalize_float32,
)


def space(modality="text", dimensions=4, **updates):
    value = {
        "modality": modality,
        "provenance": "synthetic",
        "model_id": f"synthetic/{modality}",
        "model_version": f"synthetic-{modality}-v1",
        "checkpoint_sha256": "1" * 64,
        "weights_sha256": "2" * 64,
        "implementation_version": "synthetic/1",
        "dimensions": dimensions,
        "preprocessing_id": f"synthetic/{modality}-preprocessor",
        "preprocessing_version": "v1",
        "preprocessing_sha256": "3" * 64,
        "normalization": "l2",
        "normalization_version": "l2/1",
        "normalization_sha256": normalization_digest("l2", "l2/1"),
    }
    if modality == "text":
        value.update(
            tokenizer_id="synthetic/tokenizer",
            tokenizer_version="v1",
            tokenizer_sha256="4" * 64,
            max_input_tokens=77,
        )
    value.update(updates)
    return FeatureSpace.from_descriptor(FeatureSpaceDescriptor.model_validate(value))


def pair(provenance="synthetic", **updates):
    kwargs = {"provenance": provenance}
    if provenance == "observed":
        # Syntactically observed declarations only. These are NOT real receipts.
        kwargs["provenance_receipt_sha256"] = "9" * 64
    query, target = space("text", 512, **kwargs), space("image", 512, **kwargs)
    value = {
        "query_space": query,
        "target_space": target,
        "joint_checkpoint_id": "synthetic/original-joint-clip",
        "joint_checkpoint_sha256": "5" * 64,
        "text_export_revision": query.descriptor.model_version,
        "image_export_revision": target.descriptor.model_version,
        "text_config_sha256": "6" * 64,
        "image_config_sha256": "7" * 64,
        "paired_source_metadata_sha256": "8" * 64,
        "provenance": provenance,
        "capability_receipt_sha256": "a" * 64 if provenance == "observed" else None,
    }
    value.update(updates)
    return CrossModalAlignment.from_descriptor(CrossModalAlignmentDescriptor.model_validate(value))


def unit(dimensions=4, axis=0, sign=1.0):
    return struct.pack(f"<{dimensions}f", *(sign if i == axis else 0.0 for i in range(dimensions)))


class VectorTests(unittest.TestCase):
    def test_exact_little_endian_float32_roundtrip(self):
        self.assertEqual(decode_float32(b"\x00\x00\x80?" + b"\0" * 12, space()), (1, 0, 0, 0))

    def test_explicit_cast_then_normalize(self):
        payload = normalize_float32((3.0, 4.0, 0.0, 0.0), space())
        values = decode_float32(payload, space())
        self.assertAlmostEqual(values[0], 0.6, places=6)
        self.assertAlmostEqual(values[1], 0.8, places=6)
        self.assertAlmostEqual(math.hypot(*values), 1, places=6)

    def test_no_silent_normalization_on_read(self):
        with self.assertRaises(VectorError):
            decode_float32(struct.pack("<4f", 3, 4, 0, 0), space())

    def test_short_long_empty_and_other_buffers_rejected(self):
        for payload in (b"", unit()[:-1], unit() + b"\0", bytearray(unit()), memoryview(unit())):
            with self.subTest(payload_type=type(payload).__name__), self.assertRaises(VectorError):
                decode_float32(payload, space())

    def test_nonfinite_components_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value), self.assertRaises(VectorError):
                decode_float32(struct.pack("<4f", value, 0, 0, 0), space())

    def test_zero_vector_rejected(self):
        with self.assertRaises(VectorError):
            decode_float32(b"\0" * 16, space())

    def test_declared_norm_tolerance_both_sides(self):
        for value in (0.99998, 1.00002):
            with self.subTest(value=value), self.assertRaises(VectorError):
                decode_float32(struct.pack("<4f", value, 0, 0, 0), space())

    def test_float32_drift_within_fixed_tolerance(self):
        self.assertGreater(decode_float32(struct.pack("<4f", 1.000001, 0, 0, 0), space())[0], 1)

    def test_big_endian_payload_not_interpreted_as_native_endian(self):
        with self.assertRaises(VectorError):
            decode_float32(struct.pack(">4f", 1, 0, 0, 0), space())

    def test_normalization_rejects_implicit_integer_and_bool_coercion(self):
        for values in ((1, 0.0, 0.0, 0.0), (True, 0.0, 0.0, 0.0), [1.0, 0.0, 0.0, 0.0]):
            with self.subTest(kind=type(values).__name__), self.assertRaises(VectorError):
                normalize_float32(values, space())

    def test_normalization_dimension_and_nonfinite_rejected(self):
        for values in ((1.0,), (float("nan"), 0.0, 0.0, 0.0), (float("inf"), 0.0, 0.0, 0.0)):
            with self.subTest(values=values), self.assertRaises(VectorError):
                normalize_float32(values, space())

    def test_float32_overflow_and_underflow_rejected(self):
        for values in ((1e300, 0.0, 0.0, 0.0), (1e-300, 0.0, 0.0, 0.0)):
            with self.subTest(values=values), self.assertRaises(VectorError):
                normalize_float32(values, space())

    def test_largest_finite_float32_can_be_explicitly_normalized(self):
        payload = normalize_float32((3.4028234e38, 3.4028234e38, 0.0, 0.0), space())
        self.assertAlmostEqual(math.hypot(*decode_float32(payload, space())), 1, places=6)

    def test_none_normalization_is_readable_but_not_searchable(self):
        plain = space(
            normalization="none", normalization_sha256=normalization_digest("none", "l2/1")
        )
        payload = struct.pack("<4f", 3, 4, 0, 0)
        self.assertEqual(decode_float32(payload, plain)[:2], (3, 4))
        with self.assertRaises(VectorError):
            normalize_float32((3.0, 4.0, 0.0, 0.0), plain)
        with self.assertRaises(VectorError):
            cosine_within(payload, plain, payload, plain, require_observed=False)

    def test_within_cosine_identical_orthogonal_opposite(self):
        value = space()
        for right, expected in ((unit(), 1), (unit(axis=1), 0), (unit(sign=-1.0), -1)):
            with self.subTest(expected=expected):
                self.assertEqual(
                    cosine_within(unit(), value, right, value, require_observed=False), expected
                )

    def test_within_cosine_normalized_hand_computed(self):
        value = space()
        query = normalize_float32((3.0, 4.0, 0.0, 0.0), value)
        self.assertAlmostEqual(
            cosine_within(query, value, unit(), value, require_observed=False), 0.6, places=6
        )

    def test_synthetic_space_rejected_by_default(self):
        with self.assertRaises(VectorError):
            cosine_within(unit(), space(), unit(), space())

    def test_require_observed_not_truthy_coercion(self):
        with self.assertRaises(VectorError):
            cosine_within(unit(), space(), unit(), space(), require_observed=0)

    def test_same_dimension_other_model_or_prefix_rejected(self):
        for other in (space(model_id="synthetic/other"), space(query_prefix="query: ")):
            with self.subTest(other=other.feature_space_id), self.assertRaises(VectorError):
                cosine_within(unit(), space(), unit(), other, require_observed=False)

    def test_changed_preprocessing_tokenizer_weights_rejected(self):
        for updates in (
            {"preprocessing_sha256": "f" * 64},
            {"tokenizer_sha256": "f" * 64},
            {"weights_sha256": "f" * 64},
        ):
            with self.subTest(updates=updates), self.assertRaises(VectorError):
                cosine_within(unit(), space(), unit(), space(**updates), require_observed=False)

    def test_forged_constructed_space_revalidated(self):
        forged = space().model_copy(update={"feature_space_id": "f" * 64})
        with self.assertRaises(ValidationError):
            decode_float32(unit(), forged)
        with self.assertRaises(ValidationError):
            cosine_within(unit(), forged, unit(), forged, require_observed=False)

    def test_observed_metadata_only_does_not_authenticate_receipt(self):
        observed = space(provenance="observed", provenance_receipt_sha256="9" * 64)
        self.assertEqual(cosine_within(unit(), observed, unit(), observed), 1)
        # Deliberately fake opaque digest is structurally accepted; external admission is mandatory.
        self.assertEqual(observed.descriptor.provenance_receipt_sha256, "9" * 64)


class AlignmentTests(unittest.TestCase):
    def test_synthetic_ordered_pair_and_strict_old_compatibility(self):
        alignment = pair()
        query, target = alignment.descriptor.query_space, alignment.descriptor.target_space
        self.assertFalse(query.compatible_with(target))
        self.assertEqual(
            cosine_aligned(unit(512), query, unit(512), target, alignment, require_observed=False),
            1,
        )
        with self.assertRaises(VectorError):
            cosine_within(unit(512), query, unit(512), target, require_observed=False)

    def test_alignment_digest_exact_full_canon_domain(self):
        alignment = pair()
        raw = json.dumps(
            alignment.descriptor.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        self.assertEqual(
            alignment.alignment_id,
            hashlib.sha256(b"s7-cross-modal-alignment/1\n" + raw).hexdigest(),
        )

    def test_alignment_roundtrip_json(self):
        alignment = pair()
        self.assertEqual(
            CrossModalAlignment.model_validate_json(alignment.model_dump_json()), alignment
        )

    def test_pair_reversal_rejected(self):
        alignment = pair()
        with self.assertRaises(VectorError):
            cosine_aligned(
                unit(512),
                alignment.descriptor.target_space,
                unit(512),
                alignment.descriptor.query_space,
                alignment,
                require_observed=False,
            )

    def test_image_query_or_text_target_descriptor_rejected(self):
        alignment = pair()
        for updates in ({"query_space": space("image", 512)}, {"target_space": space("text", 512)}):
            data = alignment.descriptor.model_dump()
            data.update(updates)
            with self.subTest(updates=tuple(updates)), self.assertRaises(ValidationError):
                CrossModalAlignmentDescriptor.model_validate(data)

    def test_other_dimension_rejected(self):
        for updates in (
            {"query_space": space("text", 384)},
            {"target_space": space("image", 384)},
            {"dimensions": 384},
            {"dimensions": True},
        ):
            with self.subTest(updates=tuple(updates)), self.assertRaises(ValidationError):
                pair(**updates)

    def test_revision_mismatch_rejected(self):
        for key in ("text_export_revision", "image_export_revision"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                pair(**{key: "wrong"})

    def test_normalization_policy_mismatch_rejected(self):
        target = space(
            "image",
            512,
            normalization_version="l2/2",
            normalization_sha256=normalization_digest("l2", "l2/2"),
        )
        with self.assertRaises(ValidationError):
            pair(target_space=target)

    def test_normalization_none_rejected(self):
        target = space(
            "image",
            512,
            normalization="none",
            normalization_sha256=normalization_digest("none", "l2/1"),
        )
        with self.assertRaises(ValidationError):
            pair(target_space=target)

    def test_missing_checkpoint_or_weights_rejected_even_synthetic(self):
        for key in ("checkpoint_sha256", "weights_sha256"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                pair(query_space=space("text", 512, **{key: None}))

    def test_foreign_same_dimension_target_rejected(self):
        alignment = pair()
        with self.assertRaises(VectorError):
            cosine_aligned(
                unit(512),
                alignment.descriptor.query_space,
                unit(512),
                space("image", 512, model_id="synthetic/unrelated"),
                alignment,
                require_observed=False,
            )

    def test_changed_query_prefix_and_target_preprocessor_rejected(self):
        alignment = pair()
        query, target = alignment.descriptor.query_space, alignment.descriptor.target_space
        for left, right in (
            (space("text", 512, query_prefix="changed"), target),
            (query, space("image", 512, preprocessing_sha256="f" * 64)),
        ):
            with self.subTest(query=left.feature_space_id), self.assertRaises(VectorError):
                cosine_aligned(unit(512), left, unit(512), right, alignment, require_observed=False)

    def test_synthetic_and_declared_not_observed_by_default(self):
        for provenance in ("synthetic", "declared"):
            alignment = pair(provenance)
            with self.subTest(provenance=provenance), self.assertRaises(VectorError):
                cosine_aligned(
                    unit(512),
                    alignment.descriptor.query_space,
                    unit(512),
                    alignment.descriptor.target_space,
                    alignment,
                )

    def test_observed_alignment_cannot_promote_synthetic_spaces(self):
        with self.assertRaises(ValidationError):
            pair(provenance="observed", query_space=space("text", 512))

    def test_observed_requires_receipt_and_unobserved_forbids_one(self):
        for provenance, receipt in (
            ("observed", None),
            ("synthetic", "a" * 64),
            ("declared", "a" * 64),
        ):
            with self.subTest(provenance=provenance), self.assertRaises(ValidationError):
                pair(provenance, capability_receipt_sha256=receipt)

    def test_syntactically_observed_pair_not_real_capability_proof(self):
        alignment = pair("observed")
        self.assertEqual(
            cosine_aligned(
                unit(512),
                alignment.descriptor.query_space,
                unit(512),
                alignment.descriptor.target_space,
                alignment,
            ),
            1,
        )
        self.assertEqual(alignment.descriptor.capability_receipt_sha256, "a" * 64)

    def test_forged_alignment_digest_and_nested_space_rejected(self):
        alignment = pair()
        query, target = alignment.descriptor.query_space, alignment.descriptor.target_space
        for forged in (
            alignment.model_copy(update={"alignment_id": "f" * 64}),
            alignment.model_copy(
                update={
                    "descriptor": alignment.descriptor.model_copy(
                        update={
                            "query_space": query.model_copy(update={"feature_space_id": "f" * 64})
                        }
                    )
                }
            ),
        ):
            with self.subTest(alignment=forged.alignment_id), self.assertRaises(ValidationError):
                cosine_aligned(unit(512), query, unit(512), target, forged, require_observed=False)

    def test_nonfinite_zero_wrong_length_vectors_rejected(self):
        alignment = pair()
        query, target = alignment.descriptor.query_space, alignment.descriptor.target_space
        for payload in (b"\0" * 2048, struct.pack("<512f", float("nan"), *([0] * 511)), unit(4)):
            with self.subTest(length=len(payload)), self.assertRaises(VectorError):
                cosine_aligned(payload, query, unit(512), target, alignment, require_observed=False)

    def test_all_source_and_export_identity_changes_change_alignment_id(self):
        original = pair()
        for key in (
            "joint_checkpoint_sha256",
            "text_config_sha256",
            "image_config_sha256",
            "paired_source_metadata_sha256",
        ):
            with self.subTest(key=key):
                self.assertNotEqual(original.alignment_id, pair(**{key: "f" * 64}).alignment_id)
