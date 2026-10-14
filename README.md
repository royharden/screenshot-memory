# Screenshot Memory

Planned: search a bounded local collection of screenshots, inspect the matching
OCR region and verify deletion from every store. **Current state: local core.**
Strict metadata, SQLite storage/deletion and pure retrieval metric helpers have
focused tests. Screenshot ingestion, OCR, captioning, embeddings, search,
region viewing and the end-to-end application/evaluation workflow remain pending.

With Python3.12, the empty demo needs no keys or model downloads:

```sh
python scripts/demo.py --mock
python scripts/check_secrets.py
```

The demo reports core availability and an empty preview with no image/model/retrieval output.
Pydantic and pytest/Ruff developer tools are pinned in uv.lock; AGENTS.md describes
the cache-only frozen setup. The full test suite needs that environment:

```sh
uv run --offline --frozen --no-sync python -m pytest
uv run --offline --frozen --no-sync python scripts/generate_schemas.py --check
```

Collection/Item/StageStatus/FeatureSpace validate bounded metadata and internal
identity/status consistency. They perform no source access or model initialization;
valid declared hashes are not verified checkpoint or execution evidence.
See contracts/README.md for the owned schema boundary and digest definitions.
The owned vindex API stores bounded records and managed objects with generation
checks and resumable all-store deletion; see docs/storage.md for exact limits.
Domain recall/hit/full-MRR functions and whole-group metric callbacks are
described in docs/retrieval-metrics.md. They do not execute retrieval methods.
The future evaluation entrypoint reports not_implemented and exits nonzero:

```sh
python scripts/eval.py --mode mock --split dev
```

The intended architecture is a local Python/SQLite/NumPy core and a React/Vite
viewer. S7 will export vindex, retrievaleval and the region-display/ablation method;
other shared modules require verified owner contracts/source provenance. Draft
local metadata boundaries are generated under contracts/generated from the Python
models. No shared-owner dependencies have been vendored.

Quality, latency and cost are **not yet measured**. Provisional synthetic reference
material requires a validated freeze and integration before evaluation; no measured
results table exists. The status demo makes no API calls and loads no credentials.
See docs/LIMITATIONS.md and BOLT-HANDOFF.md for current gaps.

Codex authored this local core. Focused checks verify the documented core boundaries;
they do not establish the planned application's functionality or release acceptance.
