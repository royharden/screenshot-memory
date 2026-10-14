# Current limitations

This is a local core with strict metadata, SQLite stores/resumable deletion and
pure ranking metric functions. The empty status demo has no integrated fixture
pipeline, OCR, captions, embeddings, retrieval, regions or upload/delete workflow.
Evaluation exits nonzero; quality/latency/cost and held-out results are not measured.

Provisional synthetic references require validated freeze/integration before use.
No provider/SDK/account/model
capability, model licence, checkpoint or vendored source has been verified here.
No viewer/Bolt preview, API listener, container or cloud resource exists.

Metadata validation proves only declared shape and internal consistency; it does
not authenticate source/evidence hashes or provenance receipts. No actual model
checkpoint was loaded. JSON Schema omits cross-field runtime validators; use the
pinned Pydantic models for those invariants. Archive policy checks do not replace
building and checking the actual candidate's detached source distribution.
The new storage and metric sources have detached copied-module consumer checks;
their current wheel/sdist/source-archive rebuild is a separate pending check.
See storage.md for logical deletion scope, OS handle/checkpoint limits, private
root assumptions and the lack of forensic physical-erasure guarantees.

The repository text scanner catches only its named secret shapes and environment
filenames. A passing scan does not guarantee that arbitrary sensitive data is absent.
Its tests include planted positive controls; matching values are never reported.
