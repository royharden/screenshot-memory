"""Real SQLite schema transitions; each control targets a migration failure."""

import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from screenshot_memory.shared.vindex import Store, StoreError

INITIAL = Path(__file__).resolve().parents[2] / (
    "src/screenshot_memory/shared/vindex/migrations/001_initial.sql"
)


def version_one(root):
    root.mkdir()
    with sqlite3.connect(root / "index.sqlite3") as conn:
        conn.executescript(INITIAL.read_text("utf-8"))
        conn.execute("INSERT INTO collections VALUES(?,0,30,0,0)", ("a" * 32,))
        for n, state, generation in [(1, "ready", 0), (2, "deleting", 1), (3, "ready", 1)]:
            conn.execute(
                "INSERT INTO items VALUES(?,?,?,?,1,'{}')",
                ("a" * 32, f"{n:032x}", generation, state),
            )
            for table in ("item_fts", "line_fts"):
                conn.execute(
                    f"INSERT INTO {table} VALUES(?,?,?,?,?)",
                    ("a" * 32, f"{n:032x}", "f" * 32, 0, "ộ migrationcanary"),
                )
        conn.execute(
            "INSERT INTO content VALUES(?,?,?,?,?)",
            ("a" * 32, f"{1:032x}", "e" * 32, 0, b"retained-canary"),
        )
        conn.execute("INSERT INTO tombstones VALUES(?,?,1)", ("a" * 32, f"{2:032x}"))
        conn.execute(
            "INSERT INTO delete_jobs(operation_id,collection_id,item_id,item_generation,"
            "collection_generation,source_bytes,status,created_ns) "
            "VALUES(?,?,?,1,0,1,'marked',1)",
            ("d" * 32, "a" * 32, f"{2:032x}"),
        )


def nonfts_snapshot(conn):
    names = sorted(
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not row[0].startswith(("item_fts", "line_fts", "sqlite_"))
    )
    return {
        name: conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall() for name in names
    }


def test_original_001_bytes_are_immutable():
    # Concrete historical Git identity prevents rewriting history to hide upgrade bugs.
    assert hashlib.sha256(INITIAL.read_bytes()).hexdigest() == INITIAL_SHA


def test_fresh_and_idempotent_startup(tmp_path):
    root = tmp_path / "store"
    for _ in range(2):
        store = Store(root)
        with store.connection() as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
            assert conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
            for table in ("item_fts", "line_fts"):
                assert (
                    conn.execute(
                        f"SELECT v FROM {table}_config WHERE k='secure-delete'"
                    ).fetchone()[0]
                    == 1
                )


def test_upgrade_keeps_current_rows_and_nonfts_but_never_resurrects(tmp_path):
    root = tmp_path / "store"
    version_one(root)
    with sqlite3.connect(root / "index.sqlite3") as conn:
        before = nonfts_snapshot(conn)
        assert (
            conn.execute("SELECT count(*) FROM item_fts WHERE item_fts MATCH 'o'").fetchone()[0]
            == 0
        )
    store = Store(root)
    with store.connection() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        for table in ("item_fts", "line_fts"):
            rows = conn.execute(
                f"SELECT rowid,item_id FROM {table} WHERE {table} MATCH 'o'"
            ).fetchall()
            assert [tuple(r) for r in rows] == [(1, f"{1:032x}")]
        assert (
            bytes(conn.execute("SELECT payload FROM content").fetchone()[0]) == b"retained-canary"
        )
        assert conn.execute("SELECT count(*) FROM items").fetchone()[0] == 3
        # Every non-FTS table, including tombstone and pending-delete job, is unchanged.
        after = {name: [tuple(row) for row in rows] for name, rows in nonfts_snapshot(conn).items()}
        assert after == before


def test_mid_migration_fault_rolls_back_tables_views_version_and_rows(tmp_path):
    root = tmp_path / "store"
    version_one(root)
    original = Store._apply_migration

    def fail(conn, target):
        original(conn, target)
        raise RuntimeError("synthetic_after_002_before_commit")

    with patch.object(Store, "_apply_migration", side_effect=fail):
        with pytest.raises(RuntimeError, match="synthetic_after_002"):
            Store(root)
    with sqlite3.connect(root / "index.sqlite3") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM item_fts").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM visible_item_fts").fetchone()[0] == 1
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE '%_next%'"
        ).fetchall()
    assert Store(root)


def test_concurrent_version1_startup_rereads_inside_lock(tmp_path):
    root = tmp_path / "store"
    version_one(root)
    # WAL is established first so this specifically exercises the migration race.
    with sqlite3.connect(root / "index.sqlite3") as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    barrier = threading.Barrier(2)

    def start(_):
        barrier.wait(timeout=3)
        return Store(root, busy_ms=250)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(list(pool.map(start, range(2)))) == 2
    with Store(root).connection() as conn:
        assert conn.execute("SELECT count(*) FROM item_fts").fetchone()[0] == 1


def test_concurrent_fresh_startup_runs_both_migrations_once(tmp_path):
    root = tmp_path / "store"
    barrier = threading.Barrier(2)

    def start(_):
        barrier.wait(timeout=3)
        return Store(root, busy_ms=250)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(list(pool.map(start, range(2)))) == 2
    with Store(root).connection() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM items").fetchone()[0] == 0


def test_busy_migration_is_bounded_and_preserves_version1(tmp_path):
    root = tmp_path / "store"
    version_one(root)
    with sqlite3.connect(root / "index.sqlite3", isolation_level=None) as blocker:
        blocker.execute("PRAGMA journal_mode=WAL")
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(StoreError, match="database_busy"):
            Store(root, busy_ms=0)
        assert blocker.execute("PRAGMA user_version").fetchone()[0] == 1
        blocker.rollback()
    assert Store(root)


def test_future_schema_refuses_without_downgrade(tmp_path):
    root = tmp_path / "store"
    Store(root)
    with sqlite3.connect(root / "index.sqlite3") as conn:
        conn.execute("PRAGMA user_version=3")
    with pytest.raises(StoreError, match="unsupported_schema"):
        Store(root)
    with sqlite3.connect(root / "index.sqlite3") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3


def test_sidecar_disappearing_during_inspection_is_allowed(tmp_path):
    # Regression: SQLite may unlink shm between another connection's probes.
    store = Store(tmp_path / "store")
    original = Path.lstat
    observed = []

    def transient(path):
        if path.name == "index.sqlite3-shm":
            observed.append(path.name)
            raise FileNotFoundError("synthetic_sidecar_closed")
        return original(path)

    with patch.object(Path, "lstat", transient):
        with store.connection() as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert observed == ["index.sqlite3-shm"]


INITIAL_SHA = "f74d637310033e3d2476a5099b73a49d7928f42240523a2e2441ac4e5f97fd18"
