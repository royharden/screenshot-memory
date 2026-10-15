# Verified shared-source components

Each component is copied from the exact owner Git commit below. Relative product
imports and original source bytes are retained; consumer-only test namespace and
source-root adaptations are explicit. Original MIT notices are retained under
docs/third-party. These are component conformance results, not native feature,
quality, hosted-account or application acceptance.

| Component | Owner project / commit | Actual supported scope | Notice / provenance |
| --- | --- | --- | --- |
| shared/docio | receipt-field-review / 455d73c6efe283fdf3919267532de7ad5d39924b | Pure canonical models, retained RGBA/artifact identity, ordered text and source-frame/transform checks; no decoder/OCR/Pointer or lifetime implementation | docs/third-party/docio.md and docio-LICENSE.md |
| shared/screen | github-issue-triage / 8f8bb88ffc4148611dd6180b6f01d264c367cce3 | Stdlib whole-input preparation/rules and explicit native offline binding to the same canonical S3 classes; mock/strict replay with synthetic captures only, no live SDK/quality/calibration | docs/third-party/screen.md and screen-LICENSE.md |
| shared/providers + shared/callledger + shared root | llm-router-eval / c7a03a8a5aa91a3881782621d8a5f09c6b82520d | Offline mock/strict replay/injected simulation against real SQLite allocation and accounting; supplied synthetic prices/captures; no SDK or live transport | docs/third-party/providers.md and providers-LICENSE.md |
| shared/cited | changelog-upgrade-advisor / 61c15cd05041c9c9360ff4e727a46f6896dc13c3 | Canonical Pointer models, explicit registry, supplied-text line/section resolver and mandatory evidence accounting; no installed screenshot/source-domain adapter | docs/third-party/cited.md and cited-LICENSE.md |

Runtime: Python3.12, Pydantic2.14.1 and the pinned uv.lock runtime closure. Screen
rules/preparation are stdlib only. Each copied closure has been executed outside
the product checkout with owner-app/model/provider imports and network blocked,
including positive controls for those guards and the component's failure cases.
Actual source/notice digests and schema assets are retained with the component.

S7-owned vindex storage/deletion/vector-space and retrievaleval mathematics are
original local components, not alternative canonical Docio/Pointer/provider
implementations. The supplied-text resolver requires explicit installation;
the S7 screenshot-region resolver and generic evaluation-owner source remain
pending. No production numeric screening thresholds are adopted.
No copied module independently grants source access, survives deleted-generation
checks on behalf of its caller, authenticates provenance references or authorizes
an external action. Actual consumer adapters must establish those obligations.
