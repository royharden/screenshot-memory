# Bolt handoff — local construction CLI; application pending

Current target is a Python3.12/SQLite local application. No cloud database,
authentication service, buckets, edge functions or provisioning actions are required
for the implemented CLI. No frontend/API listener, Docker resource or deployment
artifact is running. The minimal local viewer uses dependency-free ESM and the
existing TypeScript state helpers, built with the pinned installed Node24.18.0
type stripper. It is not a React/Vite/cloud conversion. This bounded local
implementation preserves the Python/SQLite target and requires separate actual
host/browser qualification; [local viewer](docs/local-viewer.md) records it.

## Implemented inventory

- Guarded direct WSGI collection lifecycle and GET browser admission, plus explicit
  foreground loopback host/viewer source. Public assets carry source/output hashes;
  the host refuses a missing/mismatched build. `/detail` delegates source geometry
  to the canonical resolver; `/render` emits verified source-grid PNG without EXIF
  axis ambiguity. Missing OCR/model stages stay not-run. No actual browser run or
  server/model qualification follows from source or a successful asset build.

- `smem` / `python -m screenshot_memory`: create, explicit bounded PNG/JPEG import,
  inspect, default query-refusal, explicit retained-text keyword queries, confirmed
  delete and collection-scoped recovery.
- Strict metadata schemas; SQLite migrations001→002→003; managed original files;
  atomic generation/revision-checked stage publication; durable batch visibility
  and cancellation/recovery; verified all-store logical deletion.
- Existing domain metrics, FTS/fusion cores, pinned canonical document/citation,
  screening and offline provider/ledger/evaluation components. Their component
  checks are separate from native/whole-app integration.
- Explicit source-region resolver over unchanged canonical document/citation
  contracts, with trusted access and bounded decoder ports. A concrete Pillow
  decoder now shares import's unchanged source-grid policy. Joined tests cover
  real PNG/JPEG decoding/storage/deletion with hand-built OCR controls, separately
  from the original synthetic decoder checks; see [regions](docs/regions.md).
- Canonical OCR adapter source with issued-token source binding and atomic
  document/artifact, word/line and lexical publication. A lazy explicit local
  RapidOCR/ORT backend has a two-image native execution at source revision
  `7a88b39fb7f2f126665b734bfaafeeeee56e3875`. Independent review accepted the
  consistency of its attributed source/receipts without rerunning inference.
  Synthetic construction checks remain separate; see [OCR](docs/ocr.md) for the
  exact scope, persisted results and open quality/runtime gates.

CLI imports report partial with observed decode metadata and four unexecuted model
stages. Default CLI query reports unavailable, not executed, exit2. Explicit
`--mode keyword` reads retained text projections and source-bound empty OCR metadata,
with coverage/status reporting and no image/model execution; see
[keyword queries](docs/keyword-query.md). No fake OCR, filenames-as-
captions, fake embeddings or semantic results are supplied. Caller-owned source
images remain intact after managed-copy deletion. Recovery explicitly cancels an
incomplete import and can cancel a running importer in that collection.

## Setup and checks

Viewer commands: `node web/scripts/build.mjs`, its `--check` counterpart, and the
existing Node state plus new client tests. Node24.18.0 is pinned; no new npm package
or lockfile is required. Python `smem serve --root PRIVATE_ROOT --port OWNED_PORT`
is an explicit local foreground action, not part of Bolt import. It requires a
local in-memory session token and does not print or publish it. Source, build,
direct-call tests and real HTTP/browser observations are separate readiness claims.

See README for commands and storage bounds. Pillow10.4.0 and Pydantic are runtime
requirements in uv.lock. Offline lock checking and frozen cache-only synchronization
were checked against the existing environment, with no acquisition/model action.
Local workflow/storage/search/scaffold checks:147 passed, two Windows link-privilege
skips, six passed subtests. Inputs were new tiny images; real child-process exits
exercise persistence/recovery. Clean-cache setup and distribution rebuilds remain
unverified. Existing failure receipts retain their original scope.

The native check used a separately prepared local runtime and two existing
anonymous PNGs. Its case receipts record readable text and successful blank
output, plus verified deletion from all 14 implemented stores. Query/resolver/stale
predicates were worker assertions with exit 0, without separate result payloads.
This does not add native SDKs/models to uv.lock or reproduce a clean installation.
The qualification stays pinned to the source revision above; later candidates
need their own affected-scope checks. No inference or model acquisition is part
of importing the repository into Bolt.

## Portability and remaining work

Python/ONNX and a private local filesystem need a separately operated runtime;
importing this repository into Bolt does not provision those capabilities. A future
static Vite fixture preview cannot establish native OCR/retrieval/deletion behavior.
No Supabase or replacement backend should be introduced for this local milestone.

Still required: independent OCR/geometry quality and model-rights review, runtime
packaging and CLI OCR/semantic-search wiring, captions, text/image embeddings, retrieval
and application region integration, API/React/browser integration, controlled dev
and held-out evaluation, distributions and independent finished-app review. Quality,
latency and cost are not measured. No frozen corpus/evaluation was run for this
checkpoint; no release/provisioning-ready claim is made.

Future server-only names, when actually configured: OPENAI_API_KEY and
TYPESAFE_API_KEY. This CLI loads neither. No browser/public secrets exist. Actual
provider, model acquisition, remote repository, hosting or publication actions
retain separate authorization/configuration requirements.

## Future Bolt inspection prompt

Inspect this exact repository and BOLT-HANDOFF.md. Target: **no cloud database**;
preserve the local Python/SQLite workflow, schema history and private filesystem.
The ESM viewer is built from public source with Node24.18.0; importing it does not
provision Python, model weights, private storage or an always-running loopback
server. Identify actual runtime/browser/model gaps and prepare only a scoped
inspection report. Do not add Supabase, provision cloud resources, expose the local
API or publish the unfinished application from this inspection.
