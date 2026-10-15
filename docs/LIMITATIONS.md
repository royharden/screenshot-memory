# Current limitations

Development is paused as of 2026-10-15. The application is not ready for release.

## Finished local components

- Strict metadata contracts, generated schemas and float32 feature-space and
  ordered cross-modal alignment validation.
- SQLite capability checks, transactional migrations, bounded managed objects,
  generation-checked access and resumable verified logical deletion.
- Atomic initial metadata batch admission with quota and concurrent-writer
  controls. This does not make original-file writes or feature publication atomic.
- Current-visible-row FTS keyword search, pure BM25/reference fusion helpers,
  ranking metrics and whole-group resampling callbacks.
- Pinned canonical document/evidence, citation, offline screening, provider/ledger
  and evaluation components with focused and detached consumer checks.
- A data-only synthetic reference freeze and portable fixture verification.
- Pure TypeScript client state for request epochs, deletion state and display
  coordinate mapping. This has Node execution checks, not a browser renderer or
  frontend build.

The last completed source batch passed 140 tests with one Windows symlink
privilege skip. Earlier component checks have separate scopes; their totals are
not an integrated application acceptance result.

## Work in progress

Atomic feature-stage publication and the screenshot evidence resolver were
designed but have no product implementation. The intended stage publication
checks both metadata revision and generation, commits projections with metadata,
and prevents a stale producer from publishing after deletion. The proposed MVP
keeps completed output immutable until explicit deletion and re-import.

Dependency archives and selected source notices were inspected outside the
product tree. The acquired RapidOCR archive contains three model weights; they
remain uninstalled and unused. No native SDK import, model construction, native
OCR/embedding execution or provider request has been verified. A combined cached
dependency installation/import probe remains preparation work, not an executed
runtime check.

## Outstanding work

1. Implement and verify atomic stage publication, then the smallest actual local
   image import, inspect and verified-delete workflow with bounded image decoding.
2. Implement current-source screenshot evidence resolution using measured OCR
   geometry and the canonical evidence validator.
3. Complete the native runtime/config/model closure and native OCR, caption,
   text/image embedding and retrieval integration. Preserve explicit unsupported
   or unavailable results rather than substituting synthetic output.
4. Connect the API and React/Vite viewer, verify browser behavior and deletion
   through the actual application, and update the runnable demo.
5. Lock experiment inputs, run development evaluation and the separately locked
   held-out evaluation, rebuild/check distributions, and complete independent
   finished-application review. Quality, latency and cost remain unmeasured.

## Lessons learned

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

This is a local core with strict metadata, SQLite stores/resumable deletion and
pure ranking metric functions. The empty status demo has no integrated fixture
pipeline, OCR, captions, embeddings, retrieval, regions or upload/delete workflow.
Evaluation exits nonzero; quality/latency/cost and held-out results are not measured.

Original synthetic references now have a first data-only freeze, with no original-
gallery feature/tuning/benchmark output in that operation. Integration and actual
model/config/experiment locks remain pending; the references remain provisional.
Pinned canonical Docio, offline screen and offline provider/real-ledger source
closures have local and detached consumer checks. Only supplied synthetic price,
capture and transport cases are exercised. Actual SDK/account/model capability,
installed model/checkpoint bytes and live provider integration remain unverified.
No viewer/Bolt preview, API listener, container or cloud resource exists.

Metadata validation proves only declared shape and internal consistency; it does
not authenticate source/evidence hashes or provenance receipts. No actual model
checkpoint was loaded. JSON Schema omits cross-field runtime validators; use the
pinned Pydantic models for those invariants. Archive policy checks do not replace
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
