"""All data here is synthetic bytes, not decoded images or native features."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from screenshot_memory.contracts import Collection, Item, StageStatus
from screenshot_memory.shared.vindex import (
    Deleter,
    DeleteReceipt,
    GenerationToken,
    Store,
    StoreError,
)

COLLECTION = "a" * 32
OTHER = "b" * 32
ITEM = "1" * 32
ROW = "2" * 32
CACHE = "3" * 32
DATA = b"synthetic-byte-control-never-decoded"
DATA_SIZE = len(DATA)
TABLES = ("content", "lines", "words", "captions", "spaces", "vectors", "stages")


def metadata(collection=COLLECTION, item_id=ITEM, size=DATA_SIZE, **updates):
    fields = dict(
        collection_id=collection,
        item_id=item_id,
        source_object_id="4" * 32,
        original_content_sha256=hashlib.sha256(DATA).hexdigest(),
        raw_source_revision="synthetic/raw/1",
        revision=0,
        generation=0,
        collection_generation=0,
        encoded_bytes=size,
        width_px=20,
        height_px=10,
        state="pending",
        stages=tuple(
            StageStatus(stage=s, status="not_run", item_generation=0)
            for s in ("decode", "ocr", "caption", "text_embeddings", "image_embeddings")
        ),
    )
    fields.update(updates)
    return Item(**fields)


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "private")
    result.create_collection(Collection(collection_id=COLLECTION, generation=0))
    result.admit(metadata())
    return result


def fill_all(store, token):
    for table in TABLES:
        store.put(table, token, ROW, (table + " distinctcanary").encode())
    for table in ("item_fts", "line_fts"):
        store.put_fts(table, token, ROW, table + " distinctcanary")
    store.put_cache(CACHE, (token,), b"cache distinctcanary")
    paths = []
    for role in ("original", "thumbnail", "derived", "cache"):
        object_id = store.put_file(token, role, DATA)
        paths.append(store.object_path(token.collection_id, token.item_id, object_id))
        assert store.read_file(token, object_id) == DATA
    return paths


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize(
    "payload",
    ["not-a-blob", 3, 3.25, b"", b"x" * (1024 * 1024 + 1)],
    ids=["sql-text", "sql-integer", "sql-real", "empty-blob", "oversized-blob"],
)
def test_get_rejects_malformed_payload_type_or_bound(store, table, payload):
    token = store.token(COLLECTION, ITEM)
    store.put(table, token, ROW, DATA)
    assert store.get(table, token, ROW) == DATA
    with store.transaction() as conn:
        conn.execute(f"UPDATE {table} SET payload=? WHERE row_id=?", (payload, ROW))
    with pytest.raises(StoreError, match="^invalid_payload$"):
        store.get(table, token, ROW)


@pytest.mark.parametrize("table", TABLES)
def test_get_preserves_valid_blob_and_missing_row(store, table):
    token = store.token(COLLECTION, ITEM)
    assert store.get(table, token, ROW) is None
    store.put(table, token, ROW, DATA)
    assert store.get(table, token, ROW) == DATA


def test_positive_controls_every_store_then_complete_and_idempotent(store):
    token = store.token(COLLECTION, ITEM)
    paths = fill_all(store, token)
    explicit_stores = (
        *TABLES,
        "item_fts",
        "line_fts",
        "cache_entries",
        "cache_dependencies",
        "owned_files",
        "import_members",
        "items",
    )
    with store.connection() as conn:
        for table in explicit_stores:
            if table == "import_members":
                continue
            assert (
                conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE collection_id=?", (COLLECTION,)
                ).fetchone()[0]
                > 0
            )
        for table in ("item_fts", "line_fts"):
            assert (
                conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {table} MATCH 'distinctcanary'"
                ).fetchone()[0]
                == 1
            )
    assert store.get_cache(CACHE, token) == b"cache distinctcanary"
    # Positive control for the added visibility barrier, before all-store deletion.
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO import_batches(batch_id,collection_id,member_count) VALUES(?,?,1)",
            ("e" * 32, COLLECTION),
        )
        conn.execute("INSERT INTO import_members VALUES(?,?,?)", ("e" * 32, COLLECTION, ITEM))
        assert conn.execute("SELECT count(*) FROM import_members").fetchone()[0] == 1
    receipt = Deleter(store).delete(COLLECTION, ITEM)
    assert receipt.status == "deleted"
    assert receipt.files_planned == receipt.files_absent == 4
    assert receipt.stores_verified == explicit_stores
    assert receipt.wal_checkpointed and receipt.verified_ns
    assert all(not p.exists() for p in paths)
    assert not store._generation_memo
    with store.connection() as conn:
        for table in explicit_stores:
            assert (
                conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE collection_id=?", (COLLECTION,)
                ).fetchone()[0]
                == 0
            )
        for table in ("item_fts", "line_fts"):
            assert (
                conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {table} MATCH 'distinctcanary'"
                ).fetchone()[0]
                == 0
            )
        assert conn.execute("SELECT COUNT(*) FROM delete_files").fetchone()[0] == 0
        retained = dict(conn.execute("SELECT * FROM delete_jobs").fetchone())
        assert retained["source_bytes"] == 0
        assert "distinctcanary" not in json.dumps(retained)
        assert conn.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0] == 1
    assert store.collection(COLLECTION).item_count == 0
    assert store.collection(COLLECTION).encoded_bytes == 0
    assert Deleter(Store(store.root)).delete(COLLECTION, ITEM) == receipt
    with pytest.raises(StoreError, match="generation_mismatch|item_retired"):
        store.admit(metadata(collection_generation=1))


def test_mark_hides_open_fts_and_cache_before_any_cleanup(store):
    token = store.token(COLLECTION, ITEM)
    paths = fill_all(store, token)
    receipt = Deleter(store).begin(COLLECTION, ITEM)
    assert receipt.status == "cleanup_pending"
    assert paths[0].exists()  # positive proof cleanup has not run
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM content").fetchone()[0] == 1
        for view in ("visible_item_fts", "visible_line_fts"):
            assert conn.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0] == 0
    for action in (
        lambda: store.item(token),
        lambda: store.get("content", token, ROW),
        lambda: store.read_file(token, "4" * 32),
        lambda: store.get_cache(CACHE, token),
        lambda: store.token(COLLECTION, ITEM),
    ):
        with pytest.raises(StoreError):
            action()
    assert Deleter(store).resume(receipt.operation_id).status == "deleted"


@pytest.mark.parametrize("table", TABLES)
def test_late_derived_write_cannot_resurrect(store, table):
    token = store.token(COLLECTION, ITEM)
    Deleter(store).delete(COLLECTION, ITEM)
    with pytest.raises(StoreError, match="generation_mismatch"):
        store.put(table, token, ROW, b"late canary")


def test_same_raw_image_in_two_collections_independent(store):
    store.create_collection(Collection(collection_id=OTHER, generation=0))
    other = store.admit(metadata(OTHER))
    token = store.token(COLLECTION, ITEM)
    fill_all(store, token)
    other_paths = fill_all(store, other)
    assert Deleter(store).delete(COLLECTION, ITEM).status == "deleted"
    assert store.item(other).original_content_sha256 == hashlib.sha256(DATA).hexdigest()
    assert store.get("words", other, ROW) == b"words distinctcanary"
    assert store.get_cache(CACHE, other) == b"cache distinctcanary"
    assert all(p.exists() for p in other_paths)
    assert store.read_file(other, "4" * 32) == DATA


def test_collection_generation_invalidates_inflight_sibling_and_dependent_cache(store):
    first = store.token(COLLECTION, ITEM)
    sibling = store.admit(metadata(item_id="5" * 32))
    cache_file = store.put_file(sibling, "cache", b"sibling cached payload")
    store.put_cache(CACHE, (first, sibling), b"depends on both")
    pending = Deleter(store).begin(COLLECTION, ITEM)
    for action in (
        lambda: store.put("content", sibling, ROW, b"stale"),
        lambda: store.put_fts("item_fts", sibling, ROW, "stale"),
        lambda: store.put_cache(CACHE, (sibling,), b"stale"),
    ):
        with pytest.raises(StoreError):
            action()
    current = store.token(COLLECTION, sibling.item_id)
    assert current.collection_generation == 1
    assert store.item(current).collection_generation == 1
    with pytest.raises(StoreError, match="cleanup_pending"):
        store.put_cache(CACHE, (current,), b"new cache during cleanup")
    with pytest.raises(StoreError, match="cleanup_pending"):
        store.reserve_file(current, "cache", b"new file during cleanup")
    assert Deleter(store).resume(pending.operation_id).status == "deleted"
    assert not store.object_path(COLLECTION, sibling.item_id, cache_file).exists()
    assert store.get_cache(CACHE, current) is None
    store.put_cache(CACHE, (current,), b"new valid cache")
    assert store.get_cache(CACHE, current) == b"new valid cache"


def test_late_file_finish_after_mark_cannot_leave_object(store):
    token = store.token(COLLECTION, ITEM)
    object_id = store.reserve_file(token, "thumbnail", b"reserved payload")
    pending = Deleter(store).begin(COLLECTION, ITEM)
    with pytest.raises(StoreError, match="generation_mismatch"):
        store.finish_file(token, object_id, b"reserved payload")
    assert not store.object_path(COLLECTION, ITEM, object_id).exists()
    assert Deleter(store).resume(pending.operation_id).status == "deleted"


def test_unlink_failure_retains_pending_hides_data_and_recovers(store):
    token = store.token(COLLECTION, ITEM)
    paths = fill_all(store, token)
    with patch.object(Path, "unlink", side_effect=PermissionError("synthetic private error")):
        receipt = Deleter(store).delete(COLLECTION, ITEM)
    assert receipt.status == "cleanup_pending"
    assert "file_unavailable" in receipt.reasons
    assert receipt.files_absent == 0 and not receipt.wal_checkpointed
    assert all(p.exists() for p in paths)
    assert "synthetic private error" not in receipt.model_dump_json()
    assert store.collection(COLLECTION).item_count == 1  # quota retained while pending
    with store.connection() as conn:
        for table in (
            *TABLES,
            "item_fts",
            "line_fts",
            "cache_entries",
            "cache_dependencies",
            "owned_files",
        ):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    recovered = Deleter(Store(store.root)).recover()
    assert len(recovered) == 1 and recovered[0].status == "deleted"
    assert all(not p.exists() for p in paths)
    assert Deleter(store).recover() == ()


def test_process_exit_after_mark_restart_has_durable_recovery(store):
    token = store.token(COLLECTION, ITEM)
    paths = fill_all(store, token)
    # A fresh process commits intent and exits abruptly, before any cleanup.
    program = (
        "import os,sys; from pathlib import Path; "
        "from screenshot_memory.shared.vindex import Store,Deleter; "
        f"Deleter(Store(Path(sys.argv[1]))).begin('{COLLECTION}','{ITEM}');os._exit(23)"
    )
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    outcome = subprocess.run(
        [sys.executable, "-c", program, str(store.root)],
        capture_output=True,
        timeout=10,
        check=False,
        env=env,
    )
    assert outcome.returncode == 23, outcome.stderr.decode()
    assert all(p.exists() for p in paths)
    new = Store(store.root)
    with pytest.raises(StoreError, match="item_unavailable"):
        new.token(COLLECTION, ITEM)
    receipts = Deleter(new).recover()
    assert len(receipts) == 1 and receipts[0].status == "deleted"
    assert all(not p.exists() for p in paths)


def test_active_wal_reader_prevents_completed_receipt_until_closed(store):
    token = store.token(COLLECTION, ITEM)
    store.put("content", token, ROW, b"retained reader canary")
    with store.connection() as reader:
        reader.execute("BEGIN")
        assert (
            reader.execute("SELECT payload FROM content").fetchone()[0] == b"retained reader canary"
        )
        receipt = Deleter(store).delete(COLLECTION, ITEM)
        assert receipt.status == "cleanup_pending"
        assert receipt.reasons == ("checkpoint_busy",)
        assert not receipt.wal_checkpointed
        # Data in a previously returned/external snapshot cannot be recalled.
        assert (
            reader.execute("SELECT payload FROM content").fetchone()[0] == b"retained reader canary"
        )
        reader.rollback()
    assert Deleter(store).resume(receipt.operation_id).status == "deleted"


def test_busy_writer_is_bounded_and_cannot_claim_delete(store):
    with store.connection() as locker:
        locker.execute("BEGIN IMMEDIATE")
        with pytest.raises(StoreError, match="database_busy"):
            Deleter(store).delete(COLLECTION, ITEM)
        locker.rollback()
    assert store.item(store.token(COLLECTION, ITEM)).item_id == ITEM


def test_changed_file_is_preserved_and_pending(store):
    token = store.token(COLLECTION, ITEM)
    object_id = store.put_file(token, "thumbnail", b"original identity")
    path = store.object_path(COLLECTION, ITEM, object_id)
    path.write_bytes(b"unexpected replacement")
    receipt = Deleter(store).delete(COLLECTION, ITEM)
    assert receipt.status == "cleanup_pending"
    assert "file_identity_mismatch" in receipt.reasons
    assert path.read_bytes() == b"unexpected replacement"


def test_unregistered_target_object_blocks_completion_without_removing_it(store):
    path = store.object_path(COLLECTION, ITEM, "8" * 32)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"unregistered must not delete")
    receipt = Deleter(store).delete(COLLECTION, ITEM)
    assert receipt.status == "cleanup_pending" and "unexpected_objects" in receipt.reasons
    assert path.read_bytes() == b"unregistered must not delete"


def test_unsafe_symlink_never_unlinks_external_file(store, tmp_path):
    token = store.token(COLLECTION, ITEM)
    object_id = store.put_file(token, "thumbnail", b"owned")
    path = store.object_path(COLLECTION, ITEM, object_id)
    external = tmp_path / "external"
    external.write_bytes(b"external preserve")
    path.unlink()
    try:
        path.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"host symlink privilege unavailable: {exc.errno}")
    receipt = Deleter(store).delete(COLLECTION, ITEM)
    assert receipt.status == "cleanup_pending" and "unsafe_object" in receipt.reasons
    assert external.read_bytes() == b"external preserve" and path.is_symlink()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows reparse point control")
def test_windows_junction_parent_never_traversed(store, tmp_path):
    import _winapi

    external = tmp_path / "external-directory"
    external.mkdir()
    canary = external / ("8" * 32)
    canary.write_bytes(b"external junction canary")
    parent = store.object_path(COLLECTION, ITEM, "8" * 32).parent
    parent.parent.mkdir(parents=True)
    _winapi.CreateJunction(str(external), str(parent))
    with pytest.raises(StoreError, match="unsafe_object"):
        store.object_path(COLLECTION, ITEM, "8" * 32)
    receipt = Deleter(store).delete(COLLECTION, ITEM)
    assert receipt.status == "cleanup_pending" and "unsafe_object" in receipt.reasons
    assert canary.read_bytes() == b"external junction canary"


@pytest.mark.parametrize("bad", ["../escape", "0" * 31, "f" * 33, "F" * 32, "C:/absolute", True, 3])
def test_object_handles_reject_paths_and_coercions(store, bad):
    with pytest.raises(StoreError, match="invalid_id"):
        store.object_path(COLLECTION, ITEM, bad)


@pytest.mark.parametrize(
    "updates",
    [
        dict(encoded_bytes=True),
        dict(encoded_bytes=8 * 1024 * 1024 + 1),
        dict(width_px=20_000_000, height_px=2),
        dict(generation=True),
        dict(collection_generation=0.0),
    ],
)
def test_record_admission_strict_caps_before_sql(store, updates):
    with pytest.raises(ValidationError):
        store.admit(metadata(item_id="6" * 32, **updates))
    assert store.collection(COLLECTION).item_count == 1


def test_item_count_atomic_across_concurrent_connections(tmp_path):
    root = tmp_path / "concurrent"
    first = Store(root)
    first.create_collection(Collection(collection_id=COLLECTION, generation=0, cap=1))
    barrier = threading.Barrier(2)

    def insert(number):
        separate = Store(root, busy_ms=100)
        barrier.wait(timeout=5)
        try:
            separate.admit(metadata(item_id=f"{number:032x}"))
            return "admitted"
        except StoreError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(insert, (10, 11)))
    assert results == ["admitted", "collection_full"]
    assert first.collection(COLLECTION).item_count == 1


def test_collection_bytes_cap_admission_has_no_decode_claim(tmp_path):
    store = Store(tmp_path / "bytes")
    store.create_collection(Collection(collection_id=COLLECTION, generation=0))
    # Declared8MiB records, not allocated or decoded image payloads.
    for number in range(12):
        store.admit(metadata(item_id=f"{number:032x}", size=8 * 1024 * 1024))
    with pytest.raises(StoreError, match="collection_bytes_full"):
        store.admit(metadata(item_id="e" * 32, size=8 * 1024 * 1024))
    assert store.collection(COLLECTION).encoded_bytes == 96 * 1024 * 1024


def test_source_file_hash_and_size_must_match_declared_metadata(store):
    token = store.token(COLLECTION, ITEM)
    with pytest.raises(StoreError, match="source_identity_mismatch"):
        store.put_file(token, "original", b"different")
    object_id = store.put_file(token, "original", DATA)
    assert object_id == "4" * 32 and store.read_file(token, object_id) == DATA
    with pytest.raises(StoreError, match="file_exists"):
        store.put_file(token, "original", DATA)


def test_sql_migration_has_foreign_keys_for_all_payloads(store):
    with store.connection() as conn:
        for table in TABLES:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    f"INSERT INTO {table} VALUES(?,?,?,?,?)",
                    (COLLECTION, "9" * 32, ROW, 0, b"orphan"),
                )
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3


def test_receipt_strict_and_completion_checks_cannot_be_omitted(store):
    completed = Deleter(store).delete(COLLECTION, ITEM)
    assert DeleteReceipt.model_validate_json(completed.model_dump_json()) == completed
    for field, value in (
        ("wal_checkpointed", False),
        ("stores_verified", ()),
        ("verified_ns", None),
        ("files_absent", True),
        ("reasons", ("checkpoint_busy",)),
        ("schema_version", True),
    ):
        data = completed.model_dump()
        data[field] = value
        with pytest.raises(ValidationError):
            DeleteReceipt.model_validate(data)


def test_not_found_is_not_success_and_invalid_dependency_scope_rejected(store):
    absent = Deleter(store).delete(COLLECTION, "f" * 32)
    assert absent.status == "not_found" and absent.operation_id is None
    assert not absent.wal_checkpointed and not absent.stores_verified
    token = store.token(COLLECTION, ITEM)
    store.create_collection(Collection(collection_id=OTHER, generation=0))
    other = store.admit(metadata(OTHER, item_id="6" * 32))
    with pytest.raises(StoreError, match="invalid_dependencies"):
        store.put_cache(CACHE, (token, other), b"invalid mixed scope")
    with pytest.raises(ValidationError):
        GenerationToken(
            collection_id=COLLECTION, item_id=ITEM, item_generation=True, collection_generation=0
        )


def test_actual_delayed_producer_cannot_resurrect_after_delete(store):
    token = store.token(COLLECTION, ITEM)
    captured = threading.Event()
    proceed = threading.Event()

    def producer():
        captured.set()
        assert proceed.wait(5)
        try:
            store.put("vectors", token, ROW, b"late synthetic bytes")
        except StoreError as exc:
            return str(exc)
        return "unexpected write"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(producer)
        assert captured.wait(5)
        assert Deleter(store).delete(COLLECTION, ITEM).status == "deleted"
        proceed.set()
        assert future.result(timeout=5) == "generation_mismatch"
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == 0


def test_two_cleanup_runners_cannot_downgrade_completed_job_or_counts(store):
    token = store.token(COLLECTION, ITEM)
    fill_all(store, token)
    first = Deleter(store)
    intent = first.begin(COLLECTION, ITEM)
    paused = threading.Event()
    proceed = threading.Event()
    original = first._unlink
    once = False

    def delayed_unlink(file):
        nonlocal once
        if not once:
            once = True
            paused.set()
            assert proceed.wait(10)
        original(file)

    with patch.object(first, "_unlink", delayed_unlink):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(first.resume, intent.operation_id)
            assert paused.wait(5)
            completed = Deleter(Store(store.root)).resume(intent.operation_id)
            assert completed.status == "deleted" and completed.files_absent == 4
            proceed.set()
            assert future.result(timeout=5) == completed
    assert Deleter(store).delete(COLLECTION, ITEM) == completed
    assert store.collection(COLLECTION).item_count == 0


def test_read_transaction_serializes_delete_until_returned_bytes(store):
    token = store.token(COLLECTION, ITEM)
    object_id = store.put_file(token, "thumbnail", DATA)
    captured = threading.Event()
    proceed = threading.Event()
    real = Store._verified_file

    def paused_read(path, row):
        result = real(path, row)
        captured.set()
        assert proceed.wait(5)
        return result

    with patch.object(Store, "_verified_file", staticmethod(paused_read)):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(store.read_file, token, object_id)
            assert captured.wait(5)
            with pytest.raises(StoreError, match="database_busy"):
                Deleter(store).begin(COLLECTION, ITEM)
            proceed.set()
            assert future.result(timeout=5) == DATA
    assert Deleter(store).delete(COLLECTION, ITEM).status == "deleted"


@pytest.mark.parametrize("crash_stage,exit_code", [("file_fsync", 25), ("after_purge", 24)])
def test_process_exit_during_file_or_cleanup_recovers_known_intent(store, crash_stage, exit_code):
    token = store.token(COLLECTION, ITEM)
    if crash_stage == "after_purge":
        paths = fill_all(store, token)
        program = (
            "import os,sys;from pathlib import Path;"
            "from screenshot_memory.shared.vindex import Store,Deleter;"
            "Deleter._checkpoint=lambda self:os._exit(24);"
            f"Deleter(Store(Path(sys.argv[1]))).delete('{COLLECTION}','{ITEM}')"
        )
    else:
        object_id = store.reserve_file(token, "thumbnail", DATA)
        paths = [store.object_path(COLLECTION, ITEM, object_id)]
        program = (
            "import os,sys;from pathlib import Path;"
            "from screenshot_memory.shared.vindex import Store;"
            "real=os.fsync;os.fsync=lambda fd:(real(fd),os._exit(25));"
            f"s=Store(Path(sys.argv[1]));t=s.token('{COLLECTION}','{ITEM}');"
            f"s.finish_file(t,'{object_id}',{DATA!r})"
        )
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    outcome = subprocess.run(
        [sys.executable, "-c", program, str(store.root)],
        capture_output=True,
        timeout=10,
        check=False,
        env=env,
    )
    assert outcome.returncode == exit_code, outcome.stderr.decode()
    reopened = Store(store.root)
    if crash_stage == "file_fsync":
        assert paths[0].read_bytes() == DATA
        receipt = Deleter(reopened).delete(COLLECTION, ITEM)
    else:
        assert all(not p.exists() for p in paths)
        (receipt,) = Deleter(reopened).recover()
    assert receipt.status == "deleted"
    assert all(not p.exists() for p in paths)
