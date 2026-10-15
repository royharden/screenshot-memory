# docio: models and pure validation

Implemented: closed Document/Page/Word/Line/Block/ProcessingArtifact wires; separate raw upload,
displayed RGBA8 grid and immutable processing-artifact preimages; inverse affine shape validation;
one engine-to-source box mapping; exact retained-artifact/ordered-ID/Unicode excerpt checks.
SourceEvidence is a neutral producer model. The external tagged Pointer union and resolver registry
are supplied by an adapter, not implemented here.

Copy closure: this directory's `__init__.py`, `models.py`, `identity.py`, `interfaces.py`, `schema.json`
and this README, with the root MIT LICENSE. Python3.12/Pydantic2 are the only runtime requirements.
Imports and validators do not open files, find sources, decode images, run OCR, or contact providers.
Callers supply already-authorized source objects and retained bytes; validation is not access control,
collection lifetime enforcement or permission to retain deleted evidence.

Persisted boxes are source pixels/top-left; page indices are zero-based. Native OCR confidence is
nullable; asserted vision geometry cannot satisfy measured/native spatial requirements. Box-only
references can be structurally valid while measured evidence remains unavailable. Blank recognition
is an explicit successful empty Page, never a failed OCR stage fabricated as blank.

`schema.json` is generated from models. Model shapes alone do not enforce runtime decoder/output/
deadline bounds or establish HEIC/native/OCR capabilities. Decoders, OCR adapters, actual Pointer
adapters, source storage and conformance against real images remain pending.
