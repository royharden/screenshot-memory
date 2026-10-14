# Bolt handoff — specification only

Current inventory: a Python package scaffold, keyless status demo, explicit
unimplemented evaluation entrypoint, strict owned metadata models and generated
JSON Schemas with tests. These metadata contracts do not process screenshots.
No frontend, API, database implementation, migrations, functions, uploads, model
weights or provider integration exists yet. There is no deployment-ready artifact.

Database provisioning: not required for the planned local SQLite tool. The future
Python/ONNX/local-filesystem core requires a separately operated runtime; a Vite
fixture preview would not establish OCR/retrieval/deletion functionality. No static
preview has been built at this stage.

Local check: Python3.12; run the README commands. Minimal pytest/Ruff tools are
pinned alongside Pydantic in uv.lock and can use the AGENTS.md cache-only frozen
setup. The current metadata candidate still needs distribution rebuild verification;
complete detached-source and real-feature acceptance remain separate checks.

Future server secrets by name only: OPENAI_API_KEY and TYPESAFE_API_KEY. Scaffold
loads neither. No browser/public secrets. Hosted processing, import, provisioning,
remote repository and publication actions require their actual configuration/grants.

Future Bolt action: inspect this inventory and implemented source before proposing
an import/provisioning job. Do not deploy the scaffold as a finished application.
