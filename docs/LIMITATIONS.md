# Current limitations

The local construction CLI is implemented; the application is not ready for release.

## Finished local components

- Strict metadata contracts, generated schemas and float32 feature-space and
  ordered cross-modal alignment validation.
- SQLite capability checks, transactional migrations, bounded managed objects,
  generation-checked access and resumable verified logical deletion.
- Atomic initial metadata batch admission with quota and concurrent-writer
  controls, atomic feature publication and a durable whole-import visibility barrier.
- Current-visible-row FTS keyword search, pure BM25/reference fusion helpers,
  ranking metrics and whole-group resampling callbacks.
- Pinned canonical document/evidence, citation, offline screening, provider/ledger
  and evaluation components with focused and detached consumer checks.
- A data-only synthetic reference freeze and portable fixture verification.
- Pure TypeScript client state for request epochs, deletion state and display
  coordinate mapping. This has Node execution checks, not a browser renderer or
  frontend build.

The local workflow/storage/search/scaffold run reported147 passed, two skipped
for unavailable Windows link privileges, and six passed subtests. Its JUnit file
records155 cases including subtests, zero failures/errors and two skips.
It used newly generated tiny PNG/JPEG inputs and real SQLite/process termination,
not the frozen reference gallery or model output. An earlier run had three failures
(two outdated new-schema expectations and one subprocess timeout); those failures
remain recorded separately. These counts do not establish application acceptance.

## Current local workflow

The CLI creates collections, imports explicit bounded PNG/JPEG files, inspects
actual decode dimensions/grid provenance and verifies confirmed deletion. File
validation precedes admission. Independent opaque originals and decode projections
stage behind a durable batch barrier; the complete batch becomes visible only
after every original and decoded member is verified. Caught staging failure rolls
back through the deletion journal. Abrupt termination leaves every member hidden;
explicit collection-scoped `recover` cancels the incomplete batch and retries
pending cleanup. Quota stays reserved while cleanup is incomplete. Recovery is an
explicit cancellation operation, including against an in-progress importer.

Selected paths must describe regular files before opening; descriptor and path
identity checks also reject replacement during reading. On POSIX, nonblocking open
prevents a replacement FIFO from waiting for a writer. Windows checks exercise
nonregular-file metadata controls and a real same-byte file replacement. Actual
FIFO subprocess checks require POSIX and are skipped on Windows; this does not
qualify arbitrary device drivers or hostile filesystem races on every platform.

Default CLI query explicitly reports unavailable/not-executed. Explicit
`--mode keyword` reads already retained text and validates empty OCR coverage;
it never runs OCR or loads models. Missing projections remain unavailable or partial.
See [keyword queries](keyword-query.md). This metadata path is not measured semantic
retrieval. Screenshot evidence resolution has an explicit canonical-contract binding with original synthetic
controls and a separate real PNG/JPEG/Pillow decode join using hand-built OCR
artifacts and actual SQLite/files/deletion. The concrete decoder shares import's
unchanged bounded source-grid policy. The separate two-image native adapter check
is described below. API admission, CLI OCR publication, region overlays and other
native decoder/platform combinations remain unverified.
See [regions](regions.md).
The status demo still shows the empty core.

Pillow10.4.0 is a runtime requirement, retaining the existing locked archive/version
hashes. The predecessor's isolated offline resolver-cache failure is preserved.
The reconciled lock passes offline checking and the existing isolated environment
passes cache-only frozen synchronization. This is not a clean-cache install or a
rebuilt wheel/source-distribution claim.

Native dependency archives, model identities and notices are retained outside the
product tree. A separate isolated runtime produced partial native OCR evidence but
ended with a guard-count assertion failure. Its missing counters remain unknown;
a later import-only diagnostic does not retroactively complete that qualification.
The [OCR adapter](ocr.md) has independently reviewed synthetic construction checks
and one attributed native two-image execution at source revision
`7a88b39fb7f2f126665b734bfaafeeeee56e3875`. Its readable and blank case receipts
include verified deletion across all 14 stores. Independent review accepted consistency of
the source/receipts/guard/origin/resource closure without rerunning inference.
Query/resolver/stale predicates are worker assertions without separate payloads.
The exact scope and configuration are recorded in the adapter docs; future source
revisions are not silently qualified by that execution. A preceding import-origin
assertion failure remains failed, with its missing final case receipts preserved
as missing. Native runtime packaging, independent OCR/geometry/model-rights review
and application quality remain open. No embedding or provider qualification follows.

## Outstanding work

1. Independently review the local construction CLI, stage publication, import
   visibility/recovery and verified deletion checkpoint.
2. Integrate application screenshot evidence resolution and independently qualify
   OCR geometry using the canonical evidence validator. The two-image worker's
   issued-access control does not implement production admission.
3. Package the native runtime/model closure and connect CLI OCR/search, caption,
   text/image embedding and retrieval integration. Preserve explicit unsupported
   or unavailable results rather than substituting synthetic output.
4. Connect the API and React/Vite viewer, verify browser behavior and deletion
   through the actual application, and update the runnable demo.
5. Lock experiment inputs, run development evaluation and the separately locked
   held-out evaluation, rebuild/check distributions, and complete independent
   finished-application review. Quality, latency and cost remain unmeasured.

## Lessons learned

- Per-item atomic publication is insufficient for all-or-none import visibility.
  Persist a batch barrier with admission, test actual process exits after file and
  stage writes, and release visibility only in one final validated transaction.
- New stores need deletion positive controls and explicit receipt enumeration;
  a row disappearing through a cascade alone is not a complete verification record.
- Canonical producer models with similar fields remain distinct types. Consumer
  tests need valid positive controls so a wire-type rejection cannot masquerade
  as successful occurrence/geometry validation.
- Guard checks need named event phases and retained denial telemetry. An import
  capability probe may be denied successfully while violating a naive event-count
  assertion; retain the failed edition rather than retroactively calling it passed.
- Resolve both module paths and their allowed roots before a physical containment
  comparison. Interpreter junction aliases can otherwise reject an existing
  in-root standard-library module; preserve the failure and check the corrected
  edition separately.
- Keep attributed execution, independent receipt/source review and independent
  model-quality evaluation distinct. Worker assertions without retained result
  payloads provide a narrower observation than a separately inspectable response.

- Metadata shape, copied-module conformance and mock replay prove different
  boundaries from native execution and finished-application behavior.
- Python version alone does not prove SQLite FTS capabilities. Probe the actual
  linked runtime before creating private storage.
- Keyword corpus membership affects BM25 statistics. Exclude stale, deleting and
  other-collection rows before scoring rather than filtering only the results.
- Treat ephemeral WAL sidecar disappearance as a possible filesystem race while
  continuing to refuse unsafe or replaced objects.
- A short produced ranking must not be padded. Recall uses the full gold set;
  unexecuted outcomes and empty executed outcomes have different meanings.
- Inspect archive contents and exact licenses before installing. A missing
  standalone notice, cached weights and successful source validation each need
  their own explicit record; none establishes an installed, usable model.
- Keep the fixture verifier portable. Historical font-dependent rerendering is a
  separate capability check and cannot establish execution on another platform.
- A wheel cache and an existing environment do not necessarily contain resolver
  metadata needed by a new isolated offline lock operation. Preserve lock failures
  and reconcile the real dependency closure before advertising frozen setup.

This is a local core with strict metadata, SQLite stores/resumable deletion and
pure ranking metric functions. The empty status demo has no integrated fixture
pipeline, OCR, captions, embeddings, retrieval, regions or an integrated application workflow. The separate local CLI supports import/inspect/delete.
Evaluation exits nonzero; quality/latency/cost and held-out results are not measured.

Original synthetic references now have a first data-only freeze, with no original-
gallery feature/tuning/benchmark output in that operation. Integration and actual
model/config/experiment locks remain pending; the references remain provisional.
Pinned canonical Docio, offline screen and offline provider/real-ledger source
closures have local and detached consumer checks. Only supplied synthetic price,
capture and transport cases are exercised for those shared components. The local
OCR backend has only the separate pinned two-image check above; installed provider
models, live account capability and provider integration remain unverified.
No viewer/Bolt preview, API listener, container or cloud resource exists.

Metadata validation proves only declared shape and internal consistency; it does
not authenticate source/evidence hashes or provenance receipts. The pinned OCR
check does not qualify the integrated application or future adapter revisions.
JSON Schema omits cross-field runtime validators; use the pinned Pydantic models
for those invariants. Archive policy checks do not replace
building and checking the actual candidate's detached source distribution.
Storage, metrics, vector/alignment and imported component cores have detached
copied-module consumer checks;
their current wheel/sdist/source-archive rebuild is a separate pending check.
See storage.md for logical deletion scope, OS handle/checkpoint limits, private
root assumptions and the lack of forensic physical-erasure guarantees.

The S6 operating profile remains rules-only with null hazard probabilities and no
numeric typed threshold. The controlled native S6 binding now has combined
detached checks against the same canonical S3 classes and real offline ledger;
legacy injected gateway spies are separately labelled. Only mock/strict replay
with supplied synthetic captures is supported, and atomic current-generation
persistence remains a caller obligation. S3's offline controller supplies no live driver or paid image
token bound; valid opaque evidence/receipt references do not authenticate sources.
VENDORED.md and the component docs name the supported scopes.

The repository text scanner catches only its named secret shapes and environment
filenames. A passing scan does not guarantee that arbitrary sensitive data is absent.
Its tests include planted positive controls; matching values are never reported.
