"""Generation-checked metadata/payload storage. No decoding or retrieval here.

The configured root is private application storage, exclusively managed by this
module. Object handles are generated opaque IDs, never caller supplied paths.
SQLite transactions, rather than a process-local lock, arbitrate admission.
"""

import hashlib
import os
import re
import sqlite3
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from screenshot_memory.contracts import (
    MAX_COLLECTION_BYTES,
    MAX_COUNTER,
    Collection,
    Counter,
    Item,
    Metadata,
    OpaqueID,
)

PAYLOAD_TABLES = ("content", "lines", "words", "captions", "spaces", "vectors", "stages")
FTS_TABLES = ("item_fts", "line_fts")
MAX_PAYLOAD = 1024 * 1024
MAX_CACHE = 4 * 1024 * 1024
_ID = re.compile(r"[a-f0-9]{32}\Z")


class StoreError(Exception):
    """Content-free failure with a closed reason, never a payload or path dump."""


class GenerationToken(Metadata):
    collection_id: OpaqueID
    item_id: OpaqueID
    collection_generation: Counter
    item_generation: Counter


def checked_id(value: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise StoreError("invalid_id")
    return value


def next_generation(value: int) -> int:
    if value >= MAX_COUNTER:
        raise StoreError("generation_exhausted")
    return value + 1


def bounded_bytes(value: bytes, cap: int) -> bytes:
    if type(value) is not bytes or not 0 < len(value) <= cap:
        raise StoreError("invalid_payload")
    return value


def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def require_sqlite_features() -> str:
    """Probe actual native behavior in MEMORY; never infer support from Python."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        version = conn.execute("SELECT sqlite_version()").fetchone()[0]
        if tuple(int(part) for part in version.split(".")) < (3, 42, 0):
            raise StoreError("sqlite_fts5_setup_required")
        conn.execute("PRAGMA secure_delete=ON")
        if conn.execute("PRAGMA secure_delete").fetchone()[0] != 1:
            raise StoreError("sqlite_fts5_setup_required")
        conn.execute(
            "CREATE VIRTUAL TABLE capability_probe USING fts5(body,"
            "tokenize='unicode61 remove_diacritics 2')"
        )
        conn.execute("INSERT INTO capability_probe VALUES(?)", ("ộ probecanary",))
        if (
            conn.execute(
                "SELECT count(*) FROM capability_probe WHERE capability_probe MATCH 'o'"
            ).fetchone()[0]
            != 1
        ):
            raise StoreError("sqlite_fts5_setup_required")
        conn.execute(
            "INSERT INTO capability_probe(capability_probe,rank) VALUES('secure-delete',1)"
        )
        if (
            conn.execute(
                "SELECT v FROM capability_probe_config WHERE k='secure-delete'"
            ).fetchone()[0]
            != 1
        ):
            raise StoreError("sqlite_fts5_setup_required")
        conn.execute("DELETE FROM capability_probe")
        if conn.execute("SELECT count(*) FROM capability_probe").fetchone()[0] != 0:
            raise StoreError("sqlite_fts5_setup_required")
        return version
    except (sqlite3.DatabaseError, ValueError, TypeError, IndexError):
        raise StoreError("sqlite_fts5_setup_required") from None
    finally:
        conn.close()


class Store:
    def __init__(self, root: Path, *, busy_ms: int = 50):
        if type(busy_ms) is not int or not 0 <= busy_ms <= 250:
            raise StoreError("invalid_busy_bound")
        require_sqlite_features()
        root = Path(root).absolute()
        for part in (root, *root.parents):
            if part.exists() and is_link(part):
                raise StoreError("unsafe_root")
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve(strict=True)
        self._root_identity = (self.root.stat().st_dev, self.root.stat().st_ino)
        self.busy_ms = busy_ms
        self._generation_memo: dict[tuple[str, str], GenerationToken] = {}
        self._check_root()
        db = self.root / "index.sqlite3"
        if db.exists() and (is_link(db) or not db.is_file()):
            raise StoreError("unsafe_database")
        with self.connection() as conn:
            for attempt in range(3):
                try:
                    if conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                        raise StoreError("wal_unavailable")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or attempt == 2:
                        raise StoreError("database_busy") from None
                    time.sleep(0.01)
        # Acquire the writer lock before reading the version. Another startup may
        # have migrated while this instance was waiting. Never use executescript:
        # its implicit commit would break atomic rollback across both migrations.
        with self.transaction() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise StoreError("unsupported_schema")
            for target in range(version + 1, 4):
                self._apply_migration(conn, target)

    @staticmethod
    def _apply_migration(conn, target: int) -> None:
        name = {1: "001_initial.sql", 2: "002_unicode_fts.sql", 3: "003_import_staging.sql"}[target]
        migration = Path(__file__).with_name("migrations") / name
        statement = ""
        for line in migration.read_text("utf-8").splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                conn.execute(statement)
                statement = ""
        if statement.strip():
            raise StoreError("invalid_migration")

    def _check_root(self) -> None:
        for part in (self.root, *self.root.parents):
            if is_link(part):
                raise StoreError("unsafe_root")
        current = self.root.stat()
        if (current.st_dev, current.st_ino) != self._root_identity:
            raise StoreError("changed_root")

    @contextmanager
    def connection(self):
        self._check_root()
        db = self.root / "index.sqlite3"
        for path in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
            try:
                info = path.lstat()
            except FileNotFoundError:
                # SQLite removes its transient sidecars when the last handle
                # closes. Absence is allowed; an unsafe observed entry is not.
                continue
            if (
                stat.S_ISLNK(info.st_mode)
                or bool(getattr(info, "st_file_attributes", 0) & 0x400)
                or not stat.S_ISREG(info.st_mode)
            ):
                raise StoreError("unsafe_database")
        conn = sqlite3.connect(db, timeout=self.busy_ms / 1000, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(f"PRAGMA busy_timeout={self.busy_ms}")
            conn.execute("PRAGMA secure_delete=ON")
            if conn.execute("PRAGMA secure_delete").fetchone()[0] != 1:
                raise StoreError("secure_delete_unavailable")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        with self.connection() as conn:
            for attempt in range(3):
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or attempt == 2:
                        raise StoreError("database_busy") from None
                    time.sleep(0.01)
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def create_collection(self, collection: Collection) -> None:
        collection = Collection.model_validate(collection)
        if collection.item_count or collection.encoded_bytes:
            raise StoreError("new_collection_not_empty")
        with self.transaction() as conn:
            try:
                conn.execute(
                    "INSERT INTO collections(collection_id,generation,cap) VALUES(?,?,?)",
                    (collection.collection_id, collection.generation, collection.cap),
                )
            except sqlite3.IntegrityError:
                raise StoreError("collection_exists") from None

    def collection(self, collection_id: str) -> Collection:
        checked_id(collection_id)
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM collections WHERE collection_id=?", (collection_id,)
            ).fetchone()
            if row is None:
                raise StoreError("collection_missing")
            return Collection.model_validate(dict(row))

    def admit(self, item: Item) -> GenerationToken:
        """Admit declared metadata only; image decoding is a separate obligation."""
        return self._admit_many((Item.model_validate(item),), require_unprocessed=False)[0]

    def admit_batch(self, items: tuple[Item, ...]) -> tuple[GenerationToken, ...]:
        """All-or-none initial metadata admission, not a decode or file-write proof."""
        if type(items) is not tuple or not 1 <= len(items) <= 30:
            raise StoreError("invalid_batch")
        return self._admit_many(
            tuple(Item.model_validate(item) for item in items), require_unprocessed=True
        )

    def _admit_many(
        self, items: tuple[Item, ...], *, require_unprocessed: bool, import_batch: str | None = None
    ) -> tuple[GenerationToken, ...]:
        first = items[0]
        if len({item.item_id for item in items}) != len(items):
            raise StoreError("item_exists")
        for item in items:
            if (item.collection_id, item.collection_generation) != (
                first.collection_id,
                first.collection_generation,
            ):
                raise StoreError("invalid_batch_scope")
            if item.state in {"deleting", "cleanup_pending"}:
                raise StoreError("invalid_initial_state")
            if require_unprocessed and (
                item.state != "pending"
                or item.source_grid_sha256 is not None
                or item.evidence_artifact_sha256 is not None
                or any(
                    s.status != "not_run" or s.item_generation != item.generation
                    for s in item.stages
                )
            ):
                raise StoreError("batch_not_unprocessed")
        total_bytes = sum(item.encoded_bytes for item in items)
        with self.transaction() as conn:
            collection = conn.execute(
                "SELECT * FROM collections WHERE collection_id=?", (first.collection_id,)
            ).fetchone()
            if collection is None or collection["generation"] != first.collection_generation:
                raise StoreError("generation_mismatch")
            if collection["item_count"] + len(items) > collection["cap"]:
                raise StoreError("collection_full")
            if collection["encoded_bytes"] + total_bytes > MAX_COLLECTION_BYTES:
                raise StoreError("collection_bytes_full")
            for item in items:
                if conn.execute(
                    "SELECT 1 FROM tombstones WHERE collection_id=? AND item_id=?",
                    (item.collection_id, item.item_id),
                ).fetchone():
                    raise StoreError("item_retired")
                if conn.execute(
                    "SELECT 1 FROM items WHERE collection_id=? AND item_id=?",
                    (item.collection_id, item.item_id),
                ).fetchone():
                    raise StoreError("item_exists")
            try:
                conn.executemany(
                    "INSERT INTO items VALUES(?,?,?,?,?,?)",
                    [
                        (
                            item.collection_id,
                            item.item_id,
                            item.generation,
                            item.state,
                            item.encoded_bytes,
                            item.model_dump_json(),
                        )
                        for item in items
                    ],
                )
            except sqlite3.IntegrityError:
                raise StoreError("item_exists") from None
            if import_batch is not None:
                conn.execute(
                    "INSERT INTO import_batches(batch_id,collection_id,member_count) VALUES(?,?,?)",
                    (import_batch, first.collection_id, len(items)),
                )
                conn.executemany(
                    "INSERT INTO import_members VALUES(?,?,?)",
                    [(import_batch, i.collection_id, i.item_id) for i in items],
                )
            conn.execute(
                "UPDATE collections SET item_count=item_count+?,encoded_bytes=encoded_bytes+? "
                "WHERE collection_id=?",
                (len(items), total_bytes, first.collection_id),
            )
            tokens = tuple(
                GenerationToken(
                    collection_id=item.collection_id,
                    item_id=item.item_id,
                    collection_generation=item.collection_generation,
                    item_generation=item.generation,
                )
                for item in items
            )
        return tokens

    def begin_import(self, items: tuple[Item, ...]) -> tuple[str, tuple[GenerationToken, ...]]:
        """Reserve the whole decoded batch and its durable visibility barrier atomically."""
        if type(items) is not tuple or not 1 <= len(items) <= 30:
            raise StoreError("invalid_batch")
        batch_id = uuid.uuid4().hex
        tokens = self._admit_many(
            tuple(Item.model_validate(i) for i in items),
            require_unprocessed=True,
            import_batch=batch_id,
        )
        return batch_id, tokens

    def complete_import(self, batch_id: str, tokens: tuple[GenerationToken, ...]) -> None:
        """Publish every member together, only after verified original/decode writes."""
        checked_id(batch_id)
        if (
            type(tokens) is not tuple
            or not 1 <= len(tokens) <= 30
            or not all(isinstance(t, GenerationToken) for t in tokens)
        ):
            raise StoreError("invalid_batch")
        tokens = tuple(GenerationToken.model_validate(t) for t in tokens)
        with self.transaction() as conn:
            batch = conn.execute(
                "SELECT * FROM import_batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            members = {
                (r[0], r[1])
                for r in conn.execute(
                    "SELECT collection_id,item_id FROM import_members WHERE batch_id=?", (batch_id,)
                )
            }
            if (
                batch is None
                or batch["status"] != "staging"
                or len(members) != batch["member_count"]
                or members != {(t.collection_id, t.item_id) for t in tokens}
                or len(tokens) != len(members)
            ):
                raise StoreError("import_incomplete")
            for token in tokens:
                row = self._live(conn, token)
                item = Item.model_validate_json(row["metadata"])
                if item.state != "partial" or item.source_grid_sha256 is None:
                    raise StoreError("import_incomplete")
                original = conn.execute(
                    "SELECT * FROM owned_files WHERE collection_id=? AND item_id=? "
                    "AND object_id=? AND role='original' AND state='ready'",
                    (token.collection_id, token.item_id, item.source_object_id),
                ).fetchone()
                if original is None:
                    raise StoreError("import_incomplete")
                self._verified_file(
                    self.object_path(token.collection_id, token.item_id, item.source_object_id),
                    original,
                )
            conn.execute("DELETE FROM import_batches WHERE batch_id=?", (batch_id,))

    @staticmethod
    def _published(conn, token: GenerationToken) -> None:
        if conn.execute(
            "SELECT 1 FROM import_members WHERE collection_id=? AND item_id=?",
            (token.collection_id, token.item_id),
        ).fetchone():
            raise StoreError("import_incomplete")

    @staticmethod
    def _live(conn, token: GenerationToken):
        token = GenerationToken.model_validate(token)
        row = conn.execute(
            "SELECT i.*,c.generation AS cg FROM items i JOIN collections c "
            "USING(collection_id) WHERE i.collection_id=? AND i.item_id=?",
            (token.collection_id, token.item_id),
        ).fetchone()
        if (
            row is None
            or row["state"] in {"deleting", "cleanup_pending"}
            or row["generation"] != token.item_generation
            or row["cg"] != token.collection_generation
        ):
            raise StoreError("generation_mismatch")
        return row

    def token(self, collection_id: str, item_id: str) -> GenerationToken:
        checked_id(collection_id)
        checked_id(item_id)
        with self.connection() as conn:
            row = conn.execute(
                "SELECT i.generation,c.generation cg,i.state FROM items i JOIN collections c "
                "USING(collection_id) WHERE i.collection_id=? AND i.item_id=?",
                (collection_id, item_id),
            ).fetchone()
            if row is None or row["state"] in {"deleting", "cleanup_pending"}:
                raise StoreError("item_unavailable")
            token = GenerationToken(
                collection_id=collection_id,
                item_id=item_id,
                item_generation=row["generation"],
                collection_generation=row["cg"],
            )
            self._published(conn, token)
            self._generation_memo[(collection_id, item_id)] = token
            return token

    def item(self, token: GenerationToken) -> Item:
        with self.transaction() as conn:
            row = self._live(conn, token)
            self._published(conn, token)
            data = Item.model_validate_json(row["metadata"]).model_dump()
            data["collection_generation"] = row["cg"]
            return Item.model_validate(data)

    def list_items(self, collection_id: str) -> tuple[Item, ...]:
        """Visible metadata in one bounded snapshot, without source content."""
        checked_id(collection_id)
        with self.transaction() as conn:
            collection = conn.execute(
                "SELECT generation FROM collections WHERE collection_id=?", (collection_id,)
            ).fetchone()
            if collection is None:
                raise StoreError("collection_missing")
            rows = conn.execute(
                "SELECT metadata FROM items i WHERE collection_id=? "
                "AND state NOT IN ('deleting','cleanup_pending') "
                "AND NOT EXISTS (SELECT 1 FROM import_members m WHERE "
                "m.collection_id=i.collection_id AND m.item_id=i.item_id) "
                "ORDER BY item_id LIMIT 31",
                (collection_id,),
            ).fetchall()
            if len(rows) > 30:
                raise StoreError("collection_full")
            items = []
            for row in rows:
                data = Item.model_validate_json(row["metadata"]).model_dump()
                data["collection_generation"] = collection["generation"]
                items.append(Item.model_validate(data))
            return tuple(items)

    def publish_stage(
        self,
        token: GenerationToken,
        expected_revision: int,
        stage_name: str,
        updated: Item,
        payload_writes: tuple[tuple[str, str, bytes], ...] = (),
        fts_writes: tuple[tuple[str, str, str], ...] = (),
    ) -> Item:
        """Commit one stage and its projections; adapters validate actual outputs.

        Completed output is immutable within a generation. Reindex by explicit
        delete/reimport. Generic put APIs are not a stage publication protocol.
        """
        tables = {
            "decode": {"content"},
            "ocr": {"content", "lines", "words"},
            "caption": {"captions"},
            "text_embeddings": {"spaces", "vectors"},
            "image_embeddings": {"spaces", "vectors"},
        }
        fts_tables = {"ocr": {"item_fts", "line_fts"}, "caption": {"item_fts"}}
        if type(stage_name) is not str or stage_name not in tables:
            raise StoreError("invalid_stage")
        if type(expected_revision) is not int or not 0 <= expected_revision < MAX_COUNTER:
            raise StoreError("invalid_revision")
        updated = Item.model_validate(updated)
        if updated.state in {"deleting", "cleanup_pending"}:
            raise StoreError("invalid_stage_state")
        if (
            type(payload_writes) is not tuple
            or type(fts_writes) is not tuple
            or len(payload_writes) + len(fts_writes) > 32768
        ):
            raise StoreError("invalid_stage_writes")
        cells = set()
        total_bytes = 0
        for writes, allowed, text in (
            (payload_writes, tables[stage_name], False),
            (fts_writes, fts_tables.get(stage_name, set()), True),
        ):
            for cell in writes:
                if type(cell) is not tuple or len(cell) != 3:
                    raise StoreError("invalid_stage_writes")
                table, row_id, value = cell
                if type(table) is not str or table not in allowed:
                    raise StoreError("invalid_table")
                checked_id(row_id)
                if (table, row_id) in cells:
                    raise StoreError("duplicate_stage_row")
                cells.add((table, row_id))
                if text:
                    if type(value) is not str:
                        raise StoreError("invalid_payload")
                    try:
                        value = value.encode("utf-8")
                    except UnicodeEncodeError:
                        raise StoreError("invalid_payload") from None
                total_bytes += len(bounded_bytes(value, MAX_PAYLOAD))
        if total_bytes > 32 * MAX_PAYLOAD:
            raise StoreError("stage_bytes_exceeded")
        with self.transaction() as conn:
            row = self._live(conn, token)
            before = Item.model_validate_json(row["metadata"]).model_dump()
            before["collection_generation"] = row["cg"]
            old = Item.model_validate(before)
            if old.revision != expected_revision or updated.revision != expected_revision + 1:
                raise StoreError("revision_mismatch")
            previous = {s.stage: s for s in old.stages}[stage_name]
            following = {s.stage: s for s in updated.stages}[stage_name]
            if previous.status in {"ready", "partial"}:
                raise StoreError("stage_output_immutable")
            if following.item_generation != token.item_generation:
                raise StoreError("generation_mismatch")
            mutable = {"revision", "state", "stages"}
            if stage_name == "decode":
                mutable.add("source_grid_sha256")
            if stage_name == "ocr":
                mutable.add("evidence_artifact_sha256")
            after = updated.model_dump()
            if any(before[k] != after[k] for k in before if k not in mutable) or any(
                a != b
                for a, b in zip(old.stages, updated.stages, strict=True)
                if a.stage != stage_name
            ):
                raise StoreError("stage_identity_mismatch")
            if tuple(s.stage for s in old.stages) != tuple(s.stage for s in updated.stages):
                raise StoreError("stage_identity_mismatch")
            has_output = following.status in {"ready", "partial"}
            if not has_output and cells:
                raise StoreError("non_output_stage_writes")
            if has_output:
                original = conn.execute(
                    "SELECT * FROM owned_files WHERE collection_id=? AND item_id=? "
                    "AND role='original'",
                    (token.collection_id, token.item_id),
                ).fetchone()
                if (
                    original is None
                    or original["state"] != "ready"
                    or original["object_id"] != old.source_object_id
                    or original["expected_sha256"] != old.original_content_sha256
                    or original["size_bytes"] != old.encoded_bytes
                ):
                    raise StoreError("file_unavailable")
                try:
                    self._verified_file(
                        self.object_path(token.collection_id, token.item_id, old.source_object_id),
                        original,
                    )
                except OSError:
                    raise StoreError("file_unavailable") from None
            slot = hashlib.sha256(stage_name.encode("ascii")).hexdigest()[:32]
            prior = conn.execute(
                "SELECT payload,generation FROM stages WHERE collection_id=? AND item_id=? "
                "AND row_id=?",
                (token.collection_id, token.item_id, slot),
            ).fetchone()
            if prior is not None and (
                bytes(prior["payload"]) != previous.model_dump_json().encode("utf-8")
                or prior["generation"] != token.item_generation
            ):
                raise StoreError("stage_row_collision")
            for writes in (payload_writes, fts_writes):
                for table, row_id, value in writes:
                    if conn.execute(
                        f"SELECT 1 FROM {table} WHERE collection_id=? AND item_id=? AND row_id=?",
                        (token.collection_id, token.item_id, row_id),
                    ).fetchone():
                        raise StoreError("stage_row_collision")
                    conn.execute(
                        f"INSERT INTO {table} VALUES(?,?,?,?,?)",
                        (token.collection_id, token.item_id, row_id, token.item_generation, value),
                    )
            conn.execute(
                "INSERT OR REPLACE INTO stages VALUES(?,?,?,?,?)",
                (
                    token.collection_id,
                    token.item_id,
                    slot,
                    token.item_generation,
                    following.model_dump_json().encode("utf-8"),
                ),
            )
            conn.execute(
                "UPDATE items SET state=?,metadata=? WHERE collection_id=? AND item_id=?",
                (updated.state, updated.model_dump_json(), token.collection_id, token.item_id),
            )
            conn.execute("DELETE FROM cache_entries WHERE collection_id=?", (token.collection_id,))
        return updated

    def put(self, table: str, token: GenerationToken, row_id: str, payload: bytes) -> None:
        if table not in PAYLOAD_TABLES:
            raise StoreError("invalid_table")
        checked_id(row_id)
        bounded_bytes(payload, MAX_PAYLOAD)
        with self.transaction() as conn:
            self._live(conn, token)
            conn.execute(
                f"INSERT OR REPLACE INTO {table} VALUES(?,?,?,?,?)",
                (token.collection_id, token.item_id, row_id, token.item_generation, payload),
            )

    def get(self, table: str, token: GenerationToken, row_id: str) -> bytes | None:
        if table not in PAYLOAD_TABLES:
            raise StoreError("invalid_table")
        checked_id(row_id)
        with self.transaction() as conn:
            self._live(conn, token)
            self._published(conn, token)
            row = conn.execute(
                f"SELECT payload FROM {table} WHERE collection_id=? AND item_id=? "
                "AND row_id=? AND generation=?",
                (token.collection_id, token.item_id, row_id, token.item_generation),
            ).fetchone()
            # SQLite BLOB affinity does not exclude TEXT/INTEGER/REAL rows.
            # Never coerce an integer with bytes(n), or accept oversized data.
            return None if row is None else bounded_bytes(row[0], MAX_PAYLOAD)

    def put_fts(self, table: str, token: GenerationToken, row_id: str, body: str) -> None:
        if table not in FTS_TABLES:
            raise StoreError("invalid_table")
        checked_id(row_id)
        if type(body) is not str:
            raise StoreError("invalid_payload")
        bounded_bytes(body.encode("utf-8"), MAX_PAYLOAD)
        with self.transaction() as conn:
            self._live(conn, token)
            conn.execute(
                f"DELETE FROM {table} WHERE collection_id=? AND item_id=? AND row_id=?",
                (token.collection_id, token.item_id, row_id),
            )
            conn.execute(
                f"INSERT INTO {table} VALUES(?,?,?,?,?)",
                (token.collection_id, token.item_id, row_id, token.item_generation, body),
            )

    def put_cache(self, cache_id: str, dependencies: tuple[GenerationToken, ...], payload: bytes):
        checked_id(cache_id)
        bounded_bytes(payload, MAX_CACHE)
        if (
            type(dependencies) is not tuple
            or not 1 <= len(dependencies) <= 30
            or not all(isinstance(d, GenerationToken) for d in dependencies)
        ):
            raise StoreError("invalid_dependencies")
        dependencies = tuple(GenerationToken.model_validate(d) for d in dependencies)
        if len({d.item_id for d in dependencies}) != len(dependencies):
            raise StoreError("invalid_dependencies")
        first = dependencies[0]
        with self.transaction() as conn:
            self._cache_writable(conn, first.collection_id)
            for token in dependencies:
                self._live(conn, token)
                self._published(conn, token)
                if (token.collection_id, token.collection_generation) != (
                    first.collection_id,
                    first.collection_generation,
                ):
                    raise StoreError("invalid_dependencies")
            conn.execute(
                "DELETE FROM cache_entries WHERE collection_id=? AND cache_id=?",
                (first.collection_id, cache_id),
            )
            conn.execute(
                "INSERT INTO cache_entries VALUES(?,?,?,?)",
                (first.collection_id, cache_id, first.collection_generation, payload),
            )
            conn.executemany(
                "INSERT INTO cache_dependencies VALUES(?,?,?,?)",
                [(t.collection_id, cache_id, t.item_id, t.item_generation) for t in dependencies],
            )

    @staticmethod
    def _cache_writable(conn, collection_id: str) -> None:
        if conn.execute(
            "SELECT 1 FROM delete_jobs WHERE collection_id=? AND status!='deleted' LIMIT 1",
            (collection_id,),
        ).fetchone():
            raise StoreError("cleanup_pending")

    def get_cache(self, cache_id: str, token: GenerationToken) -> bytes | None:
        checked_id(cache_id)
        with self.transaction() as conn:
            self._live(conn, token)
            self._published(conn, token)
            row = conn.execute(
                "SELECT payload FROM cache_entries WHERE collection_id=? AND cache_id=? "
                "AND collection_generation=?",
                (token.collection_id, cache_id, token.collection_generation),
            ).fetchone()
            if row is None:
                return None
            deps = conn.execute(
                "SELECT * FROM cache_dependencies WHERE collection_id=? AND cache_id=?",
                (token.collection_id, cache_id),
            ).fetchall()
            if not deps:
                raise StoreError("invalid_dependencies")
            for dep in deps:
                self._live(
                    conn,
                    GenerationToken(
                        collection_id=token.collection_id,
                        item_id=dep["item_id"],
                        item_generation=dep["item_generation"],
                        collection_generation=token.collection_generation,
                    ),
                )
            return bytes(row[0])

    def object_path(self, collection_id: str, item_id: str, object_id: str) -> Path:
        self._check_root()
        for value in (collection_id, item_id, object_id):
            checked_id(value)
        path = self.root / "objects" / collection_id / item_id / object_id
        for part in (path, path.parent, path.parent.parent, path.parent.parent.parent):
            if part.exists() and is_link(part):
                raise StoreError("unsafe_object")
        if not path.resolve().is_relative_to(self.root):
            raise StoreError("unsafe_object")
        return path

    def reserve_file(
        self,
        token: GenerationToken,
        role: Literal["original", "thumbnail", "derived", "cache"],
        payload: bytes,
    ) -> str:
        """Durable intent first. An interrupted writer cannot leave an untracked object."""
        if role not in {"original", "thumbnail", "derived", "cache"}:
            raise StoreError("invalid_role")
        bounded_bytes(payload, 8 * 1024 * 1024)
        object_id = uuid.uuid4().hex
        with self.transaction() as conn:
            row = self._live(conn, token)
            if role == "cache":
                self._cache_writable(conn, token.collection_id)
            if role == "original":
                item = Item.model_validate_json(row["metadata"])
                if (
                    len(payload) != item.encoded_bytes
                    or hashlib.sha256(payload).hexdigest() != item.original_content_sha256
                ):
                    raise StoreError("source_identity_mismatch")
                object_id = item.source_object_id
            try:
                conn.execute(
                    "INSERT INTO owned_files VALUES(?,?,?,?,?,?,NULL,NULL,NULL,'reserved')",
                    (
                        token.collection_id,
                        token.item_id,
                        object_id,
                        role,
                        hashlib.sha256(payload).hexdigest(),
                        len(payload),
                    ),
                )
            except sqlite3.IntegrityError:
                raise StoreError("file_exists") from None
        return object_id

    def finish_file(self, token: GenerationToken, object_id: str, payload: bytes) -> None:
        checked_id(object_id)
        bounded_bytes(payload, 8 * 1024 * 1024)
        with self.transaction() as conn:
            self._live(conn, token)
            row = conn.execute(
                "SELECT * FROM owned_files WHERE collection_id=? AND item_id=? AND object_id=?",
                (token.collection_id, token.item_id, object_id),
            ).fetchone()
            if (
                row is None
                or row["state"] != "reserved"
                or len(payload) != row["size_bytes"]
                or hashlib.sha256(payload).hexdigest() != row["expected_sha256"]
            ):
                raise StoreError("file_identity_mismatch")
            path = self.object_path(token.collection_id, token.item_id, object_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.object_path(token.collection_id, token.item_id, object_id)
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_BINARY", 0)
            )
            try:
                with os.fdopen(os.open(path, flags, 0o600), "wb") as output:
                    output.write(payload)
                    output.flush()
                    os.fsync(output.fileno())
                info = path.stat(follow_symlinks=False)
            except OSError:
                raise StoreError("file_write_failed") from None
            conn.execute(
                "UPDATE owned_files SET device=?,inode=?,mtime_ns=?,state='ready' "
                "WHERE collection_id=? AND item_id=? AND object_id=?",
                (
                    str(info.st_dev),
                    str(info.st_ino),
                    info.st_mtime_ns,
                    token.collection_id,
                    token.item_id,
                    object_id,
                ),
            )

    def put_file(self, token: GenerationToken, role: str, payload: bytes) -> str:
        object_id = self.reserve_file(token, role, payload)
        self.finish_file(token, object_id, payload)
        return object_id

    @staticmethod
    def _verified_file(path: Path, row) -> bytes:
        if is_link(path):
            raise StoreError("unsafe_object")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        with os.fdopen(os.open(path, flags), "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != row["size_bytes"]:
                raise StoreError("file_identity_mismatch")
            if row["inode"] is not None and (
                str(info.st_dev),
                str(info.st_ino),
                info.st_mtime_ns,
            ) != (
                row["device"],
                row["inode"],
                row["mtime_ns"],
            ):
                raise StoreError("file_identity_mismatch")
            payload = source.read(row["size_bytes"] + 1)
        if hashlib.sha256(payload).hexdigest() != row["expected_sha256"]:
            raise StoreError("file_identity_mismatch")
        current = path.stat(follow_symlinks=False)
        if (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) != (
            info.st_dev,
            info.st_ino,
            info.st_mtime_ns,
            info.st_size,
        ):
            raise StoreError("file_identity_mismatch")
        return payload

    def read_file(self, token: GenerationToken, object_id: str) -> bytes:
        checked_id(object_id)
        with self.transaction() as conn:
            self._live(conn, token)
            self._published(conn, token)
            row = conn.execute(
                "SELECT * FROM owned_files WHERE collection_id=? AND item_id=? AND object_id=?",
                (token.collection_id, token.item_id, object_id),
            ).fetchone()
            if row is None or row["state"] != "ready":
                raise StoreError("file_unavailable")
            try:
                return self._verified_file(
                    self.object_path(token.collection_id, token.item_id, object_id), row
                )
            except OSError:
                raise StoreError("file_unavailable") from None
