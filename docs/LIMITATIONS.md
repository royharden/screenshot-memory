# Current limitations

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
numeric typed threshold. Its injected gateway tests are separate from actual S3
integration. S3's offline controller does not supply a live driver or paid image
token bound; valid opaque evidence/receipt references do not authenticate sources.
VENDORED.md and the component docs name the supported scopes.

The repository text scanner catches only its named secret shapes and environment
filenames. A passing scan does not guarantee that arbitrary sensitive data is absent.
Its tests include planted positive controls; matching values are never reported.
