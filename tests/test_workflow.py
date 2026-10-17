"""Real synthetic PNG/JPEG and SQLite journeys; no reference gallery or model output."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from screenshot_memory import workflow
from screenshot_memory.cli import main
from screenshot_memory.shared.vindex import Deleter, Store, StoreError
from screenshot_memory.shared.vindex.deletion import STORES
from screenshot_memory.shared.vindex.search import keyword_search


def image(tmp_path, name="input.png", *, colour="blue"):
    path = tmp_path / name
    with Image.new("RGB", (16, 12), colour) as value:
        value.save(path)
    return path


def test_import_inspect_query_refusal_restart_and_every_store_delete(tmp_path):
    source = image(tmp_path)
    jpeg = image(tmp_path, "other.jpg")
    store = Store(tmp_path / "private")
    collection = workflow.create_collection(store)
    items = workflow.import_images(store, collection, (source, jpeg))
    assert len(items) == 2
    assert all(i.state == "partial" and i.stages[0].provenance == "observed" for i in items)
    assert all(i.width_px == 16 and i.height_px == 12 for i in items)
    assert all(i.source_grid_sha256 for i in items)
    store = Store(store.root)
    assert len(workflow.inspect_items(store, collection)) == 2
    for item in items:
        assert workflow.inspect_items(store, collection, item.item_id)[0] == item
        token = store.token(collection, item.item_id)
        assert store.read_file(token, item.source_object_id) in (
            source.read_bytes(),
            jpeg.read_bytes(),
        )
    assert workflow.query(store, collection, "blue rectangle") == {
        "status": "unavailable",
        "reason": "ocr_caption_and_vectors_not_implemented",
        "executed": False,
        "hits": [],
        "mode": "local_construction",
    }
    # Positive controls cover real decode metadata/files, not invented OCR/vector output.
    with store.connection() as conn:
        for table in ("items", "content", "stages", "owned_files"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 2
    for item in items:
        receipt = Deleter(store).delete(collection, item.item_id)
        assert receipt.status == "deleted" and receipt.stores_verified == STORES
        assert receipt.files_absent == receipt.files_planned == 1
        with pytest.raises(StoreError):
            workflow.inspect_items(store, collection, item.item_id)
        assert not store.object_path(collection, item.item_id, item.source_object_id).exists()
    assert workflow.inspect_items(Store(store.root), collection) == ()
    assert workflow.query(store, collection, "blue")["hits"] == []
    with store.connection() as conn:
        for table in STORES:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert source.exists() and jpeg.exists()  # Explicit import preserves caller-owned originals.


def test_identical_content_separate_items_and_collections_survive_target_delete(tmp_path):
    path = image(tmp_path)
    store = Store(tmp_path / "private")
    first, second = (workflow.create_collection(store) for _ in range(2))
    a, b = workflow.import_images(store, first, (path, path))
    (c,) = workflow.import_images(store, second, (path,))
    assert len({a.item_id, b.item_id, c.item_id}) == 3
    assert a.original_content_sha256 == b.original_content_sha256 == c.original_content_sha256
    assert Deleter(store).delete(first, a.item_id).status == "deleted"
    assert [i.item_id for i in workflow.inspect_items(store, first)] == [b.item_id]
    assert workflow.inspect_items(store, second, c.item_id)[0].item_id == c.item_id
    assert store.read_file(store.token(second, c.item_id), c.source_object_id) == path.read_bytes()


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "directory",
        "traversal",
        "corrupt",
        "signature",
        "animated",
        "bytes",
        "pixels",
        "symlink",
    ],
)
def test_invalid_image_refuses_entire_batch_before_metadata_or_files(tmp_path, monkeypatch, kind):
    valid = image(tmp_path)
    invalid = tmp_path / "bad.png"
    if kind == "directory":
        invalid.mkdir()
    elif kind == "traversal":
        invalid = tmp_path / "child" / ".." / valid.name
    elif kind == "corrupt":
        invalid.write_bytes(b"\x89PNG\r\n\x1a\nnot a decoded image")
    elif kind == "signature":
        invalid.write_bytes(b"arbitrary text")
    elif kind == "animated":
        with Image.new("RGB", (2, 2), "red") as a, Image.new("RGB", (2, 2), "green") as b:
            a.save(invalid, save_all=True, append_images=[b], duration=10, loop=0)
    elif kind == "bytes":
        with invalid.open("wb") as stream:
            stream.truncate(workflow.MAX_IMAGE_BYTES + 1)
    elif kind == "pixels":
        invalid = image(tmp_path, "large.png")
        monkeypatch.setattr(workflow, "MAX_IMAGE_PIXELS", 100)
    elif kind == "symlink":
        try:
            invalid.symlink_to(valid)
        except OSError:
            pytest.skip("Windows symlink privilege unavailable")
    store = Store(tmp_path / "private")
    collection = workflow.create_collection(store)
    with pytest.raises(workflow.WorkflowError):
        workflow.import_images(store, collection, (valid, invalid))
    assert store.collection(collection).item_count == 0
    with store.connection() as conn:
        for table in ("items", "owned_files", "import_batches", "import_members"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("mode", [stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFDIR])
def test_nonregular_selected_path_is_rejected_without_opening(tmp_path, monkeypatch, mode):
    # Opening a FIFO/driver can block before a descriptor type check is possible.
    source = image(tmp_path)
    original_lstat = Path.lstat

    def special_file(path, *args, **kwargs):
        info = original_lstat(path, *args, **kwargs)
        if path == source:
            return SimpleNamespace(st_mode=mode | 0o600, st_file_attributes=0)
        return info

    def forbidden_open(*args, **kwargs):
        raise AssertionError("nonregular source must be refused before open")

    monkeypatch.setattr(Path, "lstat", special_file)
    monkeypatch.setattr(workflow.os, "open", forbidden_open)
    with pytest.raises(workflow.WorkflowError, match="invalid_image_path"):
        workflow.decode_selected(source)


def test_selected_file_replaced_before_open_is_rejected(tmp_path, monkeypatch):
    source = image(tmp_path)
    replacement = tmp_path / "replacement.png"
    replacement.write_bytes(source.read_bytes())
    original_open = os.open

    def replace_before_open(path, flags):
        os.replace(replacement, source)
        return original_open(path, flags)

    monkeypatch.setattr(workflow.os, "open", replace_before_open)
    with pytest.raises(workflow.WorkflowError, match="image_changed_during_read"):
        workflow.decode_selected(source)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO creation unavailable")
@pytest.mark.parametrize("replace_at_open", [False, True])
def test_actual_fifo_refusal_does_not_wait_for_a_writer(tmp_path, replace_at_open):
    # The subprocess timeout bounds the regression even on the old blocking code.
    source = image(tmp_path)
    program = """
import os, sys
from pathlib import Path
from screenshot_memory.workflow import WorkflowError, decode_selected
source = Path(sys.argv[1])
if sys.argv[2] == "True":
    original_open = os.open
    def replace(path, flags):
        source.unlink()
        os.mkfifo(source)
        return original_open(path, flags)
    os.open = replace
else:
    source.unlink()
    os.mkfifo(source)
try:
    decode_selected(source)
except WorkflowError as error:
    assert str(error) == "invalid_image_path"
else:
    raise AssertionError("FIFO accepted")
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-B", "-c", program, str(source), str(replace_at_open)],
        env=environment,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_batch_count_and_collection_overflow_preserve_prior_item(tmp_path):
    source = image(tmp_path)
    store = Store(tmp_path / "private")
    collection = workflow.create_collection(store)
    (existing,) = workflow.import_images(store, collection, (source,))
    for paths in ((source,) * 31, (source,) * 30, ()):
        with pytest.raises(workflow.WorkflowError):
            workflow.import_images(store, collection, paths)
    assert workflow.inspect_items(store, collection) == (existing,)


@pytest.mark.parametrize("fail_cleanup", [False, True])
def test_second_write_failure_rolls_back_batch_or_hides_pending_cleanup(
    tmp_path, monkeypatch, fail_cleanup
):
    source = image(tmp_path)
    store = Store(tmp_path / "private")
    collection = workflow.create_collection(store)
    original_put = Store.put_file
    calls = 0

    def fail_second(self, *args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic staging failure")
        return original_put(self, *args)

    original_unlink = Deleter._unlink
    monkeypatch.setattr(Store, "put_file", fail_second)
    if fail_cleanup:
        monkeypatch.setattr(Deleter, "_unlink", lambda *_: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(workflow.WorkflowError) as error:
        workflow.import_images(store, collection, (source, source))
    assert str(error.value) == ("cleanup_pending" if fail_cleanup else "import_failed")
    assert workflow.inspect_items(store, collection) == ()
    assert keyword_search(store, collection, "anything") == ()
    monkeypatch.setattr(Deleter, "_unlink", original_unlink)
    receipts = workflow.recover_imports(Store(store.root), collection)
    assert all(r.status == "deleted" for r in receipts)
    assert store.collection(collection).item_count == 0
    with store.connection() as conn:
        for table in (*STORES, "import_batches"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("phase", ["file", "stage", "before_commit"])
def test_real_process_exit_keeps_whole_batch_hidden_and_explicit_restart_recovers(tmp_path, phase):
    source = image(tmp_path)
    store = Store(tmp_path / "private")
    collection = workflow.create_collection(store)
    # Crash after actual durable writes; no Python exception handler/finally runs.
    program = """
import os, sys
from pathlib import Path
from screenshot_memory.shared.vindex import Store
from screenshot_memory.workflow import import_images
phase, root, collection, source = sys.argv[1:]
name = {"file": "put_file", "stage": "publish_stage", "before_commit": "complete_import"}[phase]
original = getattr(Store, name)
def crash(self, *args):
    if phase != "before_commit":
        original(self, *args)
    os._exit(73)
setattr(Store, name, crash)
import_images(Store(Path(root)), collection, (Path(source), Path(source)))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-c", program, phase, str(store.root), collection, str(source)],
        env=environment,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 73, result.stderr
    reopened = Store(store.root)
    assert reopened.collection(collection).item_count == 2  # Durable reservation positive control.
    assert workflow.inspect_items(reopened, collection) == ()
    with reopened.connection() as conn:
        ids = [r[0] for r in conn.execute("SELECT item_id FROM import_members")]
    assert len(ids) == 2
    for item_id in ids:
        with pytest.raises(StoreError, match="import_incomplete"):
            reopened.token(collection, item_id)
    assert keyword_search(reopened, collection, "anything") == ()
    receipts = workflow.recover_imports(reopened, collection)
    assert len(receipts) == 2 and all(r.status == "deleted" for r in receipts)
    assert reopened.collection(collection).item_count == 0
    assert workflow.recover_imports(Store(store.root), collection) == ()
    assert len(workflow.import_images(reopened, collection, (source,))) == 1


def test_cli_confirmation_actual_persistence_and_repository_root_refusal(tmp_path, capsys):
    root = tmp_path / "private"
    source = image(tmp_path)

    def cli(*args):
        code = main(list(args))
        return code, json.loads(capsys.readouterr().out)

    code, result = cli("create", "--root", str(root))
    assert code == 0
    collection = result["collection_id"]
    common = ("--root", str(root), "--collection", collection)
    code, result = cli("import", *common, str(source))
    assert code == 0 and result["status"] == "imported_partial"
    item = result["items"][0]["item_id"]
    assert cli("inspect", *common, "--item", item)[0] == 0
    code, result = cli("query", *common, "anything")
    assert code == 2 and result["executed"] is False
    assert cli("delete", *common, "--item", item)[1]["reason"] == "delete_confirmation_required"
    assert cli("inspect", *common, "--item", item)[0] == 0
    code, result = cli("delete", *common, "--item", item, "--confirm")
    assert code == 0 and result["status"] == "deleted"
    assert cli("inspect", *common, "--item", item)[0] == 2
    assert cli("recover", *common) == (0, {"status": "ok", "receipts": []})
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".git").write_text("gitdir: elsewhere")
    assert (
        cli("create", "--root", str(repository / "private"))[1]["reason"]
        == "storage_inside_repository"
    )
    assert not (repository / "private").exists()


def test_staging_barrier_covers_direct_reads_fts_and_cache_and_publishes_together(
    tmp_path, monkeypatch
):
    source = image(tmp_path)
    store = Store(tmp_path / "private")
    collection = workflow.create_collection(store)
    complete = Store.complete_import

    def check_barrier(self, batch_id, tokens):
        assert self.list_items(collection) == ()
        for token in tokens:
            with self.connection() as conn:
                item = json.loads(
                    conn.execute(
                        "SELECT metadata FROM items WHERE item_id=?", (token.item_id,)
                    ).fetchone()[0]
                )
            # Deliberately planted text is a store visibility control, never OCR evidence.
            self.put_fts("item_fts", token, "f" * 32, "stagingcanary")
            self.put_fts("line_fts", token, "f" * 32, "stagingcanary")
            for read in (
                lambda t=token: self.token(collection, t.item_id),
                lambda t=token: self.item(t),
                lambda t=token: self.get("content", t, "f" * 32),
                lambda t=token, i=item: self.read_file(t, i["source_object_id"]),
                lambda t=token: self.put_cache("e" * 32, (t,), b"must not cache"),
            ):
                with pytest.raises(StoreError, match="import_incomplete"):
                    read()
        with self.connection() as conn:
            assert conn.execute("SELECT count(*) FROM item_fts").fetchone()[0] == 2
            assert conn.execute("SELECT count(*) FROM visible_item_fts").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM visible_line_fts").fetchone()[0] == 0
        assert keyword_search(self, collection, "stagingcanary") == ()
        with pytest.raises(StoreError):
            complete(self, batch_id, (tokens[0], tokens[0]))
        with pytest.raises(StoreError):
            complete(self, batch_id, ("invalid",))
        complete(self, batch_id, tokens)
        assert len(self.list_items(collection)) == 2
        assert len(keyword_search(self, collection, "stagingcanary")) == 2

    monkeypatch.setattr(Store, "complete_import", check_barrier)
    items = workflow.import_images(store, collection, (source, source))
    for item in items:
        assert Deleter(store).delete(collection, item.item_id).status == "deleted"
    assert keyword_search(store, collection, "stagingcanary") == ()


def test_deletion_between_stage_and_batch_commit_cannot_publish_surviving_sibling(
    tmp_path, monkeypatch
):
    source = image(tmp_path)
    store = Store(tmp_path / "private")
    collection = workflow.create_collection(store)
    complete = Store.complete_import

    def delete_before_commit(self, batch_id, tokens):
        Deleter(self).begin(collection, tokens[0].item_id)
        complete(self, batch_id, tokens)

    monkeypatch.setattr(Store, "complete_import", delete_before_commit)
    with pytest.raises(workflow.WorkflowError, match="import_failed"):
        workflow.import_images(store, collection, (source, source))
    assert store.list_items(collection) == ()
    assert store.collection(collection).item_count == 0
