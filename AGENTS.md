# Repository instructions — v1

This checkout contains product code only. Keep agent plans, reviews, receipts,
registries and chat exports outside this repository. Do not initialize a registry
or copy credentials here. Do not modify another checkout or shared module owner.

## Current implementation

Only a keyless package scaffold exists. OCR, captions, embeddings, persistence,
search, region resolution, upload/delete and evaluation are not implemented.
Boundary JSON schemas under contracts/proposed are proposals, not validated runtime
contracts. Shared owner contracts require explicit agreed versions before use.

## Commands

Use Python 3.12. No dependency installation is needed for the scaffold commands:

    python -m unittest discover -s tests -v
    python scripts/demo.py --mock
    python scripts/check_secrets.py

The evaluation entrypoint intentionally returns nonzero until implemented:

    python scripts/eval.py --mode mock --split dev

Dependency locking, frozen installation, Ruff, pytest and package-build verification
remain pending environment setup. Do not claim those checks passed without receipts.

## Invariants

- Local processing and keyless mock operation are distinct from configured hosted use.
- No automatic fallback from missing real capabilities to fabricated model output.
- No network/model initialization or files written at import or scaffold status time.
- Fixtures/gold must be synthetic or appropriately licensed, authored/frozen before
  feature outputs and held-out tuning. No labelled corpus exists yet.
- Never commit user screenshots, secrets, local environment/data/model caches or logs.
- S7 owns vindex/retrievaleval/embeddings/region resolution; consume other shared
  modules only at verified source commits with provenance and consumer tests.
- Confirmed deletion must eventually verify every owned store; a static preview
  cannot establish backend deletion, OCR or retrieval acceptance.

Changelog: v1 establishes the initial scaffold commands and product boundaries.
