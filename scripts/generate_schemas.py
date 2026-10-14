"""Generate S7-owned metadata schemas; cross-field validators remain runtime obligations."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screenshot_memory.contracts import Collection, FeatureSpace, Item, StageStatus  # noqa: E402
from screenshot_memory.shared.vindex.deletion import DeleteReceipt  # noqa: E402


def schema_documents() -> dict[str, str]:
    documents = {}
    for model in (Collection, Item, FeatureSpace, StageStatus, DeleteReceipt):
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$comment"] = (
            "Generated from screenshot_memory.contracts. Runtime validators additionally enforce "
            "cross-field caps, identity/generation and status coherence. "
            "This is no execution proof."
        )
        if model is DeleteReceipt:
            schema["$comment"] = (
                "Generated from screenshot_memory.shared.vindex.deletion. Runtime validators "
                "also enforce completion evidence coherence. A valid declaration alone does "
                "not prove any store or file was deleted."
            )
        documents[f"{model.__name__}.schema.json"] = (
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
    return documents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "contracts" / "generated")
    args = parser.parse_args(argv)
    documents = schema_documents()
    if args.check:
        actual = {p.name for p in args.out.glob("*.schema.json")}
        if actual != set(documents):
            return 1
        return int(
            any(
                (args.out / name).read_text(encoding="utf-8") != data
                for name, data in documents.items()
            )
        )
    args.out.mkdir(parents=True, exist_ok=True)
    for name, data in documents.items():
        (args.out / name).write_text(data, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
