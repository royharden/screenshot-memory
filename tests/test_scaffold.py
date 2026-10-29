import contextlib
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def script_module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScaffoldTests(unittest.TestCase):
    def run_cli(self, *arguments: str):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
            result = subprocess.run(
                [sys.executable, "-m", "screenshot_memory", *arguments],
                cwd=directory,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(list(Path(directory).iterdir()), [])
            return result

    def test_cli_status_from_another_directory_separates_core_from_pending_workflow(self):
        result = self.run_cli("status", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["stage"], "local_core")
        self.assertTrue(payload["capabilities"]["metadata_contracts"])
        for capability in ("storage_core", "deletion_core", "ranking_metrics"):
            self.assertTrue(payload["capabilities"][capability])
        self.assertEqual(payload["items"], [])
        self.assertFalse(payload["capabilities"]["ocr"])
        self.assertFalse(payload["capabilities"]["delete"])
        self.assertEqual(payload["feature_provenance"], "none")

    def test_unimplemented_mutations_reject_instead_of_succeeding(self):
        for action in ["add", "index"]:
            with self.subTest(action=action):
                result = self.run_cli(action)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid choice", result.stderr)
        # serve is a real command. Missing root and port must reject before listen.
        result = self.run_cli("serve")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--root", result.stderr)
        self.assertIn("--port", result.stderr)

    def test_mock_demo_runs_under_a_network_guard_with_a_positive_control(self):
        demo = script_module("demo")
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            with self.assertRaisesRegex(AssertionError, "network forbidden"):
                socket.create_connection(("example.invalid", 443))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(demo.main(["--mock"]), 0)
        self.assertEqual(json.loads(output.getvalue())["hits"], [])

    def test_live_demo_is_not_an_implicit_fallback(self):
        demo = script_module("demo")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            demo.main(["--live"])
        self.assertNotEqual(error.exception.code, 0)

    def test_unimplemented_eval_is_nonzero_and_has_no_metrics(self):
        evaluate = script_module("eval")
        for mode in ["mock", "recorded", "live"]:
            with self.subTest(mode=mode):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = evaluate.main(["--mode", mode, "--split", "heldout"])
                self.assertNotEqual(code, 0)
                self.assertEqual(json.loads(output.getvalue())["status"], "not_implemented")
                self.assertNotIn("recall", output.getvalue())

    def test_secret_guard_detects_planted_shapes_without_exposing_values(self):
        guard = script_module("check_secrets")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            planted = "sk-" + "A" * 24
            (root / "example.py").write_text(planted, encoding="utf-8")
            findings = guard.scan(root)
            self.assertEqual(findings, [{"path": "example.py", "rule": "provider_key_shape"}])
            self.assertNotIn(planted, json.dumps(findings))

    def test_secret_guard_rejects_env_by_name_and_prunes_private_directories(self):
        guard = script_module("check_secrets")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("private", encoding="utf-8")
            (root / ".env.example").write_text("OPENAI_API_KEY=", encoding="utf-8")
            private = root / ".thinking"
            private.mkdir()
            (private / "private.py").write_text("sk-" + "B" * 24, encoding="utf-8")
            self.assertEqual(
                guard.scan(root), [{"path": ".env", "rule": "private_environment_file"}]
            )


if __name__ == "__main__":
    unittest.main()
