# Screenshot Memory

Import a bounded local collection of PNG/JPEG images, inspect verified decode
metadata, and explicitly delete each managed copy from the implemented stores.
**Current milestone: local construction CLI and an explicit Python OCR adapter.**
The adapter has a bounded two-image native check at the revision documented in
[OCR](docs/ocr.md). CLI OCR/search, captions, embeddings, semantic search, region
display, the API/viewer and evaluation remain unfinished.

## Quickstart

Use Python3.12 linked to SQLite/FTS5 >=3.42; startup probes actual required features.
No models, keys or hosted service are needed for this local workflow. From this
repository in PowerShell, install the pinned tools, then use the source directly:

```powershell
uv sync --frozen --no-install-project --no-build --group dev
$env:PYTHONPATH = "src"
uv run --frozen --no-sync python -m screenshot_memory create --root ../smem-data
```

Use the returned collection ID and an explicitly selected PNG/JPEG:

```powershell
uv run --frozen --no-sync python -m screenshot_memory import --root ../smem-data --collection COLLECTION ./example.png
uv run --frozen --no-sync python -m screenshot_memory inspect --root ../smem-data --collection COLLECTION
uv run --frozen --no-sync python -m screenshot_memory query --root ../smem-data --collection COLLECTION "settings"
uv run --frozen --no-sync python -m screenshot_memory delete --root ../smem-data --collection COLLECTION --item ITEM --confirm
uv run --frozen --no-sync python -m screenshot_memory recover --root ../smem-data --collection COLLECTION
```

`import` reports `imported_partial`: the original copy, actual dimensions/grid hash
and decode provenance are stored; the four model stages are `not_run`. `query`
currently returns `unavailable`, `executed:false`, no hits and exit2; the adapter
does not enable CLI OCR/search.
It never substitutes filenames, fabricated captions or hash vectors for search.
Delete requires `--confirm`; `deleted` requires verified absence from every
implemented store and managed file. Caller-owned source images are preserved.
`recover` explicitly cancels incomplete imports and resumes pending deletions in
the selected collection. It can cancel an in-progress import; stop that importer
first unless cancellation is intended. Nothing scans folders or runs in the background.

## Bounds and persistence

At most30 PNG/JPEG images,8MiB/image,20megapixels/image and100MiB/collection.
Animation, corrupt content, unsafe paths/symlinks and an overflowing batch refuse.
Duplicate bytes get independent opaque IDs and copies, including across collections.
Keep storage outside a repository in an exclusively managed private directory.

SQLite transactions govern admission, generation/revision checks, atomic feature
publication and batch visibility. A process exit during import leaves the whole
batch hidden until explicit recovery. Durable deletion invalidates stale workers,
purges metadata/projections/caches and verifies owned files; failures remain hidden
as `cleanup_pending`. This is logical active-store removal, with no forensic,
backup or external-provider erasure claim. See [storage](docs/storage.md).

## Verification and remaining work

Focused tests use newly generated tiny images and actual SQLite/subprocess crashes.
The legacy `python scripts/demo.py --mock` still shows the empty core status; it is
not the image journey. Tests/schema checks use the frozen developer environment:

```powershell
uv run --offline --frozen --no-sync python -m pytest tests/test_workflow.py tests/storage tests/search
uv run --offline --frozen --no-sync python scripts/generate_schemas.py --check
```

Owned vindex/retrievaleval cores and pinned canonical document, citation, screening,
provider/ledger and evaluation components have separate consumer checks; see
[VENDORED.md](VENDORED.md). A component check does not establish native model or
finished-application integration. The planned architecture remains Python/SQLite
with a React/Vite viewer. No API/listener or cloud resource is created by this CLI.

Quality, latency and cost are **not measured**. Evaluation still exits nonzero;
the frozen reference corpus has not been used for this construction checkpoint.
OCR runtime packaging and independent quality checks, captions, text/image
embeddings, matching regions, browser workflow, distribution rebuilds and
independent finished-application review remain release requirements.
The [source-region resolver](docs/regions.md) has an explicitly injected core and
a concrete bounded Pillow decoder sharing import's policy. Separate checks cover
synthetic decoder controls and real PNG/JPEG decode/storage/deletion with hand-built
OCR artifacts. CLI search and the viewer remain unfinished.
The [local OCR adapter](docs/ocr.md) now supplies source-bound atomic publication
and an explicit lazy CPU backend. Synthetic construction checks and the separate
native two-image execution have distinct evidence. Independent review accepted
the consistency of the attributed native source and receipts; it did not rerun
inference or qualify general OCR quality. The default lock still omits the native
OCR runtime. See the exact revision and remaining limits in the adapter docs.
See [limitations and lessons](docs/LIMITATIONS.md) and [Bolt handoff](BOLT-HANDOFF.md).

Coding agents authored the implementation. Local construction checks support only
the boundaries above; they do not certify the planned application or its quality.
