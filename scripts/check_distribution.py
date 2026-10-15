"""Inspect a local sdist against a fixed synthetic-data policy; never extract it."""

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath

POLICY_FILE = "scripts/synthetic_distribution.json"
POLICY_SHA256 = "5b40b0419aa84edd6d2d6d34778771c2c75db7b5f8cfaa5efeced761fa1f4477"
MAX_ENTRIES = 512
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024


def synthetic_policy() -> dict[str, dict[str, object]]:
    # Fixed owned policy, not an archive-provided file or arbitrary caller path.
    path = Path(__file__).with_name("synthetic_distribution.json")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("synthetic policy too large")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != POLICY_SHA256:
        raise ValueError("fixed synthetic policy hash mismatch")
    policy = json.loads(raw)
    if policy["schema"] != "S7-original-synthetic-distribution/1":
        raise ValueError("unknown synthetic policy")
    files = policy["files"]
    if len(files) != 202:
        raise ValueError("wrong synthetic policy count")
    for name, entry in files.items():
        if (
            name.startswith("/")
            or "\\" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            or type(entry["bytes"]) is not int
            or not 0 < entry["bytes"] <= MAX_FILE_BYTES
        ):
            raise ValueError("invalid fixed synthetic member")
    return files


SYNTHETIC_FILES = synthetic_policy()

REQUIRED = frozenset(
    {
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "uv.lock",
        "MANIFEST.in",
        ".gitattributes",
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
        "contracts/generated/CrossModalAlignment.schema.json",
        "src/screenshot_memory/shared/vindex/storage.py",
        "src/screenshot_memory/shared/vindex/deletion.py",
        "src/screenshot_memory/shared/vindex/__init__.py",
        "src/screenshot_memory/shared/vindex/spaces.py",
        "src/screenshot_memory/shared/vindex/migrations/001_initial.sql",
        "src/screenshot_memory/shared/retrievaleval/__init__.py",
        "src/screenshot_memory/shared/retrievaleval/metrics.py",
        "tests/eval/test_metrics.py",
        "tests/storage/test_storage_deletion.py",
        "tests/features/test_spaces.py",
        "src/screenshot_memory/shared/docio/__init__.py",
        "src/screenshot_memory/shared/docio/models.py",
        "src/screenshot_memory/shared/docio/identity.py",
        "src/screenshot_memory/shared/docio/interfaces.py",
        "src/screenshot_memory/shared/docio/schema.json",
        "src/screenshot_memory/shared/docio/README.md",
        "docs/third-party/docio-LICENSE.md",
        "tests/docio/test_docio.py",
        "src/screenshot_memory/shared/screen/__init__.py",
        "src/screenshot_memory/shared/screen/models.py",
        "src/screenshot_memory/shared/screen/prepare.py",
        "src/screenshot_memory/shared/screen/questions.py",
        "src/screenshot_memory/shared/screen/rules.py",
        "src/screenshot_memory/shared/screen/typed.py",
        "contracts/vendor/screen/README.md",
        "docs/third-party/screen-LICENSE.md",
        "tests/screen/test_screen.py",
        "tests/screen/test_s7_profile.py",
        POLICY_FILE,
    }
) | frozenset(SYNTHETIC_FILES)
ROOT_FILES = frozenset(
    {
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "uv.lock",
        "MANIFEST.in",
        ".python-version",
        ".gitattributes",
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
    if relative in ROOT_FILES or relative in SYNTHETIC_FILES or relative == POLICY_FILE:
        return True
    if len(parts) == 3 and parts[:2] == ("src", "screenshot_memory.egg-info"):
        return parts[2] in EGG_INFO_FILES
    if parts[:2] == ("src", "screenshot_memory"):
        return relative.endswith(".py") or relative in {
            "src/screenshot_memory/shared/vindex/migrations/001_initial.sql",
            "src/screenshot_memory/shared/docio/schema.json",
            "src/screenshot_memory/shared/docio/README.md",
        }
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
                if count > MAX_ENTRIES:
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
                if relative not in {".python-version", ".gitattributes"} and any(
                    p.startswith(".")
                    or p in {"planning", "agentops", "userdata", "models", "cache"}
                    for p in parts[1:]
                ):
                    issues.append("unapproved_file")
                if member.isdir():
                    continue
                total += member.size
                if member.size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                    issues.append("size_limit")
                    break
                if not relative or not allowed_file(relative):
                    issues.append("unapproved_file")
                expected = (
                    POLICY_SHA256
                    if relative == POLICY_FILE
                    else SYNTHETIC_FILES.get(relative, {}).get("sha256")
                )
                if expected is not None:
                    stream = archive.extractfile(member)
                    payload = b"" if stream is None else stream.read(MAX_FILE_BYTES + 1)
                    if stream is not None:
                        stream.close()
                    if (
                        len(payload) != member.size
                        or hashlib.sha256(payload).hexdigest() != expected
                    ):
                        issues.append(
                            "policy_hash_mismatch"
                            if relative == POLICY_FILE
                            else "synthetic_hash_mismatch"
                        )
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
