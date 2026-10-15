"""Explicit local construction workflow; no model or provider fallback."""

import argparse
import json
import sqlite3
from pathlib import Path

from pydantic import ValidationError

from screenshot_memory.scaffold import scaffold_status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screenshot Memory (local construction workflow)")
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="Show the implemented scaffold boundary")
    status.add_argument("--json", action="store_true", help="Return a JSON status object")
    for name in ("create", "import", "inspect", "query", "delete", "recover"):
        command = commands.add_parser(name)
        command.add_argument(
            "--root", type=Path, required=True, help="Exclusive private storage root"
        )
        if name != "create":
            command.add_argument("--collection", required=True)
        if name == "import":
            command.add_argument("files", nargs="+", type=Path)
        if name == "inspect":
            command.add_argument("--item")
        if name == "query":
            command.add_argument("text")
        if name == "delete":
            command.add_argument("--item", required=True)
            command.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    if args.command != "status":
        from screenshot_memory.shared.vindex import Deleter, Store, StoreError
        from screenshot_memory.workflow import (
            WorkflowError,
            create_collection,
            import_images,
            inspect_items,
            query,
            recover_imports,
        )

        try:
            if args.command == "delete" and not args.confirm:
                raise WorkflowError("delete_confirmation_required")
            root = args.root.absolute()
            if any((parent / ".git").exists() for parent in (root, *root.parents)):
                raise WorkflowError("storage_inside_repository")
            store = Store(root)
            if args.command == "create":
                result = {"status": "created", "collection_id": create_collection(store)}
            elif args.command == "import":
                items = import_images(store, args.collection, tuple(args.files))
                result = {
                    "status": "imported_partial",
                    "items": [i.model_dump(mode="json") for i in items],
                    "duplicate_policy": "keep_separate",
                    "available": ["decode", "inspect", "verified_delete"],
                    "unavailable": [
                        "ocr",
                        "caption",
                        "text_embeddings",
                        "image_embeddings",
                        "search",
                    ],
                }
            elif args.command == "inspect":
                result = {
                    "status": "ok",
                    "items": [
                        i.model_dump(mode="json")
                        for i in inspect_items(store, args.collection, args.item)
                    ],
                }
            elif args.command == "query":
                result = query(store, args.collection, args.text)
            elif args.command == "delete":
                result = Deleter(store).delete(args.collection, args.item).model_dump(mode="json")
            else:
                receipts = recover_imports(store, args.collection)
                result = {
                    "status": "cleanup_pending"
                    if any(r is None or r.status != "deleted" for r in receipts)
                    else "ok",
                    "receipts": [r.model_dump(mode="json") if r else None for r in receipts],
                }
            print(json.dumps(result, allow_nan=False, sort_keys=True))
            return 2 if result["status"] in {"unavailable", "cleanup_pending", "not_found"} else 0
        except WorkflowError as error:
            print(
                json.dumps(
                    {
                        "status": "refused",
                        "reason": str(error),
                        "cleanup": [
                            r.model_dump(mode="json") if r else None for r in error.cleanup
                        ],
                    },
                    sort_keys=True,
                )
            )
        except StoreError as error:
            print(json.dumps({"status": "refused", "reason": str(error)}, sort_keys=True))
        except (OSError, sqlite3.Error, ValidationError):
            print(json.dumps({"status": "refused", "reason": "local_operation_failed"}))
        return 2
    payload = scaffold_status()
    if args.json:
        print(json.dumps(payload, allow_nan=False, sort_keys=True))
    else:
        print(payload["message"])
    return 0
