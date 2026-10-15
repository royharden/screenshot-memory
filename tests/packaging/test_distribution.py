"""Adversarial tiny local archives, independent from any build's observed inventory."""

import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "distribution", ROOT / "scripts/check_distribution.py"
)
distribution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(distribution)


class DistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.approved_bytes = {
            name: (ROOT / name).read_bytes()
            for name in (
                *distribution.SYNTHETIC_FILES,
                *distribution.PROVIDER_FILES,
                distribution.POLICY_FILE,
                distribution.PROVIDER_POLICY_FILE,
            )
        }

    def inspect(self, missing=(), extras=()):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "package.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                for relative in sorted(distribution.REQUIRED - set(missing)):
                    member = tarfile.TarInfo("screenshot_memory-0.1.0/" + relative)
                    data = self.approved_bytes.get(relative, b"x")
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
                for member, data in extras:
                    archive.addfile(member, io.BytesIO(data) if member.isfile() else None)
            return distribution.inspect_archive(path)

    def test_complete_allowed_inventory_is_valid(self):
        result = self.inspect()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["missing_required"], [])

    def test_missing_test_scripts_lock_and_schema_are_not_silently_complete(self):
        for missing in (
            "scripts/demo.py",
            "scripts/eval.py",
            "uv.lock",
            "contracts/generated/Item.schema.json",
            "src/screenshot_memory/shared/vindex/migrations/001_initial.sql",
            "src/screenshot_memory/shared/vindex/migrations/002_unicode_fts.sql",
            "src/screenshot_memory/shared/vindex/search.py",
            "src/screenshot_memory/shared/retrievaleval/metrics.py",
            distribution.POLICY_FILE,
            distribution.PROVIDER_POLICY_FILE,
            "docs/schemas/execution-envelope.schema.json",
            "docs/third-party/providers-LICENSE.md",
            "fixtures/heldout/FROZEN",
            next(name for name in distribution.SYNTHETIC_FILES if name.endswith(".png")),
        ):
            with self.subTest(missing=missing):
                result = self.inspect(missing=(missing,))
                self.assertEqual(result["status"], "invalid")
                self.assertIn(missing, result["missing_required"])

    def test_private_agent_runtime_and_unknown_files_are_rejected(self):
        for name in (
            ".env",
            ".creds/key.txt",
            "planning/receipt.json",
            ".thinking/lane.md",
            "screenshots/user.png",
            "model.onnx",
            "src/screenshot_memory/.env",
            "docs/debug.log",
            "tests/real-user.json",
            "src/screenshot_memory/.creds/key.py",
            "src/screenshot_memory/shared/vindex/migrations/unapproved.sql",
            "fixtures/dev/images/" + "f" * 32 + ".png",
            "fixtures/templates/unapproved.source",
        ):
            with self.subTest(name=name):
                member = tarfile.TarInfo("screenshot_memory-0.1.0/" + name)
                member.size = 1
                self.assertIn("unapproved_file", self.inspect(extras=((member, b"x"),))["issues"])

    def test_links_duplicates_path_escape_and_large_entries_are_rejected(self):
        link = tarfile.TarInfo("screenshot_memory-0.1.0/scripts/link.py")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        duplicate = tarfile.TarInfo("screenshot_memory-0.1.0/scripts/demo.py")
        duplicate.size = 1
        escape = tarfile.TarInfo("screenshot_memory-0.1.0/../scripts/escape.py")
        escape.size = 1
        large = tarfile.TarInfo("screenshot_memory-0.1.0/docs/large.md")
        large.size = 256 * 1024 + 1
        for member, data, issue in (
            (link, b"", "non_regular_member"),
            (duplicate, b"x", "duplicate_member"),
            (escape, b"x", "unsafe_path"),
            (large, b"x" * large.size, "size_limit"),
        ):
            with self.subTest(issue=issue):
                self.assertIn(issue, self.inspect(extras=((member, data),))["issues"])

    def test_unreadable_archive_is_invalid(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.tar.gz"
            path.write_text("not an archive", encoding="utf-8")
            self.assertEqual(distribution.inspect_archive(path)["status"], "invalid")

    def test_approved_image_filename_does_not_authorize_changed_bytes(self):
        name = next(n for n in distribution.SYNTHETIC_FILES if n.endswith(".png"))
        replacement = tarfile.TarInfo("screenshot_memory-0.1.0/" + name)
        replacement.size = 7
        result = self.inspect(missing=(name,), extras=((replacement, b"changed"),))
        self.assertIn("synthetic_hash_mismatch", result["issues"])
        self.assertNotIn(name, result["missing_required"])

    def test_changed_archive_policy_is_rejected_even_at_approved_path(self):
        replacement = tarfile.TarInfo("screenshot_memory-0.1.0/" + distribution.POLICY_FILE)
        replacement.size = 2
        result = self.inspect(missing=(distribution.POLICY_FILE,), extras=((replacement, b"{}"),))
        self.assertIn("policy_hash_mismatch", result["issues"])

    def test_entry_and_aggregate_caps_remain_bounded(self):
        members = []
        for number in range(distribution.MAX_ENTRIES + 1):
            member = tarfile.TarInfo(f"screenshot_memory-0.1.0/scripts/control{number}.py")
            member.size = 1
            members.append((member, b"x"))
        self.assertIn("entry_limit", self.inspect(extras=members)["issues"])
        members = []
        block = b"x" * distribution.MAX_FILE_BYTES
        for number in range(distribution.MAX_TOTAL_BYTES // len(block) + 1):
            member = tarfile.TarInfo(f"screenshot_memory-0.1.0/scripts/aggregate{number}.py")
            member.size = len(block)
            members.append((member, block))
        self.assertIn("size_limit", self.inspect(extras=members)["issues"])

    def test_exact_published_source_and_asset_bytes_cannot_be_replaced(self):
        for name in (
            "src/screenshot_memory/shared/providers/controller.py",
            "docs/schemas/execution-envelope.schema.json",
            "prices/synthetic-unit-v1.json",
        ):
            replacement = tarfile.TarInfo("screenshot_memory-0.1.0/" + name)
            replacement.size = 7
            with self.subTest(name=name):
                result = self.inspect(missing=(name,), extras=((replacement, b"changed"),))
                self.assertIn("provider_hash_mismatch", result["issues"])
                self.assertNotIn(name, result["missing_required"])

    def test_provider_policy_and_unlisted_json_cannot_expand_the_capsule(self):
        policy = distribution.PROVIDER_POLICY_FILE
        replacement = tarfile.TarInfo("screenshot_memory-0.1.0/" + policy)
        replacement.size = 2
        result = self.inspect(missing=(policy,), extras=((replacement, b"{}"),))
        self.assertIn("policy_hash_mismatch", result["issues"])
        for name in ("prices/live-current.json", "docs/schemas/unapproved.json"):
            replacement = tarfile.TarInfo("screenshot_memory-0.1.0/" + name)
            replacement.size = 2
            with self.subTest(name=name):
                self.assertIn(
                    "unapproved_file", self.inspect(extras=((replacement, b"{}"),))["issues"]
                )


if __name__ == "__main__":
    unittest.main()
