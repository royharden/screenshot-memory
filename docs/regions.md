# Screenshot source-region binding

`screenshot_memory.regions` supplies a construction-stage resolver for the existing
canonical citation domain (`doc:page:bbox`, `screenshot_collection`, `source_region`).
Importing it installs nothing. The caller explicitly supplies its `Registry`, real
`Store`, trusted `ScreenshotAccess` and bounded `SourceGridDecoder` to
`install_screenshot_resolver`. Neither port has a permissive default.

The access port authenticates the caller and returns a previously issued generation
token. Policy references in a client context are comparison inputs, not authority.
The resolver never obtains a fresh store token to refresh a stale pointer. Admission
is checked before reading the source and again before returning an excerpt.

Within one SQLite write transaction, the binding verifies current visible item and
collection generations, the managed original's identity/bytes/hash, decoded RGBA
grid, decode provenance, and the current OCR stage. It binds the exact retained
canonical document and processing artifact to the screenshot, page index zero,
dimensions, source profile, engine/configuration and transform pair. It then calls
Docio's canonical `validate_evidence(require_measured_spatial=True)` for occurrence,
reading order, exact Unicode excerpt, geometry and enclosure validation. Source
coordinates are not transformed a second time.

`literal_line_pointer` proposes the first case-insensitive literal substring match
in a retained measured/native line. It hashes the entire original line as UTF-8,
without normalizing Unicode. The proposal must pass resolution before display.
Image/caption-only matches, missing boxes and model-claimed boxes produce no line
pointer. A single occurrence preserves its supplied confidence, including null;
multiple occurrences report null rather than an averaged confidence.

Denied, stale, deleted, foreign, tampered or unsupported inputs return canonical
failures without snippets. Generic provenance-receipt references are unsupported
until an actual receipt profile is integrated. The read transaction serializes
with managed deletion; later lookups refuse deleted content. Already returned
caller bytes cannot be recalled. Root isolation and filesystem assumptions remain
those documented in [storage.md](storage.md).

The retained projections use generation-current `content` rows: `DECODE_ROW` for
the existing decode result and app-owned `DOCUMENT_ROW` / `ARTIFACT_ROW` constants
for the canonical document and artifact. A future OCR producer must publish those
two rows and the matching stage/item metadata atomically. It must use the exact
`processing_revision` and transform-reference helpers rather than inventing an
alternate identity convention. Existing logical deletion covers these content rows.

Current checks join actual SQLite, owned files, canonical contracts and deletion
with anonymous hand-built OCR artifacts and a synthetic RGBA decoder. They do not
prove native OCR, decoder qualification, image-query quality, API authorization or
browser overlay behavior. The CLI still leaves OCR unexecuted and query unavailable;
it does not expose this resolver as a completed search journey.

Canonical producers remain S2 Docio and S5 cited, vendored as recorded in
[VENDORED.md](../VENDORED.md). This app owns reconciliation. Replace the synthetic
test decoder/artifacts only when the actual bounded native decoder and OCR producer
are configured and qualified. The affected joined check must then import a real
image, publish native artifacts, resolve its measured occurrence and verify deletion
through the actual application. No competing canonical library is introduced here.
