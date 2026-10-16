"""S7 retained OCR row and processing identities, without decoder initialization."""

import hashlib

from screenshot_memory.shared.docio.identity import canonical_bytes
from screenshot_memory.shared.docio.models import ProcessingArtifact

DECODE_ROW = hashlib.sha256(b"decode-source/1").hexdigest()[:32]
DOCUMENT_ROW = hashlib.sha256(b"s7-docio-document/1").hexdigest()[:32]
ARTIFACT_ROW = hashlib.sha256(b"s7-docio-artifact/1").hexdigest()[:32]


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
    return (
        "s7docio/1:"
        + hashlib.sha256(canonical_bytes({key: data[key] for key in fields})).hexdigest()
    )
