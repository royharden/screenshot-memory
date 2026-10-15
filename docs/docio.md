# Canonical source-grid and recognized-artifact core

The unchanged Docio owner component is present under `shared/docio`, with its
source attribution and MIT notice in `docs/third-party`. It supplies strict
Document/Page/Word/Line/Block/ProcessingArtifact models, injected decoder/OCR
ports, exact retained RGBA/grid and artifact identities, inverse affine checks,
source-frame conversion and retained text/geometry validation. It imports no
decoder, OCR SDK, model or provider.

Local checks exercise the actual imported source with synthetic two-pixel grids,
ordered words/lines and exact retained artifacts. They do not establish native
OCR, measured geometry, original-corpus recognition or completed processing.
The SDK adapter must still enforce input/output/time caps and generation fences,
retain the exact source grid and engine artifacts, and bind actual native
engine/weights/config provenance. Nullable OCR confidence remains null.

Owner wire validators are structural checks, not source access, collection
membership, lifetime or deletion enforcement. Callers must validate untrusted
wires through the model's JSON validation entrypoint; constructed/copied model
objects are not a trusted input boundary. Reference validation uses only supplied
documents and retained bytes and never opens a source or resolves a Pointer.

Geometry is source pixels/top-left with zero-based page indices. Engine-frame
boxes must be transformed once using an inverse-checked pair before persistence.
Vision-asserted boxes cannot fulfil measured/native spatial evidence. Genuine
blank OCR is a successful empty page only when actual recognition succeeds;
missing/failed OCR must remain unavailable or failed.

The existing S7 Item raw-source handle is its own version identity. At integration,
the Docio document's raw revision is computed by the canonical `raw_revision`
function and retained separately; do not relabel a different hash as Docio's
identity or create competing Document/Page wires. Actual Pointer/source adapters,
OCR integration and deletion of retained evidence remain pending.
