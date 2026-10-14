# Current limitations

This is a scaffold with strict metadata contracts. The empty status demo has no fixture pipeline, OCR,
captions, embeddings, retrieval, regions, persistence, upload or verified deletion.
Evaluation exits nonzero; quality/latency/cost and held-out results are not measured.

No gold/query corpus has been authored or frozen. No provider/SDK/account/model
capability, model licence, checkpoint or vendored source has been verified here.
No viewer/Bolt preview, API listener, container or cloud resource exists.

Metadata validation proves only declared shape and internal consistency; it does
not authenticate source/evidence hashes or provenance receipts. No actual model
checkpoint was loaded. JSON Schema omits cross-field runtime validators; use the
pinned Pydantic models for those invariants. Archive policy checks do not replace
building and checking the actual candidate's detached source distribution.

The repository text scanner catches only its named secret shapes and environment
filenames. A passing scan does not guarantee that arbitrary sensitive data is absent.
Its tests include planted positive controls; matching values are never reported.
