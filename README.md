# Screenshot Memory

Planned: search a bounded local collection of screenshots, inspect the matching
OCR region and verify deletion from every store. **Current state: keyless package
scaffold only.** No screenshot ingestion, OCR, captioning, embeddings, search,
deletion or evaluation is implemented yet.

With Python 3.12, from this directory (no keys, dependencies or model downloads):

```sh
python scripts/demo.py --mock
python -m unittest discover -s tests -v
python scripts/check_secrets.py
```

The demo reports an empty scaffold status with no image/model/retrieval output.
Minimal pytest/Ruff developer tools are pinned in uv.lock; AGENTS.md describes
the cache-only frozen setup. The package itself has not been built or installed.
The future evaluation entrypoint reports not_implemented and exits nonzero:

```sh
python scripts/eval.py --mode mock --split dev
```

The intended architecture is a local Python/SQLite/NumPy core and a React/Vite
viewer. S7 will export vindex, retrievaleval and the region-display/ablation method;
other shared modules require verified owner contracts/source provenance. Draft
local boundaries are under contracts/proposed. No dependencies have been vendored.

Quality, latency and cost are **not yet measured**. There is no labelled corpus or
generated results table. The scaffold makes no API calls and loads no credentials.
See docs/LIMITATIONS.md and BOLT-HANDOFF.md for current gaps.

Codex authored this scaffold. Local checks verify the scaffold boundary only;
they do not establish the planned application's functionality or release acceptance.
