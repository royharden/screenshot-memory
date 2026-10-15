# Canonical Pointer and supplied-text core

The unchanged S5 cited package provides the canonical tagged Pointer models,
explicit resolver registry, supplied-text memory resolver and mandatory evidence
accounting. Importing the module installs no domain resolvers. A registry starts
empty; a caller must explicitly install the supplied-text resolver and inject
current access and generation policies with reviewed reference identities.

The supported functional domains in this source release are supplied_text line
and section references. Resolution checks exact retained bytes, identity,
revision, namespace, current generation, access decision and literal occurrence
without trimming or silently changing Unicode/case. Unknown/denied access,
stale/foreign source, altered artifacts and invalid windows fail closed. All
Finding evidence is mandatory; unresolved evidence stays counted and can only
downgrade an assessment. Resolution does not establish semantic truth, human
authorship, fresh authorization or an external action grant.

Screenshot, document, repository, catalog, event and metric Pointer variants can
be structurally valid without being runtime-resolvable. Their domains remain
unsupported until actual adapters are installed and tested. In particular, this
copy does not implement the S7 screenshot-collection/source-region resolver,
generation-bound access, actual OCR grounding, source deletion or UI overlays.
Those integrations must use these canonical models and the canonical Docio
retained-artifact checks; no parallel Pointer type is introduced.

The local and detached tests use supplied synthetic text and placeholder wire
identities, including unsupported-domain controls. The helper vectors are not
source access, model output, Gold, human verification or operating permission.
No filesystem/HTTP source discovery, SDK, credential loader or implicit payload
store is present. S7 storage and lifecycle checks remain caller obligations.
