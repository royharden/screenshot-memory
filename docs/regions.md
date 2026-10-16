# Screenshot source-region binding

`screenshot_memory.regions` supplies a construction-stage resolver for the existing
canonical citation domain (`doc:page:bbox`, `screenshot_collection`, `source_region`).
Importing it installs nothing. The caller explicitly supplies its `Registry`, real
`Store`, trusted `ScreenshotAccess` and bounded `SourceGridDecoder` to
`install_screenshot_resolver`. Neither port has a permissive default.

`PillowSourceGridDecoder()` is an explicit concrete option for the bounded PNG/JPEG
policy already used by import. Both paths now call `image_source.decode_image_bytes`;
the policy digest and processing revision are preserved. Decoding verifies format,
rejects animation, enforces encoded-byte/pixel bounds before pixel allocation, and
returns the encoded RGBA8 axes without EXIF autorotation or ICC transformation.
The resolver recomputes the canonical source-grid digest from those actual pixels.

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
for the canonical document and artifact. The [OCR adapter](ocr.md) publishes those
two rows and the matching stage/item metadata atomically. Producers must use the exact
`processing_revision` and transform-reference helpers rather than inventing an
alternate identity convention. Existing logical deletion covers these content rows.

The original checks join actual SQLite, owned files, canonical contracts and
deletion with anonymous hand-built OCR artifacts and a synthetic RGBA decoder.
A separate Windows/Pillow join imports actual newly generated PNG/JPEG images,
decodes their retained originals with the concrete decoder, checks exact PNG alpha
pixels and preserved JPEG orientation axes, publishes hand-built OCR controls,
resolves them, and verifies all-store deletion and subsequent refusal. Missing OCR
still refuses before those controls are published. These distinct checks do not
prove native OCR, image-query quality, API authorization, browser overlay behavior
or another decoder/platform. The CLI still leaves OCR unexecuted and query
unavailable; it does not expose this resolver as a completed search journey.

Canonical producers remain S2 Docio and S5 cited, vendored as recorded in
[VENDORED.md](../VENDORED.md). This app owns reconciliation. The bounded Pillow
producer is app-owned S7 code consuming canonical S2 grid identities; the resolver
consumes S2 document/evidence and S5 citation contracts. Keep the synthetic controls
as separate tests. A separate pinned two-image native adapter execution asserted
publication, resolution and deletion with real native artifacts; [OCR](ocr.md)
records its source/configuration and narrower worker-assertion evidence. Application
integration still needs real admission, measured occurrence/geometry quality and
deletion through the runnable application. No competing canonical library is
introduced here.
