"""Run the offline scaffold empty state; this is not a pipeline demo yet."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screenshot_memory.scaffold import scaffold_status  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock", action="store_true", required=True)
    parser.parse_args(argv)
    print(json.dumps(scaffold_status(), allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
