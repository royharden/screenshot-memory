"""Inspect a local sdist without extracting it or accessing application sources."""

import argparse
import json
import re
import tarfile
from pathlib import Path, PurePosixPath

REQUIRED = frozenset(
    {
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "uv.lock",
        "MANIFEST.in",
        "src/screenshot_memory/__init__.py",
        "src/screenshot_memory/contracts.py",
        "src/screenshot_memory/cli.py",
        "src/screenshot_memory/scaffold.py",
        "scripts/demo.py",
        "scripts/eval.py",
        "scripts/check_secrets.py",
        "scripts/generate_schemas.py",
        "scripts/check_distribution.py",
        "tests/test_scaffold.py",
        "tests/contracts/test_metadata.py",
        "tests/packaging/test_distribution.py",
        "contracts/README.md",
        "contracts/generated/Collection.schema.json",
        "contracts/generated/Item.schema.json",
        "contracts/generated/FeatureSpace.schema.json",
        "contracts/generated/StageStatus.schema.json",
        "contracts/generated/DeleteReceipt.schema.json",
        "src/screenshot_memory/shared/vindex/storage.py",
        "src/screenshot_memory/shared/vindex/deletion.py",
        "src/screenshot_memory/shared/vindex/__init__.py",
        "src/screenshot_memory/shared/vindex/migrations/001_initial.sql",
    }
)
ROOT_FILES = frozenset(
    {
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "uv.lock",
        "MANIFEST.in",
        ".python-version",
        "BOLT-HANDOFF.md",
        "PKG-INFO",
        "setup.cfg",
    }
)
EGG_INFO_FILES = frozenset(
    {
        "PKG-INFO",
        "SOURCES.txt",
        "dependency_links.txt",
        "entry_points.txt",
        "requires.txt",
        "top_level.txt",
    }
)


def allowed_file(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    if relative in ROOT_FILES:
        return True
    if len(parts) == 3 and parts[:2] == ("src", "screenshot_memory.egg-info"):
        return parts[2] in EGG_INFO_FILES
    if parts[:2] == ("src", "screenshot_memory"):
        return relative.endswith(".py") or relative == (
            "src/screenshot_memory/shared/vindex/migrations/001_initial.sql"
        )
    if parts[0] in {"scripts", "tests"}:
        return relative.endswith(".py")
    if parts[0] == "contracts":
        return relative.endswith((".schema.json", ".md"))
    return parts[0] == "docs" and relative.endswith(".md")


def inspect_archive(path: Path) -> dict[str, object]:
    issues = []
    seen = set()
    files = set()
    roots = set()
    total = 0
    try:
        with tarfile.open(path, "r:*") as archive:
            for count, member in enumerate(archive, 1):
                if count > 200:
                    issues.append("entry_limit")
                    break
                name = member.name
                parts = PurePosixPath(name).parts
                if (
                    len(name) > 256
                    or "\\" in name
                    or not parts
                    or name.startswith("/")
                    or any(p in {".", ".."} for p in name.split("/"))
                ):
                    issues.append("unsafe_path")
                    continue
                roots.add(parts[0])
                if not re.fullmatch(r"screenshot_memory-[0-9][A-Za-z0-9.+_-]{0,63}", parts[0]):
                    issues.append("invalid_root")
                if name in seen:
                    issues.append("duplicate_member")
                seen.add(name)
                if not (member.isfile() or member.isdir()):
                    issues.append("non_regular_member")
                    continue
                relative = "/".join(parts[1:])
                if relative != ".python-version" and any(
                    p.startswith(".")
                    or p in {"planning", "agentops", "userdata", "models", "cache"}
                    for p in parts[1:]
                ):
                    issues.append("unapproved_file")
                if member.isdir():
                    continue
                total += member.size
                if member.size > 256 * 1024 or total > 2 * 1024 * 1024:
                    issues.append("size_limit")
                    break
                if not relative or not allowed_file(relative):
                    issues.append("unapproved_file")
                files.add(relative)
    except (OSError, tarfile.TarError):
        issues.append("unreadable_archive")
    if len(roots) != 1:
        issues.append("root_count")
    missing = sorted(REQUIRED - files)
    if missing:
        issues.append("missing_required")
    return {
        "status": "invalid" if issues else "pass",
        "issues": sorted(set(issues)),
        "files": sorted(files),
        "missing_required": missing,
        "declared_bytes": total,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    result = inspect_archive(args.archive)
    print(json.dumps(result, sort_keys=True))
    return int(result["status"] != "pass")


if __name__ == "__main__":
    raise SystemExit(main())
