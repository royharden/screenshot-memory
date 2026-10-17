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

The default lock/environment still provides the decode-only workflow without
separately configured native dependencies and models. The explicit CLI operation
below adds orchestration, with its own controlled synthetic qualification.
The native runtime/model setup is separate from the default lock and remains
unreproduced as a clean installation. Runtime packaging and native CLI qualification,
independent native OCR/geometry and model-rights review, API authorization, browser
integration and development/held-out quality evaluation remain required. No
whole-application, human quality or Bolt acceptance follows from the two-image check.
Reuse canonical S2 Docio and S5 citation contracts as recorded in
[VENDORED.md](../VENDORED.md); this app owns runtime/producer reconciliation.

## Explicit CLI operation

After importing one explicitly selected image into an exclusively managed local
store, select its collection and item. Native use requires the exact dependency
and model edition in `adapters/rapidocr.py`, separately installed and qualified;
the default lock does not provide it. Pass all three local model files:

```powershell
python -m screenshot_memory ocr --root ../smem-data --collection COLLECTION --item ITEM --det-model ./models/det.onnx --cls-model ./models/cls.onnx --rec-model ./models/rec.onnx --timeout 30
python -m screenshot_memory query --root ../smem-data --collection COLLECTION "settings" --mode keyword
```

Missing configuration, dependencies or verified model bytes is an explicit
non-success, never an empty OCR page, downloaded replacement or mock result.
All non-success OCR statuses return exit2. Successful empty observations retain
the canonical blank-page evidence, distinct from missing recognition. Existing
OCR output is immutable; no silent replacement or automatic indexing occurs.

The parent issues one generation token and retains the canonical
`StoreOcrAdapter`, source decode/binding checks and atomic publication. A child
only computes an `EnginePage` from bounded RGBA pixels and explicit model paths;
it receives no store root or item token. The parent validates the nonce/config
and bounded UTF-8 response, closes owned work, then passes observations back to
the adapter. Deletion or a stale generation prevents publication; an interrupted
worker cannot write late rows into the store. SQL publication failures roll back
the canonical transaction. The caller's original image remains untouched.

Worker elapsed time includes startup and pipe transfer: the default is30 seconds,
configurable above0 through120 seconds. Header/reply caps are16KiB/1MiB; decoded
pixels retain the existing20-megapixel cap. The adapter bounds500 lines,5000 words
and512KiB of output. Decode and SQLite work remain parent operations; this is not
a hard real-time guarantee for the entire CLI command or an OS memory sandbox.
Cleanup has its own bounded waits. A cleanup failure refuses publication.

On Windows, the launcher starts suspended and joins a parent-owned
[Job Object](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
before its first instruction. The parent terminates the job and requires verified
zero active members before returning observations. Controlled checks include
startup without a handshake and successful/timeout descendant cleanup.
The code supplies a POSIX process-group route; this new slice's actual process
qualification is on Windows, with POSIX execution still unverified. Neither route
is an OS filesystem/network security sandbox. The CLI assumes the local caller
has filesystem authority over its exclusive store; it does not add a public API.

Controlled tests launch a separate explicitly synthetic worker over generated
images. They exercise text/Unicode and blank publication, keyword lookup,
inspect/confirmed delete, missing configuration/models/items, stale/deleted work,
malformed/oversized/mismatched responses, SQL rollback and actual Windows startup
and descendant cleanup. The controlled engine is injected through a trusted
Python test port; it is not a CLI option or fallback. These tests do not execute
the RapidOCR SDK or inference, certify the new native process route, reproduce a model installation,
or replace the historical source-specific two-image evidence above.
