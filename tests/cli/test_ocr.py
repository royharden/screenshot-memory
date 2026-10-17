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
        future = pool.submit(ocr_command.run_ocr, store, cid, iid, MODELS, timeout_s=30)
        wait_file(tmp_path / "marker")
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
    result = ocr_command.run_ocr(store, cid, iid, MODELS, timeout_s=10)
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
        _command=(sys.executable, "-c", "import time;time.sleep(2)"),
    )
    monkeypatch.setattr(ocr_command, "ProcessOcrEngine", lambda models: engine)
    try:
        result = ocr_command.run_ocr(store, cid, iid, MODELS, timeout_s=0.05)
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
