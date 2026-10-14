# Repository instructions — v2

This checkout contains product code only. Keep agent plans, reviews, receipts,
registries and chat exports outside this repository. Do not initialize a registry
or copy credentials here. Do not modify another checkout or shared module owner.

## Current implementation

A keyless package scaffold and strict owned metadata contracts exist. OCR, captions, embeddings, persistence,
search, region resolution, upload/delete and evaluation are not implemented.
Collection/Item/StageStatus/FeatureSpace live in src/screenshot_memory/contracts.py;
contracts/generated is derived, and runtime cross-field validators are additionally
required. Valid declared metadata is not verified source/model/execution evidence.
Shared owner contracts require explicit agreed versions before use.

## Commands

Use Python3.12. The empty scaffold commands need no model/provider setup:

    python scripts/demo.py --mock
    python scripts/check_secrets.py

The evaluation entrypoint intentionally returns nonzero until implemented:

    python scripts/eval.py --mode mock --split dev

The committed uv.lock covers Pydantic and minimal developer tools. With an already populated
cache, create the tool environment without building/installing the project:

    uv sync --offline --frozen --no-install-project --no-build --group dev
    uv run --offline --frozen --no-sync ruff check src scripts tests
    uv run --offline --frozen --no-sync ruff format --check src scripts tests
    uv run --offline --frozen --no-sync python -m pytest
    uv run --offline --frozen --no-sync python scripts/generate_schemas.py --check

Project installation/distribution builds and real-feature checks remain separate
setup steps. Missing cache must fail rather than silently download during an offline check.

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

Changelog: v2 records the owned metadata boundary, generated schema source and required
test environment; operating policy/harness pointers unchanged. v1 established the scaffold.
