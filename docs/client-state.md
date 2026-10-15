# Client presentation state

The early `web/src/model.ts` module is pure display/workflow logic, without a
React renderer, network, storage or image processing. Its ESM package marker has
no guessed frontend dependency versions. Root Vite commands, React/TypeScript
dependencies/lock, typecheck, built client and browser verification remain owed.

The installed Node24 runtime executes the erasable TypeScript tests directly.
That is actual runtime behavior verification, not TypeScript typechecking. Tests
exercise late-response rejection after query/collection/generation changes,
explicit deletion confirmation and receipt identity, cleanup_pending versus
completed presentation, whole-batch upload guidance and source-pixel display
scaling. Query limits count Unicode codepoints, matching the Python boundary.
Opaque version text is never converted to a floating-point JavaScript counter.

Frontend selection/item/version structures are presentation projections, not new
canonical Item, Pointer, access capability or HTTP schemas. They must be bound by
the future actual API adapter. Client validation cannot establish file format,
decoding safety, actual quota, native feature completeness, relevance, measured
geometry or all-store deletion. Unknown browser MIME proceeds to authoritative
server decode; known unsupported types can be flagged early. Actual upload
admission remains atomic and authoritative in the server.

Display boxes use the actual displayed image rectangle, including its letterbox
offset, with independently calculated source-pixel scaling on both axes. Invalid
or out-of-source geometry refuses rather than being clamped into a plausible
overlay. This performs no evidence resolution or coordinate-frame provenance
validation; the server's canonical Docio/Pointer checks remain required.
