"""Own synthetic conformance oracles for unchanged canonical Docio, no native OCR."""

import hashlib
import json
import unittest

from pydantic import ValidationError

from screenshot_memory.shared.docio.identity import (
    artifact_bytes,
    canonical_bytes,
    engine_box_to_source,
    grid_digest,
    grid_preimage,
    raw_revision,
    validate_artifact_bytes,
    validate_evidence,
)
from screenshot_memory.shared.docio.models import (
    AffineTransform,
    BoxPx,
    Document,
    EngineBox,
    Line,
    OcrResult,
    Page,
    ProcessingArtifact,
    Provenance,
    SourceEvidence,
    TransformPair,
    Word,
)


def transforms(scale=1.0):
    return TransformPair(
        source_to_engine=AffineTransform(
            direction="source_to_engine",
            algorithm="synthetic/scale",
            matrix=((scale, 0.0, 0.0), (0.0, scale, 0.0), (0.0, 0.0, 1.0)),
        ),
        engine_to_source=AffineTransform(
            direction="engine_to_source",
            algorithm="synthetic/scale",
            matrix=((1.0 / scale, 0.0, 0.0), (0.0, 1.0 / scale, 0.0), (0.0, 0.0, 1.0)),
        ),
    )


def bundle():
    raw = hashlib.sha256(b"synthetic encoded source").hexdigest()
    revision = raw_revision("synthetic-document", raw)
    transform = transforms()
    words = tuple(
        Word(
            stable_id=f"w{i}",
            text=text,
            bbox_px=BoxPx(x0=float(i * 3), y0=0.0, x1=float(i * 3 + 2), y1=2.0),
            ocr_confidence=None,
            geometry_provenance="measured_ocr",
            source_engine="synthetic/ocr",
            source_engine_version="v1",
        )
        for i, text in enumerate(("Café", "tea"))
    )
    line = Line(
        stable_id="l0",
        text="Café tea",
        bbox_px=BoxPx(x0=0.0, y0=0.0, x1=5.0, y1=2.0),
        ocr_confidence=None,
        geometry_provenance="measured_ocr",
        source_engine="synthetic/ocr",
        source_engine_version="v1",
        ordered_child_ids=("w0", "w1"),
    )
    artifact = ProcessingArtifact(
        document_id="synthetic-document",
        raw_source_revision=revision,
        page_id="synthetic-page",
        page_index=0,
        width_px=8,
        height_px=4,
        page_sha256=grid_digest(8, 4, b"\xff" * 128),
        grid_policy_id="rgba8-source-grid-v1",
        words=words,
        lines=(line,),
        blocks=(),
        artifact_id="synthetic-artifact",
        engine="synthetic/ocr",
        engine_version="v1",
        config_digest="1" * 64,
        source_to_engine=transform.source_to_engine,
        engine_to_source=transform.engine_to_source,
    )
    retained = artifact_bytes(artifact)
    page = Page(
        **{
            key: getattr(artifact, key)
            for key in (
                "document_id",
                "raw_source_revision",
                "page_id",
                "page_index",
                "width_px",
                "height_px",
                "page_sha256",
                "grid_policy_id",
                "words",
                "lines",
                "blocks",
            )
        },
        source_kind="screenshot",
        processing_ref=artifact.artifact_id,
    )
    document = Document(
        document_id=artifact.document_id,
        original_content_sha256=raw,
        raw_source_revision=revision,
        source_kind="screenshot",
        pages=(page,),
        provenance=Provenance(
            producer="synthetic/fixture",
            version="v1",
            config_sha256="2" * 64,
            source_grid_profile="rgba8-source-grid-v1",
        ),
    )
    ref = SourceEvidence(
        document_id=document.document_id,
        original_content_sha256=raw,
        raw_source_revision=revision,
        page_id=page.page_id,
        page_index=0,
        page_sha256=page.page_sha256,
        grid_policy_id=page.grid_policy_id,
        width_px=8,
        height_px=4,
        evidence_artifact_sha256=hashlib.sha256(retained).hexdigest(),
        bbox_px=line.bbox_px,
        word_ids=("w0", "w1"),
        line_ids=("l0",),
        excerpt_sha256=hashlib.sha256("Café tea".encode()).hexdigest(),
        transform_ref=None,
    )
    return document, artifact, retained, ref


class DocioConformanceTests(unittest.TestCase):
    def test_exact_two_pixel_source_grid_oracle(self):
        rgba = bytes((255, 0, 0, 255, 0, 255, 0, 255))
        header = {
            "algorithm": "rgba8-source-grid-v1",
            "width_px": 2,
            "height_px": 1,
            "mode": "RGBA8",
            "row_order": "top-to-bottom",
            "channel_order": "RGBA",
        }
        expected = (
            json.dumps(
                header, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
            + b"\n"
            + rgba
        )
        self.assertEqual(grid_preimage(2, 1, rgba), expected)
        self.assertEqual(grid_digest(2, 1, rgba), hashlib.sha256(expected).hexdigest())

    def test_grid_shape_type_bytes_and_dimension_hash_controls(self):
        for width, height, raw in (
            (True, 1, b"1234"),
            (0, 1, b""),
            (1, 1, b"123"),
            (1, 1, bytearray(b"1234")),
        ):
            with self.subTest(width=width), self.assertRaises(ValueError):
                grid_preimage(width, height, raw)
        self.assertNotEqual(grid_digest(2, 1, b"1" * 8), grid_digest(1, 2, b"1" * 8))

    def test_raw_source_revision_exact_canon_preimage(self):
        raw = "a" * 64
        expected = (
            "docraw/1:"
            + hashlib.sha256(
                canonical_bytes(
                    {"algorithm_version": 1, "document_id": "d", "original_content_sha256": raw}
                )
            ).hexdigest()
        )
        self.assertEqual(raw_revision("d", raw), expected)
        self.assertNotEqual(expected, raw_revision("other", raw))
        with self.assertRaises(ValidationError):
            raw_revision("d", "invalid")

    def test_exact_retained_artifact_and_measured_reference(self):
        document, artifact, retained, ref = bundle()
        self.assertEqual(validate_artifact_bytes(retained, ref.evidence_artifact_sha256), artifact)
        self.assertEqual(
            validate_evidence(ref, document, retained, require_measured_spatial=True), "Café tea"
        )
        self.assertIsNone(artifact.words[0].ocr_confidence)

    def test_retained_integer_number_identity_not_reencoded_as_float(self):
        _, _, retained, _ = bundle()
        data = json.loads(retained)
        data["words"][0]["bbox_px"]["x1"] = 2
        raw = canonical_bytes(data)
        self.assertNotEqual(raw, retained)
        self.assertEqual(
            validate_artifact_bytes(raw, hashlib.sha256(raw).hexdigest()).words[0].bbox_px.x1, 2.0
        )

    def test_modified_and_noncanonical_artifact_bytes_rejected(self):
        _, _, retained, ref = bundle()
        for raw, digest in (
            (retained + b" ", ref.evidence_artifact_sha256),
            (retained + b"\n", hashlib.sha256(retained + b"\n").hexdigest()),
        ):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                validate_artifact_bytes(raw, digest)

    def test_source_revision_and_page_grid_binding_rejected(self):
        document, _, retained, ref = bundle()
        for key, value in (
            ("document_id", "foreign"),
            ("raw_source_revision", "stale"),
            ("page_sha256", "f" * 64),
            ("page_index", 1),
            ("width_px", 9),
            ("evidence_artifact_sha256", "f" * 64),
        ):
            bad = SourceEvidence.model_validate_json(
                ref.model_copy(update={key: value}).model_dump_json()
            )
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_evidence(bad, document, retained)

    def test_wrong_excerpt_unicode_normalization_not_silently_accepted(self):
        document, _, retained, ref = bundle()
        bad = ref.model_copy(
            update={"excerpt_sha256": hashlib.sha256("Cafe\u0301 tea".encode()).hexdigest()}
        )
        with self.assertRaises(ValueError):
            validate_evidence(bad, document, retained)

    def test_foreign_reversed_or_inconsistent_occurrence_ids_rejected(self):
        document, _, retained, ref = bundle()
        for ids in (("foreign",), ("w1", "w0"), ("w0",)):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                validate_evidence(ref.model_copy(update={"word_ids": ids}), document, retained)

    def test_contradictory_region_enclosure_rejected(self):
        document, _, retained, ref = bundle()
        with self.assertRaises(ValueError):
            validate_evidence(
                ref.model_copy(update={"bbox_px": BoxPx(x0=0.0, y0=0.0, x1=8.0, y1=4.0)}),
                document,
                retained,
            )

    def test_retained_transform_reference_must_resolve_exactly(self):
        document, _, retained, ref = bundle()
        ref = ref.model_copy(update={"transform_ref": "retained-transform"})
        for resolved in (None, {}, {"retained-transform": transforms(2.0)}):
            with self.subTest(resolved=resolved is None), self.assertRaises(ValueError):
                validate_evidence(ref, document, retained, resolved_transforms=resolved)
        self.assertEqual(
            validate_evidence(
                ref, document, retained, resolved_transforms={"retained-transform": transforms()}
            ),
            "Café tea",
        )

    def test_engine_to_source_once_and_bounds(self):
        box = EngineBox(x0=2.0, y0=4.0, x1=6.0, y1=8.0)
        mapped = engine_box_to_source(box, transforms(2.0), 8, 8)
        self.assertEqual((mapped.x0, mapped.y0, mapped.x1, mapped.y1), (1, 2, 3, 4))
        with self.assertRaises(ValueError):
            engine_box_to_source(mapped, transforms(), 8, 8)
        with self.assertRaises(ValueError):
            engine_box_to_source(box, transforms(), 4, 4)

    def test_singular_inverse_nonfinite_and_outside_boxes_rejected(self):
        data = transforms().model_dump()
        data["engine_to_source"]["matrix"] = ((2.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 1.0))
        with self.assertRaises(ValidationError):
            TransformPair.model_validate(data)
        for x in (float("nan"), float("inf"), -1.0):
            with self.subTest(x=x), self.assertRaises(ValidationError):
                BoxPx(x0=x, y0=0.0, x1=1.0, y1=1.0)

    def test_asserted_geometry_cannot_gain_ocr_confidence(self):
        document, _, _, _ = bundle()
        data = document.pages[0].words[0].model_dump()
        data.update(geometry_provenance="model_claimed", ocr_confidence=0.9)
        with self.assertRaises(ValidationError):
            Word.model_validate(data)

    def test_unmeasured_box_only_cannot_pass_measured_spatial(self):
        document, _, retained, ref = bundle()
        ref = ref.model_copy(update={"word_ids": None, "line_ids": None, "excerpt_sha256": None})
        self.assertIsNone(validate_evidence(ref, document, retained))
        with self.assertRaises(ValueError):
            validate_evidence(ref, document, retained, require_measured_spatial=True)

    def test_failed_ocr_not_successful_blank_and_unknown_fields_rejected(self):
        document, _, _, _ = bundle()
        for data in (
            {
                "status": "unavailable",
                "page": document.pages[0],
                "issues": (),
                "capabilities": (),
                "processing_artifact_ref": None,
            },
            {
                "status": "ok",
                "page": None,
                "issues": (),
                "capabilities": (),
                "processing_artifact_ref": None,
            },
        ):
            with self.subTest(status=data["status"]), self.assertRaises(ValidationError):
                OcrResult.model_validate(data)
        with self.assertRaises(ValidationError):
            BoxPx(x0=0.0, y0=0.0, x1=1.0, y1=1.0, unknown=True)

    def test_blank_page_requires_explicit_ok_and_artifact_reference(self):
        _, artifact, _, _ = bundle()
        fields = {
            key: getattr(artifact, key)
            for key in (
                "document_id",
                "raw_source_revision",
                "page_id",
                "page_index",
                "width_px",
                "height_px",
                "page_sha256",
                "grid_policy_id",
            )
        }
        page = Page(
            **fields,
            words=(),
            lines=(),
            blocks=(),
            source_kind="screenshot",
            processing_ref="synthetic-blank-artifact",
        )
        result = OcrResult(
            status="ok",
            page=page,
            issues=(),
            capabilities=("synthetic-only",),
            processing_artifact_ref=page.processing_ref,
        )
        self.assertEqual(result.page.words, ())
        self.assertEqual(result.capabilities, ("synthetic-only",))
