"""Explicitly report that evaluation is not implemented; never emit fake metrics."""

import argparse
import json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["mock", "recorded", "live"], required=True)
    parser.add_argument("--split", choices=["dev", "heldout"], required=True)
    args = parser.parse_args(argv)
    print(json.dumps({"status": "not_implemented", "mode": args.mode, "split": args.split}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
