# Local OCR adapter

`StoreOcrAdapter` implements the unchanged canonical S2 Docio `OcrAdapter` port.
It takes an actual `Store`, a previously issued item generation token, an explicit
source-grid decoder and a trusted engine. It returns canonical `OcrResult`; client
page metadata supplies neither authorization nor a fresh generation token.

The adapter verifies the current immutable decode record, source revision/hash,
dimensions, policy/configuration and actual managed original bytes. It recomputes
the decoded grid before calling the engine. Computation occurs outside a database
write transaction. Publication checks the original generation and item revision,
then commits the canonical document/artifact, word/line rows and literal FTS
projections together. A concurrent deletion or other stage write refuses the
publication. Completed OCR is immutable; reindexing requires explicit deletion
and import into a new item.

Every persisted box is mapped once through Docio's engine-to-source validator.
Text remains the engine's exact Unicode; unknown confidence remains null. A
successful empty detection may produce an empty recognized page. Missing results,
recognition failures, bad geometry, limits and expired output return closed
non-success results without publishing output or snippets. Failed attempts leave
the previous committed state unchanged. The existing deletion protocol covers
all new rows and managed originals; returned caller bytes and native allocator
memory are outside its physical-erasure guarantee.

## Explicit native backend

`RapidOcrEngine(LocalModels(detector, classifier, recognizer))` is lazy. Importing
the module or constructing this configuration loads no SDK/model. Recognition
checks the exact supported local model sizes/hashes and dependency versions.
Verified model bytes are passed directly to CPU-only ORT sessions. Two intra-op
threads, one inter-op thread, disabled spinning and two OpenCV threads are explicit.
Paths are excluded from the processing fingerprint, while model hashes, versions,
source policy, parameters, alpha compositing and session configuration are included.

The supported edition is RapidOCR3.10.0 / ONNX Runtime1.31.0, using the bundled
PP-OCRv6 small detector/recognizer and legacy mobile angle classifier. The exact
identities are in `adapters/rapidocr.py`. The backend binds provided sessions into
one SDK instance, requires its embedded recognition dictionary, and exposes no
visualizer. It supplies no package installer, model discovery or download fallback.
Operators retain the applicable model/source licenses and provenance separately.

The input is RGBA over white, with encoded axes preserved. The SDK returns boxes
in the original input frame; Docio records the explicit identity transform. Word
geometry is SDK CTC alignment output, with no independently measured accuracy
claim. An observed successful detector call distinguishes an empty detection from
an unavailable preprocessing/inference result. Later classifier/recognizer failures
remain failures instead of being reported as blank pages.

Call this backend in an owned worker with a hard process deadline and resource
limits. In-process deadline checks cannot interrupt native code. Transport guard
telemetry must retain event phase/address/stack: SDK dependency imports can make a
denied loopback capability probe. A Python audit hook does not provide OS isolation.

## Current qualification boundary

Construction tests use explicit synthetic engine controls and actual Pillow,
SQLite, atomic publication, FTS, source-region resolution and deletion. Independent
construction review accepted 26 tests with native OCR SDK imports forbidden, plus
an original Unicode/null-confidence and reopened-store control. These output
stages remain labelled synthetic.

On 2026-10-16, source revision
`7a88b39fb7f2f126665b734bfaafeeeee56e3875` completed one bounded native execution
using the explicit backend, a separately prepared local runtime and two existing
anonymous 640x160 PNGs. The persisted case receipts contain:

- Readable image: `LOCAL OCR CHECK`, three words and one line.
- Blank image: successful empty output, zero words and lines.
- Each case: completed deletion, all 14 implemented stores verified empty and one
  managed original verified absent.

The exact worker also asserted atomic document/artifact/word/line/FTS publication,
a `LOCAL` lexical hit and issued line-pointer resolution, then no hit and a stale
pointer after deletion. Those predicates passed with worker exit 0; separate query
and resolver result payloads were not retained. The injected issued-access port
was a trusted qualification control, with production authorization still open.

The recorded processing configuration digest is
`7dbcacffe4319ffc46e4ba1e00ee900fdc89f34b3b231d623c286dfc96dd384b`.
Independent review accepted consistency of the attributed source, complete case
receipts, guard telemetry, resolved import origins and process/resource closure.
The reviewer did not execute models or certify OCR/geometry quality. The execution
and its consistency review apply only to the pinned source/configuration and the
two images. Later code revisions, images, platforms and runtime configurations
need their own affected-scope checks.

The worker retained three positive connection/write/downloader denials and one
denied urllib3 IPv6 import probe. Its global socket/downloader guard hooks are
separate from the backend's instance-local session configuration. Actual SDK
session-constructor inventory, two descendant process identities/command lines
and independent OS I/O tracing/isolation were not captured. Configured model paths
and Python guards cannot fill those gaps. Earlier guard-count and import-origin
assertion failures remain failed editions; missing counters or case receipts
were not reconstructed from the later successful run.

The default lock/environment and CLI still provide the decode-only workflow.
The native runtime/model setup is separate from the default lock and remains
unreproduced as a clean installation. Runtime packaging, CLI OCR/search wiring,
independent native OCR/geometry and model-rights review, API authorization, browser
integration and development/held-out quality evaluation remain required. No
whole-application, human quality or Bolt acceptance follows from the two-image check.
Reuse canonical S2 Docio and S5 citation contracts as recorded in
[VENDORED.md](../VENDORED.md); this app owns runtime/producer reconciliation.
