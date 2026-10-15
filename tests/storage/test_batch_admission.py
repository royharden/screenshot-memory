"""Synthetic metadata-only quota/transaction controls, never actual image decode."""

import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from screenshot_memory.contracts import Collection, Item, StageStatus
from screenshot_memory.shared.vindex import Deleter, Store, StoreError

C = "a" * 32
D = "b" * 32


def metadata(n, *, cid=C, cg=0, size=1, running=False):
    return Item(
        collection_id=cid,
        item_id=f"{n:032x}",
        source_object_id=f"{n + 100:032x}",
        original_content_sha256=hashlib.sha256(b"synthetic-not-decoded").hexdigest(),
        raw_source_revision="synthetic/unexecuted/1",
        revision=0,
        generation=0,
        collection_generation=cg,
        encoded_bytes=size,
        width_px=1,
        height_px=1,
        state="pending",
        stages=tuple(
            StageStatus(
                stage=s,
                status="running" if running and s == "decode" else "not_run",
                item_generation=0,
            )
            for s in ("decode", "ocr", "caption", "text_embeddings", "image_embeddings")
        ),
    )


def new_store(tmp_path, cap=30):
    store = Store(tmp_path / "private", busy_ms=250)
    for cid in (C, D):
        store.create_collection(Collection(collection_id=cid, generation=0, cap=cap))
    return store


def ids(store, cid=C):
    with store.connection() as conn:
        return tuple(
            r[0]
            for r in conn.execute(
                "SELECT item_id FROM items WHERE collection_id=? ORDER BY item_id", (cid,)
            )
        )


def test_thirty_item_batch_commits_exact_counter_and_current_tokens(tmp_path):
    store = new_store(tmp_path)
    tokens = store.admit_batch(tuple(metadata(n) for n in range(1, 31)))
    assert len(tokens) == 30 and len(ids(store)) == 30
    assert store.collection(C).item_count == store.collection(C).encoded_bytes == 30
    assert all(store.item(t).item_id == t.item_id for t in tokens)


def test_count_overflow_rejects_entire_batch_without_partial_first_item(tmp_path):
    store = new_store(tmp_path, 3)
    store.admit(metadata(1))
    store.admit(metadata(2))
    with pytest.raises(StoreError, match="collection_full"):
        store.admit_batch((metadata(3), metadata(4)))
    assert ids(store) == (f"{1:032x}", f"{2:032x}")
    assert store.collection(C).item_count == 2


def test_combined_byte_overflow_rejects_all_rows_and_exact_boundary_is_allowed(tmp_path):
    store = new_store(tmp_path)
    MiB = 1024 * 1024
    store.admit_batch(tuple(metadata(n, size=8 * MiB) for n in range(1, 13)))
    before = store.collection(C)
    with pytest.raises(StoreError, match="collection_bytes_full"):
        store.admit_batch((metadata(13, size=3 * MiB), metadata(14, size=3 * MiB)))
    assert store.collection(C) == before and len(ids(store)) == 12
    store.admit_batch((metadata(13, size=2 * MiB), metadata(14, size=2 * MiB)))
    assert store.collection(C).encoded_bytes == 100 * MiB
    with pytest.raises(StoreError, match="collection_bytes_full"):
        store.admit_batch((metadata(15),))
    assert len(ids(store)) == 14


@pytest.mark.parametrize("kind", ["duplicate_within", "already_existing", "retired"])
def test_duplicate_or_retired_member_does_not_admit_its_valid_sibling(tmp_path, kind):
    store = new_store(tmp_path)
    cg = 0
    if kind == "already_existing":
        store.admit(metadata(1))
    elif kind == "retired":
        store.admit(metadata(1))
        assert Deleter(store).delete(C, f"{1:032x}").status == "deleted"
        cg = 1
    before = store.collection(C)
    first = metadata(1, cg=cg)
    second = metadata(1 if kind == "duplicate_within" else 2, cg=cg)
    with pytest.raises(StoreError, match="item_retired" if kind == "retired" else "item_exists"):
        store.admit_batch((first, second))
    assert store.collection(C) == before
    assert f"{2:032x}" not in ids(store)


@pytest.mark.parametrize("scope", ["foreign_collection", "mixed_generation", "stale_generation"])
def test_scope_errors_leave_both_collections_empty(tmp_path, scope):
    store = new_store(tmp_path)
    first = metadata(1, cg=1 if scope == "stale_generation" else 0)
    second = metadata(
        2,
        cid=D if scope == "foreign_collection" else C,
        cg=1 if scope in {"mixed_generation", "stale_generation"} else 0,
    )
    with pytest.raises(StoreError):
        store.admit_batch((first, second))
    assert ids(store) == ids(store, D) == ()
    assert store.collection(C).item_count == store.collection(D).item_count == 0


@pytest.mark.parametrize("batch", [(), [], tuple(metadata(n) for n in range(1, 32))])
def test_batch_shape_and_cap_are_closed(tmp_path, batch):
    store = new_store(tmp_path)
    with pytest.raises(StoreError, match="invalid_batch"):
        store.admit_batch(batch)
    assert ids(store) == ()


def test_unchecked_invalid_second_model_refuses_before_any_sql_admission(tmp_path):
    store = new_store(tmp_path)
    bad = metadata(2).model_copy(update={"encoded_bytes": True})
    with pytest.raises(ValidationError):
        store.admit_batch((metadata(1), bad))
    assert ids(store) == () and store.collection(C).encoded_bytes == 0


def test_batch_requires_initial_unprocessed_but_legacy_single_contract_is_preserved(tmp_path):
    store = new_store(tmp_path)
    running = metadata(1, running=True)
    with pytest.raises(StoreError, match="batch_not_unprocessed"):
        store.admit_batch((metadata(2), running))
    assert ids(store) == ()
    assert store.admit(running).item_id == running.item_id


@pytest.mark.parametrize("fault", ["second_insert", "counter_update"])
def test_sql_fault_after_work_started_rolls_back_items_and_counters(tmp_path, fault):
    store = new_store(tmp_path)
    with store.connection() as conn:
        if fault == "second_insert":
            conn.execute(
                "CREATE TRIGGER injected BEFORE INSERT ON items WHEN NEW.item_id='"
                + f"{2:032x}"
                + "' BEGIN SELECT RAISE(ABORT,'synthetic_fault'); END"
            )
        else:
            conn.execute(
                "CREATE TRIGGER injected BEFORE UPDATE ON collections "
                "BEGIN SELECT RAISE(ABORT,'synthetic_fault'); END"
            )
    with pytest.raises((StoreError, sqlite3.IntegrityError)):
        store.admit_batch((metadata(1), metadata(2)))
    assert ids(store) == ()
    assert store.collection(C).item_count == store.collection(C).encoded_bytes == 0


def test_two_real_sqlite_batches_compete_for_capacity_without_partial_loser(tmp_path):
    store = new_store(tmp_path, 3)
    separate = Store(store.root, busy_ms=250)
    barrier = threading.Barrier(2)

    def admit(pair):
        instance, seed = pair
        barrier.wait(timeout=3)
        try:
            return (
                "admitted",
                tuple(
                    t.item_id for t in instance.admit_batch((metadata(seed), metadata(seed + 1)))
                ),
            )
        except StoreError as exc:
            return (str(exc), ())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(admit, ((store, 1), (separate, 3))))
    assert sorted(r[0] for r in results) == ["admitted", "collection_full"]
    winner = next(r[1] for r in results if r[0] == "admitted")
    assert ids(store) == winner and store.collection(C).item_count == 2


def test_same_declared_source_and_item_id_in_other_collection_are_independent(tmp_path):
    store = new_store(tmp_path)
    a = store.admit_batch((metadata(1),))[0]
    b = store.admit_batch((metadata(1, cid=D),))[0]
    assert a.item_id == b.item_id and a.collection_id != b.collection_id
    assert Deleter(store).delete(C, a.item_id).status == "deleted"
    assert store.item(b).collection_id == D
    assert store.collection(D).item_count == 1
