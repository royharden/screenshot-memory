"""Keyless status CLI; future commands fail closed until implemented."""

import argparse
import json

from screenshot_memory.scaffold import scaffold_status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screenshot Memory (metadata contracts only)")
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="Show the implemented scaffold boundary")
    status.add_argument("--json", action="store_true", help="Return a JSON status object")
    args = parser.parse_args(argv)
    payload = scaffold_status()
    if args.json:
        print(json.dumps(payload, allow_nan=False, sort_keys=True))
    else:
        print(payload["message"])
    return 0
