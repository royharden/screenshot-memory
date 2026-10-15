"""Capability controls against the native engine, before any app root is created."""

import sqlite3
from unittest.mock import patch

import pytest

from screenshot_memory.shared.vindex.storage import Store, StoreError, require_sqlite_features


def test_actual_native_memory_probe_and_version():
    assert require_sqlite_features() == sqlite3.sqlite_version


@pytest.mark.parametrize("denied", ["fts", "secure_delete"])
def test_missing_actual_native_capability_refuses_without_creating_root(tmp_path, denied):
    original = sqlite3.connect

    def restricted(*args, **kwargs):
        conn = original(*args, **kwargs)
        assert args[0] == ":memory:"

        def authorize(action, name, value, database, trigger):
            if (denied == "fts" and action == sqlite3.SQLITE_CREATE_VTABLE) or (
                denied == "secure_delete"
                and action == sqlite3.SQLITE_PRAGMA
                and name == "secure_delete"
            ):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.set_authorizer(authorize)
        return conn

    root = tmp_path / "never-created"
    with patch("sqlite3.connect", restricted):
        with pytest.raises(StoreError, match="sqlite_fts5_setup_required"):
            Store(root)
    assert not root.exists()


def test_old_native_version_result_refuses_before_persistent_storage(tmp_path):
    original = sqlite3.connect

    class OldVersionView:
        def __init__(self):
            self.conn = original(":memory:")

        def execute(self, sql):
            assert sql == "SELECT sqlite_version()"
            return self.conn.execute("SELECT '3.41.2'")

        def close(self):
            self.conn.close()

    root = tmp_path / "never-created"
    with patch("sqlite3.connect", return_value=OldVersionView()):
        with pytest.raises(StoreError, match="sqlite_fts5_setup_required"):
            Store(root)
    assert not root.exists()
