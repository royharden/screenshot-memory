"""Synthetic metadata controls; no screenshots, model weights or query gold."""

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from screenshot_memory.contracts import (
    MAX_COLLECTION_BYTES,
    MAX_COUNTER,
    MAX_IMAGE_BYTES,
    Collection,
    FeatureSpace,
    FeatureSpaceDescriptor,
    Item,
    StageStatus,
    normalization_digest,
)

ROOT = Path(__file__).resolve().parents[2]
STAGES = ("decode", "ocr", "caption", "text_embeddings", "image_embeddings")


def stage(name, status="not_run", **overrides):
    value = {"stage": name, "status": status, "item_generation": 4}
    if status in {"ready", "partial"}:
        value.update(
            processing_revision="synthetic/processing/1",
            result_sha256="d" * 64,
            provenance="synthetic",
        )
        if name.endswith("embeddings"):
            value["feature_space_id"] = "e" * 64
    value.update(overrides)
    return value


def item(ready=False):
    return {
        "item_id": "1" * 32,
        "collection_id": "2" * 32,
        "source_object_id": "3" * 32,
        "original_content_sha256": "a" * 64,
        "raw_source_revision": "owner-opaque/raw/1",
        "revision": 2,
        "generation": 4,
        "collection_generation": 2,
        "encoded_bytes": 2048,
        "width_px": 1200,
        "height_px": 800,
        "state": "ready" if ready else "pending",
        "source_grid_sha256": "b" * 64 if ready else None,
        "evidence_artifact_sha256": "c" * 64 if ready else None,
        "stages": tuple(stage(name, "ready" if ready else "not_run") for name in STAGES),
    }


def descriptor(**updates):
    value = {
        "modality": "text",
        "provenance": "declared",
        "model_id": "declared/model",
        "model_version": "v1",
        "implementation_version": "test/1",
        "dimensions": 384,
        "preprocessing_id": "declared/preprocessor",
        "preprocessing_version": "v1",
        "preprocessing_sha256": "1" * 64,
        "tokenizer_id": "declared/tokenizer",
        "tokenizer_version": "v1",
        "tokenizer_sha256": "2" * 64,
        "max_input_tokens": 256,
        "query_prefix": "query: ",
        "document_prefix": "passage: ",
        "normalization": "l2",
        "normalization_version": "l2/1",
        "normalization_sha256": normalization_digest("l2", "l2/1"),
    }
    value.update(updates)
    return FeatureSpaceDescriptor.model_validate(value)


class CollectionTests(unittest.TestCase):
    def test_valid_caps_inclusive(self):
        value = Collection(
            collection_id="a" * 32,
            generation=MAX_COUNTER,
            item_count=30,
            encoded_bytes=MAX_COLLECTION_BYTES,
        )
        self.assertEqual(value.cap, 30)

    def test_count_bytes_and_empty_consistency(self):
        for fields in (
            {"cap": 31},
            {"cap": 0},
            {"cap": 1, "item_count": 2},
            {"encoded_bytes": MAX_COLLECTION_BYTES + 1},
            {"item_count": 0, "encoded_bytes": 1},
            {"item_count": 1, "encoded_bytes": 0},
            {"item_count": 1, "encoded_bytes": MAX_IMAGE_BYTES + 1},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                Collection.model_validate({"collection_id": "a" * 32, "generation": 0, **fields})

    def test_strict_ids_counters_versions_and_unknown_fields(self):
        for fields in (
            {"collection_id": "A" * 32},
            {"collection_id": "a" * 31},
            {"generation": True},
            {"generation": "4"},
            {"generation": 1.0},
            {"generation": -1},
            {"generation": MAX_COUNTER + 1},
            {"schema_version": True},
            {"schema_version": 1.0},
            {"schema_version": "1"},
            {"gold_targets": []},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                Collection.model_validate({"collection_id": "a" * 32, "generation": 0, **fields})

    def test_frozen_and_revalidated_instances(self):
        value = Collection(collection_id="a" * 32, generation=0)
        with self.assertRaises(ValidationError):
            value.generation = 1
        unsafe_copy = value.model_copy(update={"generation": -1})
        with self.assertRaises(ValidationError):
            Collection.model_validate(unsafe_copy)


class ItemTests(unittest.TestCase):
    def test_collection_scope_and_generation_are_independent_of_item_generation(self):
        value = Item.model_validate(item())
        matching = Collection(collection_id="2" * 32, generation=2)
        self.assertTrue(value.belongs_to(matching))
        self.assertFalse(value.belongs_to(Collection(collection_id="3" * 32, generation=2)))
        self.assertFalse(value.belongs_to(Collection(collection_id="2" * 32, generation=3)))
        with self.assertRaises(ValidationError):
            Item.model_validate({**item(), "collection_generation": True})

    def test_pending_and_ready_json_roundtrip(self):
        for ready in (False, True):
            with self.subTest(ready=ready):
                value = Item.model_validate(item(ready))
                self.assertEqual(Item.model_validate_json(value.model_dump_json()), value)
                self.assertEqual(value.raw_source_revision, "owner-opaque/raw/1")
                self.assertEqual(value.original_content_sha256, "a" * 64)
                self.assertNotEqual(value.revision, value.generation)

    def test_byte_and_pixel_boundaries(self):
        value = item()
        value.update(width_px=4000, height_px=5000, encoded_bytes=MAX_IMAGE_BYTES)
        self.assertEqual(Item.model_validate(value).width_px, 4000)
        for updates in (
            {"height_px": 5001},
            {"width_px": 0},
            {"height_px": -1},
            {"encoded_bytes": MAX_IMAGE_BYTES + 1},
            {"encoded_bytes": 0},
            {"width_px": True},
            {"width_px": "4000"},
            {"height_px": 5000.0},
            {"width_px": float("nan")},
            {"height_px": float("inf")},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                Item.model_validate({**value, **updates})

    def test_owner_refs_are_bounded_opaque_and_no_path_or_gold_field(self):
        for updates in (
            {"source_object_id": "C:/secret.png"},
            {"raw_source_revision": "x" * 257},
            {"original_content_sha256": "g" * 64},
            {"evidence_artifact_sha256": "b" * 64},
            {"source_grid_sha256": "c" * 64},
            {"gold_targets": []},
            {"query": "a runtime user query"},
            {"page": {"text": "foreign"}},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                Item.model_validate({**item(), **updates})

    def test_missing_duplicate_extra_stage_rejected(self):
        original = item()
        for stages in (
            original["stages"][:4],
            original["stages"] + (stage("decode"),),
            tuple(stage("decode") for _ in range(5)),
        ):
            with self.subTest(stages=stages), self.assertRaises(ValidationError):
                Item.model_validate({**original, "stages": stages})

    def test_current_generation_required_and_future_rejected(self):
        for status, generation in (("ready", 3), ("partial", 3), ("running", 3), ("not_run", 5)):
            value = item(True)
            bad = stage("caption", status, item_generation=generation)
            if status == "partial":
                bad["reason"] = "truncated"
            value["stages"] = tuple(bad if s["stage"] == "caption" else s for s in value["stages"])
            with (
                self.subTest(status=status, generation=generation),
                self.assertRaises(ValidationError),
            ):
                Item.model_validate(value)

    def test_partial_failure_missing_and_stale_are_explicit(self):
        for status, reason in (
            ("failed", "processing_failed"),
            ("missing", "dependency_missing"),
            ("blocked", "policy_hold"),
            ("partial", "truncated"),
            ("stale", "generation_mismatch"),
        ):
            value = item(True)
            bad = stage(
                "caption", status, reason=reason, item_generation=3 if status == "stale" else 4
            )
            value["state"] = "partial"
            value["stages"] = tuple(bad if s["stage"] == "caption" else s for s in value["stages"])
            with self.subTest(status=status):
                self.assertEqual(Item.model_validate(value).state, "partial")
                with self.assertRaises(ValidationError):
                    Item.model_validate({**value, "state": "ready"})

    def test_raw_grid_evidence_are_independent_but_bound_to_stage_presence(self):
        value = item(True)
        self.assertEqual(
            len(
                {
                    value[k]
                    for k in (
                        "original_content_sha256",
                        "source_grid_sha256",
                        "evidence_artifact_sha256",
                    )
                }
            ),
            3,
        )
        for key in ("source_grid_sha256", "evidence_artifact_sha256"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                Item.model_validate({**value, key: None})
        no_decode = tuple(stage("decode") if s["stage"] == "decode" else s for s in value["stages"])
        with self.assertRaises(ValidationError):
            Item.model_validate({**value, "source_grid_sha256": None, "stages": no_decode})

    def test_empty_text_leg_may_be_inapplicable_but_required_ocr_may_not(self):
        for name, valid in (
            ("text_embeddings", True),
            ("ocr", False),
            ("caption", False),
            ("image_embeddings", False),
        ):
            value = item(True)
            value["stages"] = tuple(
                stage(name, "not_applicable", reason="not_applicable") if s["stage"] == name else s
                for s in value["stages"]
            )
            if name == "ocr":
                value["evidence_artifact_sha256"] = None
            with self.subTest(name=name):
                if valid:
                    self.assertEqual(Item.model_validate(value).state, "ready")
                else:
                    with self.assertRaises(ValidationError):
                        Item.model_validate(value)

    def test_failed_and_partial_summary_must_match_actual_stages(self):
        for value in (
            {**item(), "state": "failed"},
            {**item(), "state": "partial"},
            {**item(True), "state": "partial"},
            {**item(True), "state": "pending"},
        ):
            with self.subTest(state=value["state"]), self.assertRaises(ValidationError):
                Item.model_validate(value)


class StageTests(unittest.TestCase):
    def test_ready_partial_require_real_output_declarations(self):
        for updates in (
            {"result_sha256": None},
            {"processing_revision": None},
            {"provenance": "declared"},
            {"reason": "timeout"},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                StageStatus.model_validate(stage("ocr", "ready", **updates))
        with self.assertRaises(ValidationError):
            StageStatus.model_validate(stage("ocr", "partial"))

    def test_missing_is_never_a_ready_fallback_or_reusable_output(self):
        valid = stage("caption", "missing", reason="unavailable")
        self.assertEqual(StageStatus.model_validate(valid).provenance, "none")
        for updates in (
            {"result_sha256": "e" * 64},
            {"provenance": "synthetic"},
            {"processing_revision": "v1"},
            {"reason": None},
            {"reason": "truncated"},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                StageStatus.model_validate({**valid, **updates})

    def test_embedding_space_id_and_reason_semantics(self):
        for value in (
            stage("text_embeddings", "ready", feature_space_id=None),
            stage("ocr", "ready", feature_space_id="f" * 64),
            stage("image_embeddings", "not_run", feature_space_id="f" * 64),
            stage("ocr", "stale", reason="timeout"),
            stage("caption", "not_applicable", reason="dependency_missing"),
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                StageStatus.model_validate(value)


class FeatureSpaceTests(unittest.TestCase):
    def test_declared_model_does_not_claim_checkpoint_or_observation(self):
        value = FeatureSpace.from_descriptor(descriptor())
        self.assertEqual(value.descriptor.provenance, "declared")
        self.assertIsNone(value.descriptor.checkpoint_sha256)
        self.assertIsNone(value.descriptor.weights_sha256)
        self.assertIsNone(value.descriptor.provenance_receipt_sha256)
        self.assertEqual(FeatureSpace.model_validate_json(value.model_dump_json()), value)

    def test_identity_has_independent_canonical_preimage_control(self):
        value = FeatureSpace.from_descriptor(descriptor())
        blob = json.dumps(
            value.descriptor.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        expected = hashlib.sha256(b"s7-feature-space/1\n" + blob).hexdigest()
        self.assertEqual(value.feature_space_id, expected)
        self.assertTrue(value.compatible_with(FeatureSpace.from_descriptor(descriptor())))
        with self.assertRaises(ValidationError):
            FeatureSpace(feature_space_id="0" * 64, descriptor=descriptor())

    def test_same_dimensions_are_insufficient_for_compatibility(self):
        value = FeatureSpace.from_descriptor(descriptor())
        changes = (
            {"model_version": "v2"},
            {"checkpoint_sha256": "a" * 64},
            {"weights_sha256": "b" * 64},
            {"preprocessing_sha256": "c" * 64},
            {"preprocessing_version": "v2"},
            {"tokenizer_sha256": "d" * 64},
            {"tokenizer_version": "v2"},
            {"query_prefix": "different: "},
            {"document_prefix": "different: "},
            {"implementation_version": "test/2"},
            {"provenance": "synthetic"},
            {"max_input_tokens": 128},
            {
                "normalization": "none",
                "normalization_version": "none/1",
                "normalization_sha256": normalization_digest("none", "none/1"),
            },
        )
        for change in changes:
            with self.subTest(change=change):
                other = FeatureSpace.from_descriptor(descriptor(**change))
                self.assertEqual(value.descriptor.dimensions, other.descriptor.dimensions)
                self.assertFalse(value.compatible_with(other))

    def test_tampered_descriptor_cannot_reuse_existing_identity(self):
        value = FeatureSpace.from_descriptor(descriptor()).model_dump(mode="json")
        value["descriptor"]["query_prefix"] = "changed: "
        with self.assertRaises(ValidationError):
            FeatureSpace.model_validate_json(json.dumps(value))

    def test_prefix_unicode_and_whitespace_are_not_silently_normalized(self):
        composed = FeatureSpace.from_descriptor(descriptor(query_prefix="é: "))
        decomposed = FeatureSpace.from_descriptor(descriptor(query_prefix="e\u0301: "))
        trimmed = FeatureSpace.from_descriptor(descriptor(query_prefix="é:"))
        self.assertFalse(composed.compatible_with(decomposed))
        self.assertFalse(composed.compatible_with(trimmed))

    def test_dimensions_token_limits_and_prefix_bounds(self):
        self.assertEqual(descriptor(dimensions=16384, max_input_tokens=32768).dimensions, 16384)
        for updates in (
            {"dimensions": 0},
            {"dimensions": 16385},
            {"dimensions": True},
            {"dimensions": "384"},
            {"dimensions": float("nan")},
            {"max_input_tokens": 0},
            {"max_input_tokens": 32769},
            {"query_prefix": "é" * 257},
            {"query_prefix": "\ud800"},
            {"document_prefix": "a" * 513},
        ):
            with self.subTest(updates=repr(updates)), self.assertRaises(ValidationError):
                descriptor(**updates)

    def test_tokenizer_closed_tuple_and_normalization_digest(self):
        for updates in (
            {"tokenizer_sha256": None},
            {"tokenizer_id": None},
            {"max_input_tokens": None},
            {"normalization_sha256": "0" * 64},
            {"normalization": "unitish"},
            {"dtype": "float64"},
            {"gold_targets": []},
            {"model_id": " model "},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                descriptor(**updates)

    def test_observed_provenance_requires_receipt_but_schema_does_not_verify_it(self):
        with self.assertRaises(ValidationError):
            descriptor(provenance="observed")
        with self.assertRaises(ValidationError):
            descriptor(provenance_receipt_sha256="f" * 64)
        value = descriptor(
            provenance="observed",
            provenance_receipt_sha256="f" * 64,
            checkpoint_sha256="a" * 64,
            weights_sha256="b" * 64,
        )
        self.assertEqual(
            value.provenance, "observed"
        )  # Synthetic declaration only, not actual receipt proof.

    def test_image_descriptor_can_explicitly_omit_unused_tokenizer(self):
        value = descriptor(
            modality="image",
            tokenizer_id=None,
            tokenizer_version=None,
            tokenizer_sha256=None,
            max_input_tokens=None,
        )
        self.assertIsNone(value.tokenizer_id)


class SchemaTests(unittest.TestCase):
    def test_generated_schema_closure_is_deterministic_and_drift_detected(self):
        spec = importlib.util.spec_from_file_location(
            "schemas", ROOT / "scripts/generate_schemas.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        documents = module.schema_documents()
        self.assertEqual(
            set(documents),
            {
                "Collection.schema.json",
                "Item.schema.json",
                "FeatureSpace.schema.json",
                "StageStatus.schema.json",
                "DeleteReceipt.schema.json",
                "CrossModalAlignment.schema.json",
            },
        )
        for name, data in documents.items():
            with self.subTest(name=name):
                parsed = json.loads(data)
                self.assertFalse(parsed["additionalProperties"])
                self.assertEqual(parsed["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertNotIn('"gold_targets"', data)
                self.assertEqual(
                    (ROOT / "contracts/generated" / name).read_text(encoding="utf-8"), data
                )
                for definition in parsed.get("$defs", {}).values():
                    if definition.get("type") == "object":
                        self.assertFalse(definition["additionalProperties"])
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.assertEqual(module.main(["--out", str(output)]), 0)
            self.assertEqual(module.main(["--out", str(output), "--check"]), 0)
            (output / "Item.schema.json").write_text("{}", encoding="utf-8")
            self.assertEqual(module.main(["--out", str(output), "--check"]), 1)

    def test_nested_preconstructed_instance_is_revalidated(self):
        bad = StageStatus.model_validate(stage("decode")).model_copy(update={"item_generation": -1})
        value = copy.deepcopy(item())
        value["stages"] = (bad,) + value["stages"][1:]
        with self.assertRaises(ValidationError):
            Item.model_validate(value)


if __name__ == "__main__":
    unittest.main()
