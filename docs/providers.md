# Offline canonical provider and ledger core

The canonical S3 offline provider/controller and real SQLite ledger are present
under `shared/providers` and `shared/callledger`, with their original MIT notice
and exact source attribution. Their complete public conformance capsule includes
18 schema assets and a supplied synthetic price snapshot. The relocated schema
and snapshot utilities operate only on local supplied data; no price fetching
or account access occurs.

Actual local and detached checks exercise all 232 scenarios collected from the
17 published test files. They cover full-operation allocation, cumulative funds
and attempt ceilings, context/generation identity, ambiguous dispatch liability,
settlement, restart/migration, metadata-only projection, strict replay hit/miss,
no fallback dispatch and injected simulation with the real ledger. All original
test identities are retained. These are authored synthetic cases with mocked or
injected transport and prices. They do not prove live SDK behavior, billing,
native model quality, paid image/token bounds or real capture provenance.

Every `Provider.run` call requires explicit purpose, ledger, budget, context,
limits and allocation. Whole-plan funding must precede attempts. A read-only
allocation observation is not a dispatch lease; the real ledger rechecks during
its transaction. Unknown liabilities remain held, failed attempts remain counted,
and changing run IDs does not reset authority counters. A strict offline lookup
requires a genuinely admitted zero-outbound allocation and explicit zero attempt
limit. An authored synthetic capture remains mock-origin after lookup.

The purpose successor additionally checks each declared child purpose against its
stored child bound, independently of the root operation purpose. Omitting optional
caller limits cannot bypass that stored binding. Valid distinct stage purposes
complete the same admitted operation; an undeclared purpose fails before replay
lookup or transport. Six authored purpose controls accompany the original232
provider/ledger scenarios. The underlying controller/model types stay canonical.

No live OpenAI/TypeSafe SDK, credential loader, hosted caption capability, paid
price/token proof or model access is supplied by this component release. Actual
screening integration must use the canonical APIs and same accounting objects;
the earlier S6 injected gateway tests do not establish that integration. Source
copy and component checks do not complete the S7 application, its retention and
deletion adapters or its native feature evaluation.
