# Offline screening core

The canonical S6 offline screening package is present unchanged under
`shared/screen`. Rules and whole-input preparation operate on complete caller
supplied text, cap both original and normalized UTF8 at 32768 bytes, preserve
separate digests and conservative offset maps, and return neutral holds for
review. Reproduction instructions can require review without being malicious.
Diagnostic notices do not clear a safety hold. This does not screen image pixels.

S7's initial operating profile is rules-only, with null hazard probabilities and
no numeric typed threshold. Its future caller must screen the entire assembled
model-bound OCR/caption/query text after selecting bounded excerpts, with exact
source generation and policy binding. A hold blocks subsequent caption, rerank
or existence-guard calls, while eligible local retrieval may remain available
with a visible degraded reason. A pass is not human approval, an action grant or
proof of source access. Actual application wiring and generation-bound deletion
of caller caches remain pending.

The optional typed interface is present as an unchanged owner port. Tests use
injected gateway/accounting spies. Actual canonical S3 admission, ledger,
whole-operation budget, dispatch identity, capture/replay and Jev integration
are pending. Source declarations or test thresholds do not enable a production
typed profile. Replay remains explicitly unavailable in this published version.

The original owner test file has 61 collected scenarios. Consumer tests retain
them all with only imports and the detached source path adapted. Two separate S7
profile/generation scenarios are labelled as consumer tests. None measures model
quality, calibrated detection, billing, native OCR or a completed application.
