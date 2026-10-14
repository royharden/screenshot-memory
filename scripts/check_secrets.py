"""Bounded repository-text check. Reports locations/rules, never matching values."""

import json
import os
import re
from pathlib import Path

EXCLUDED = {
    ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules",
    ".smem", ".creds", ".thinking", ".agent-work", ".agent-registry", ".chatexports",
}
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".yaml", ".yml", ".txt", ".mdc"}
RULES = {
    "provider_key_shape": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "github_token_shape": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "private_key_header": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def scan(root: Path) -> list[dict[str, str]]:
    findings = []
    for directory, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name for name in directories
            if name not in EXCLUDED and not (Path(directory) / name).is_symlink()
        )
        for name in sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                continue
            if name.startswith(".env") and name != ".env.example":
                findings.append({"path": relative, "rule": "private_environment_file"})
                continue
            if path.suffix not in TEXT_SUFFIXES and name not in {".env.example", "LICENSE"}:
                continue
            if path.stat().st_size > 1024 * 1024:
                findings.append({"path": relative, "rule": "text_file_over_scan_limit"})
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                findings.append({"path": relative, "rule": "unreadable_text_encoding"})
                continue
            for rule, pattern in RULES.items():
                if pattern.search(text):
                    findings.append({"path": relative, "rule": rule})
    return findings


def main() -> int:
    findings = scan(Path(__file__).resolve().parents[1])
    print(json.dumps({"findings": findings, "scope": "repository text only"}, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
