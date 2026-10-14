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
    def inspect(self, missing=(), extras=()):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "package.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                for relative in sorted(distribution.REQUIRED - set(missing)):
                    member = tarfile.TarInfo("screenshot_memory-0.1.0/" + relative)
                    member.size = 1
                    archive.addfile(member, io.BytesIO(b"x"))
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


if __name__ == "__main__":
    unittest.main()
