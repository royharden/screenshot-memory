# Bolt handoff — local core, application pending

Current inventory: a Python package scaffold, keyless status demo, explicit
unimplemented evaluation entrypoint, strict owned metadata models and generated
JSON Schemas, local SQLite/WAL/FTS stores with an owned SQL migration and resumable
deletion, and pure domain ranking metric helpers. Focused source and detached
copied-module consumer tests cover those cores. No integrated frontend, API,
uploads, model weights, OCR/embedding/caption pipeline or provider integration
exists yet. There is no deployment-ready application artifact.

Database provisioning: not required for the planned local SQLite tool. The future
Python/ONNX/local-filesystem core requires a separately operated runtime; a Vite
fixture preview would not establish OCR/retrieval/deletion functionality. No static
preview has been built at this stage.

Local check: Python3.12; run the README commands. Minimal pytest/Ruff tools are
pinned alongside Pydantic in uv.lock and can use the AGENTS.md cache-only frozen
setup. The new storage/metric candidate needs distribution rebuild verification;
complete detached-source and real-feature acceptance remain separate checks.

Future server secrets by name only: OPENAI_API_KEY and TYPESAFE_API_KEY. Scaffold
loads neither. No browser/public secrets. Hosted processing, import, provisioning,
remote repository and publication actions require their actual configuration/grants.

Future Bolt action: inspect this inventory and implemented source before proposing
an import/provisioning job. Do not deploy the scaffold as a finished application.
