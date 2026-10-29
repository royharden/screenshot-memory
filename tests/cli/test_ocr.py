"""Actual CLI/worker/Pillow/SQLite journey with explicitly synthetic OCR provenance."""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image

from screenshot_memory import ocr_command, workflow
from screenshot_memory.adapters.ocr import EngineIdentity
from screenshot_memory.adapters.rapidocr import LocalModels
from screenshot_memory.cli import main
from screenshot_memory.image_source import GRID_POLICY
from screenshot_memory.ocr_records import DOCUMENT_ROW
from screenshot_memory.shared.docio.models import Document
from screenshot_memory.shared.vindex import Deleter, Store

IDENTITY = EngineIdentity("synthetic-worker-control", "1", "d" * 64, GRID_POLICY, "synthetic")
MODELS = LocalModels(Path("det.onnx"), Path("cls.onnx"), Path("rec.onnx"))
HELPER = Path(__file__).with_name("ocr_worker_control.py")
PROCESS_ENGINE = ocr_command.ProcessOcrEngine
_SRC = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture(autouse=True)
def worker_inherits_pytest_pythonpath(monkeypatch):
    # Pytest adds src for this process only. The worker is a new interpreter.
    src = str(_SRC)
    parts = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    if src not in parts:
        monkeypatch.setenv("PYTHONPATH", os.pathsep.join([src, *parts]))


def setup(tmp_path):
    image = tmp_path / "anonymous.png"
    with Image.new("RGB", (32, 20), "white") as pixels:
        pixels.save(image)
    store = Store(tmp_path / "private")
    cid = workflow.create_collection(store)
    (item,) = workflow.import_images(store, cid, (image,))
    return store, cid, item.item_id, image


def control(monkeypatch, tmp_path, mode="text"):
    instances = []

    def factory(models):
        engine = PROCESS_ENGINE(
            models,
            _identity=IDENTITY,
            _command=(
                sys.executable,
                "-B",
                str(HELPER),
                mode,
                str(tmp_path / "marker"),
                str(tmp_path / "release"),
            ),
        )
        instances.append(engine)
        return engine

    monkeypatch.setattr(ocr_command, "ProcessOcrEngine", factory)
    return instances


def cli(capsys, *args):
    code = main(list(args))
    return code, json.loads(capsys.readouterr().out)


def selected(store, cid, iid):
    return ("--root", str(store.root), "--collection", cid, "--item", iid)


def model_args():
    return ("--det-model", "det.onnx", "--cls-model", "cls.onnx", "--rec-model", "rec.onnx")


def assert_no_ocr(store, cid, iid):
    token = store.token(cid, iid)
    item = store.item(token)
    assert next(s for s in item.stages if s.stage == "ocr").status == "not_run"
    with store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM content").fetchone()[0] == 1
        for table in ("words", "lines", "item_fts", "line_fts"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_explicit_cli_worker_keyword_inspect_and_confirmed_delete(tmp_path, monkeypatch, capsys):
    store, cid, iid, source = setup(tmp_path)
    engines = control(monkeypatch, tmp_path)
    code, output = cli(capsys, "ocr", *selected(store, cid, iid), *model_args())
    assert code == 0 and output["status"] == "ok" and output["executed"] is True, output
    assert "synthetic_ocr" in output["ocr"]["capabilities"]
    assert engines[0].last_worker_closed and engines[0].last_worker_pid
    token = store.token(cid, iid)
    document = Document.model_validate_json(store.get("content", token, DOCUMENT_ROW))
    assert document.pages[0].words[0].ocr_confidence is None
    # Catches locale-default source rewrites and non-UTF8 worker pipe output.
    assert document.pages[0].words[0].text == "Caf" + chr(233)
    code, output = cli(
        capsys, "query", "--root", str(store.root), "--collection", cid, "cafe", "--mode", "keyword"
    )
    assert code == 0 and output["hits"][0]["item_id"] == iid
    code, output = cli(capsys, "inspect", *selected(store, cid, iid))
    assert code == 0 and any(s["provenance"] == "synthetic" for s in output["items"][0]["stages"])
    assert cli(capsys, "delete", *selected(store, cid, iid))[0] == 2
    code, output = cli(capsys, "delete", *selected(store, cid, iid), "--confirm")
    assert code == 0 and output["status"] == "deleted"
    code, output = cli(
        capsys, "query", "--root", str(store.root), "--collection", cid, "cafe", "--mode", "keyword"
    )
    assert code == 0 and output["hits"] == [] and source.exists()


def test_genuine_controlled_blank_publishes_empty_coverage(tmp_path, monkeypatch, capsys):
    store, cid, iid, _ = setup(tmp_path)
    engines = control(monkeypatch, tmp_path, "blank")
    code, output = cli(capsys, "ocr", *selected(store, cid, iid), *model_args())
    assert code == 0 and output["ocr"]["page"]["words"] == []
    assert engines[0].last_worker_closed
    code, output = cli(
        capsys,
        "query",
        "--root",
        str(store.root),
        "--collection",
        cid,
        "absent",
        "--mode",
        "keyword",
    )
    assert code == 0 and output["coverage"]["empty_ocr_items"] == 1


@pytest.mark.parametrize(
    "models",
    [
        (),
        (
            "--det-model",
            "missing",
        ),
        model_args(),
    ],
)
def test_missing_configuration_or_actual_models_never_fabricates_ocr(tmp_path, capsys, models):
    store, cid, iid, _ = setup(tmp_path)
    code, output = cli(capsys, "ocr", *selected(store, cid, iid), *models)
    assert code == 2 and output["status"] in {"refused", "unavailable"}
    assert_no_ocr(store, cid, iid)


@pytest.mark.parametrize("timeout", ["nan", "inf", "0", "-1", "121"])
def test_timeout_bounds_refuse_before_worker(tmp_path, capsys, timeout):
    store, cid, iid, _ = setup(tmp_path)
    code, output = cli(capsys, "ocr", *selected(store, cid, iid), "--timeout", timeout)
    assert code == 2 and output["reason"] == "ocr_timeout_bounds"
    assert_no_ocr(store, cid, iid)


@pytest.mark.parametrize("mode", ["garbage", "oversize", "wrong-nonce"])
def test_untrusted_worker_output_does_not_publish(tmp_path, monkeypatch, capsys, mode):
    store, cid, iid, _ = setup(tmp_path)
    engines = control(monkeypatch, tmp_path, mode)
    assert cli(capsys, "ocr", *selected(store, cid, iid), *model_args())[0] == 2
    assert_no_ocr(store, cid, iid)
    assert engines[0].last_worker_closed


def test_SQL_failure_rolls_back_entire_OCR_publication(tmp_path, monkeypatch, capsys):
    store, cid, iid, _ = setup(tmp_path)
    engines = control(monkeypatch, tmp_path)
    with store.connection() as conn:
        conn.execute(
            "CREATE TRIGGER refuse_line BEFORE INSERT ON lines "
            "BEGIN SELECT RAISE(ABORT, 'synthetic rollback control'); END"
        )
    assert cli(capsys, "ocr", *selected(store, cid, iid), *model_args())[0] == 2
    assert_no_ocr(store, cid, iid)
    assert engines[0].last_worker_closed


def wait_file(path, seconds=20):
    deadline = time.monotonic() + seconds
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.exists(), "controlled worker did not reach its barrier"


def test_delete_during_worker_cannot_resurrect_item(tmp_path, monkeypatch):
    store, cid, iid, source = setup(tmp_path)
    engines = control(monkeypatch, tmp_path, "pause")
    with ThreadPoolExecutor(max_workers=1) as pool:
        # The pause marker is written only after the worker import and pixel read.
        # A 20s wait expired under suite load before that write.
        future = pool.submit(ocr_command.run_ocr, store, cid, iid, MODELS, timeout_s=70)
        wait_file(tmp_path / "marker", seconds=50)
        assert Deleter(Store(store.root)).delete(cid, iid).status == "deleted"
        (tmp_path / "release").write_text("release")
        result = future.result(timeout=20)
    assert result["status"] == "invalid" and not result["executed"]
    assert workflow.inspect_items(Store(store.root), cid) == () and source.exists()
    assert engines[0].last_worker_closed


@pytest.mark.skipif(os.name != "nt", reason="Windows job/descendant qualification")
@pytest.mark.parametrize("mode,expected", [("hang", "timeout"), ("child", "ok")])
def test_owned_worker_and_child_close_on_timeout_or_success(tmp_path, monkeypatch, mode, expected):
    import ctypes
    from ctypes import wintypes as w

    store, cid, iid, _ = setup(tmp_path)
    engines = control(monkeypatch, tmp_path, mode)
    # 10s expired during worker import before the hang/child marker existed.
    # The hang worker still sleeps 120s, so 30s remains a timeout.
    result = ocr_command.run_ocr(store, cid, iid, MODELS, timeout_s=30)
    assert result["status"] == expected and engines[0].last_worker_closed
    pids = json.loads((tmp_path / "marker").read_text())
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    k.CloseHandle.argtypes = [w.HANDLE]
    for pid in pids.values():
        handle = k.OpenProcess(0x100000, False, pid)
        if handle:
            try:
                assert k.WaitForSingleObject(handle, 1000) == 0
            finally:
                k.CloseHandle(handle)
        else:
            assert (
                ctypes.get_last_error() == 87
            )  # PID no longer exists; access denial is not proof.
    if expected == "timeout":
        assert_no_ocr(store, cid, iid)


def test_startup_deadline_closes_owned_bootstrap_without_a_handshake(tmp_path, monkeypatch):
    store, cid, iid, _ = setup(tmp_path)
    engine = PROCESS_ENGINE(
        MODELS,
        _identity=IDENTITY,
        # The venv executable can exit after spawning the real interpreter and
        # close this pipe. The base interpreter is the sleeper that holds stdout.
        _command=(sys._base_executable, "-c", "import time;time.sleep(2)"),
    )
    monkeypatch.setattr(ocr_command, "ProcessOcrEngine", lambda models: engine)
    try:
        # 0.05s expired inside adapter checks before ProcessOcrEngine.recognize,
        # so the owned bootstrap never started and last_worker_closed stayed false.
        result = ocr_command.run_ocr(store, cid, iid, MODELS, timeout_s=1.0)
        assert result["status"] == "timeout" and engine.last_worker_closed
        assert_no_ocr(store, cid, iid)
    finally:
        # The pre-repair bootstrap is intentionally finite even without a job.
        time.sleep(2.5)


@pytest.mark.parametrize("iid", ["not-an-id", "f" * 32])
def test_wrong_or_missing_item_refuses_before_worker(tmp_path, monkeypatch, capsys, iid):
    store, cid, original, _ = setup(tmp_path)

    def forbidden(models):
        raise AssertionError("invalid selected item reached worker construction")

    monkeypatch.setattr(ocr_command, "ProcessOcrEngine", forbidden)
    assert cli(capsys, "ocr", *selected(store, cid, iid), *model_args())[0] == 2
    assert_no_ocr(store, cid, original)


@pytest.mark.skipif(os.name != "nt", reason="actual Windows suspended-launch custody regression")
@pytest.mark.parametrize(
    "failure", ["reader", "writer", "thread-constructor", "assignment", "resume", "cancel"]
)
def test_startup_fault_closes_actual_retained_launcher(tmp_path, monkeypatch, failure):
    # The independent backup job and retained Popen handle prevent this fault
    # experiment leaking even when the implementation under test fails cleanup.
    real_popen = ocr_command.subprocess.Popen
    backup = ocr_command._WindowsJob()
    launched = []
    real_start = ocr_command.threading.Thread.start
    real_thread = ocr_command.threading.Thread
    real_job_start = ocr_command._WindowsJob.start
    engine = PROCESS_ENGINE(
        MODELS,
        _identity=IDENTITY,
        _command=(sys.executable, "-B", str(HELPER), "text", "unused", "unused"),
    )

    def contained_launch(*args, **kwargs):
        assert kwargs["creationflags"] & 4
        process = real_popen(*args, **kwargs)
        launched.append(process)
        handle = backup.kernel.OpenProcess(0x101, False, process.pid)
        assert handle
        try:
            assert backup.kernel.AssignProcessToJobObject(backup.handle, handle)
        finally:
            backup.kernel.CloseHandle(handle)
        return process

    def deny_start(self):
        # A start count also sees unrelated threads during a long suite.
        target = getattr(getattr(self, "_target", None), "__name__", "")
        if target == {"reader": "read", "writer": "write"}.get(failure):
            raise RuntimeError("controlled_IO_thread_denied")
        return real_start(self)

    def deny_constructor(*args, **kwargs):
        raise RuntimeError("controlled_IO_thread_denied")

    def deny_job_start(self, process):
        if failure == "cancel":
            raise KeyboardInterrupt
        if failure == "assignment":
            raise OSError("controlled_assignment_denied")
        # Exercise the actual assignment/owned handles, but deny the resume API.
        self.kernel.ResumeThread = lambda thread: 0xFFFFFFFF
        return real_job_start(self, process)

    try:
        with monkeypatch.context() as fault:
            fault.setattr(ocr_command.subprocess, "Popen", contained_launch)
            if failure in {"reader", "writer"}:
                fault.setattr(real_thread, "start", deny_start)
            elif failure == "thread-constructor":
                fault.setattr(ocr_command.threading, "Thread", deny_constructor)
            else:
                fault.setattr(ocr_command._WindowsJob, "start", deny_job_start)
            expected = (
                KeyboardInterrupt
                if failure == "cancel"
                else OSError
                if failure in {"assignment", "resume"}
                else RuntimeError
            )
            with pytest.raises(expected):
                engine.recognize(
                    b"rgba" * 640,
                    32,
                    20,
                    ocr_command.Bounds(
                        max_pages=1,
                        max_encoded_bytes=10000,
                        max_decoded_pixels=1000,
                        max_words=5,
                        max_lines=5,
                        max_blocks=1,
                        max_output_bytes=65536,
                        deadline_s=45,
                    ),
                )
        assert len(launched) == 1
        (tmp_path / "thread-fault-marker.json").write_text(
            json.dumps(
                {
                    "launcher_pid": launched[0].pid,
                    "closed_by_target": launched[0].poll() is not None,
                    "engine_closed": engine.last_worker_closed,
                }
            )
        )
        assert launched[0].poll() is not None and engine.last_worker_closed
        assert launched[0].stdin.closed and launched[0].stdout.closed
    finally:
        try:
            backup_closed = backup.close()
        finally:
            for process in launched:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
        assert backup_closed
