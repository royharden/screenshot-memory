"""Logical all-store deletion with durable intent and bounded restart cleanup.

No forensic physical-erasure claim: SQLite free pages, backups and data already
returned to a caller are outside this interface. Missing proof stays pending.
"""

import json
import time
import uuid
from typing import Literal, Self

from pydantic import model_validator

from screenshot_memory.contracts import Counter, Metadata, OpaqueID

from .storage import (
    FTS_TABLES,
    PAYLOAD_TABLES,
    Store,
    StoreError,
    checked_id,
    is_link,
    next_generation,
)

STORES = (
    *PAYLOAD_TABLES,
    *FTS_TABLES,
    "cache_entries",
    "cache_dependencies",
    "owned_files",
    "import_members",
    "items",
)
DeleteReason = Literal[
    "database_busy",
    "file_unavailable",
    "unsafe_object",
    "file_identity_mismatch",
    "unexpected_objects",
    "stores_remaining",
    "checkpoint_busy",
]


class DeleteReceipt(Metadata):
    collection_id: OpaqueID
    item_id: OpaqueID
    operation_id: OpaqueID | None
    status: Literal["deleted", "cleanup_pending", "not_found"]
    item_generation: Counter | None
    collection_generation: Counter | None
    files_planned: Counter = 0
    files_absent: Counter = 0
    stores_verified: tuple[str, ...] = ()
    wal_checkpointed: bool = False
    verified_ns: Counter | None = None
    reasons: tuple[DeleteReason, ...] = ()

    @model_validator(mode="after")
    def evidence_coherence(self) -> Self:
        if self.files_absent > self.files_planned:
            raise ValueError("absent count exceeds planned files")
        if self.status == "not_found":
            if (
                self.operation_id is not None
                or self.item_generation is not None
                or self.collection_generation is not None
                or self.files_planned
                or self.files_absent
                or self.stores_verified
                or self.wal_checkpointed
                or self.verified_ns is not None
                or self.reasons
            ):
                raise ValueError("not_found is not a deletion proof")
        elif (
            self.operation_id is None
            or self.item_generation is None
            or self.collection_generation is None
        ):
            raise ValueError("deletion requires durable identity")
        elif self.status == "deleted":
            if (
                self.files_absent != self.files_planned
                or self.stores_verified != STORES
                or not self.wal_checkpointed
                or self.verified_ns is None
                or self.reasons
            ):
                raise ValueError("completed deletion needs all enumerated checks")
        elif (
            self.stores_verified
            or self.wal_checkpointed
            or self.verified_ns is not None
            or not self.reasons
        ):
            raise ValueError("pending deletion cannot assert completion")
        return self


class Deleter:
    def __init__(self, store: Store):
        self.store = store

    def begin(self, collection_id: str, item_id: str) -> DeleteReceipt:
        """Commit hiding/generation advance before unlink or expensive cleanup."""
        checked_id(collection_id)
        checked_id(item_id)
        with self.store.transaction() as conn:
            job = conn.execute(
                "SELECT * FROM delete_jobs WHERE collection_id=? AND item_id=?",
                (collection_id, item_id),
            ).fetchone()
            if job is not None:
                return self._receipt(job)
            row = conn.execute(
                "SELECT i.*,c.generation cg FROM items i JOIN collections c "
                "USING(collection_id) WHERE i.collection_id=? AND i.item_id=?",
                (collection_id, item_id),
            ).fetchone()
            if row is None:
                return DeleteReceipt(
                    collection_id=collection_id,
                    item_id=item_id,
                    operation_id=None,
                    status="not_found",
                    item_generation=None,
                    collection_generation=None,
                )
            generation = next_generation(row["generation"])
            collection_generation = next_generation(row["cg"])
            operation_id = uuid.uuid4().hex
            conn.execute(
                "UPDATE items SET generation=?,state='deleting' "
                "WHERE collection_id=? AND item_id=?",
                (generation, collection_id, item_id),
            )
            conn.execute(
                "UPDATE collections SET generation=? WHERE collection_id=?",
                (collection_generation, collection_id),
            )
            conn.execute(
                "INSERT INTO tombstones VALUES(?,?,?)", (collection_id, item_id, generation)
            )
            conn.execute(
                "INSERT INTO delete_jobs(operation_id,collection_id,item_id,item_generation,"
                "collection_generation,source_bytes,status,created_ns,reasons) "
                "VALUES(?,?,?,?,?,?,'marked',?,?)",
                (
                    operation_id,
                    collection_id,
                    item_id,
                    generation,
                    collection_generation,
                    row["encoded_bytes"],
                    time.time_ns(),
                    '["stores_remaining"]',
                ),
            )
            conn.execute(
                "INSERT INTO delete_files SELECT ?,collection_id,item_id,object_id,role,"
                "expected_sha256,size_bytes,device,inode,mtime_ns,0 FROM owned_files "
                "WHERE collection_id=? AND (item_id=? OR role='cache')",
                (operation_id, collection_id, item_id),
            )
            count = conn.execute(
                "SELECT COUNT(*) FROM delete_files WHERE operation_id=?", (operation_id,)
            ).fetchone()[0]
            conn.execute(
                "UPDATE delete_jobs SET files_planned=? WHERE operation_id=?", (count, operation_id)
            )
            # Collection-wide invalidation is conservative. No payload is cached in memory.
            conn.execute("DELETE FROM cache_entries WHERE collection_id=?", (collection_id,))
            self.store._generation_memo.clear()
            job = conn.execute(
                "SELECT * FROM delete_jobs WHERE operation_id=?", (operation_id,)
            ).fetchone()
            return self._receipt(job)

    @staticmethod
    def _receipt(job) -> DeleteReceipt:
        done = job["status"] == "deleted"
        return DeleteReceipt(
            collection_id=job["collection_id"],
            item_id=job["item_id"],
            operation_id=job["operation_id"],
            status="deleted" if done else "cleanup_pending",
            item_generation=job["item_generation"],
            collection_generation=job["collection_generation"],
            files_planned=job["files_planned"],
            files_absent=job["files_absent"],
            stores_verified=STORES if done else (),
            wal_checkpointed=done,
            verified_ns=job["verified_ns"] if done else None,
            reasons=() if done else tuple(json.loads(job["reasons"])),
        )

    def _pending(self, operation_id: str, reasons: tuple[DeleteReason, ...]) -> DeleteReceipt:
        with self.store.transaction() as conn:
            current = conn.execute(
                "SELECT * FROM delete_jobs WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if current["status"] == "deleted":
                return self._receipt(current)
            conn.execute(
                "UPDATE delete_jobs SET status='cleanup_pending',reasons=? WHERE operation_id=?",
                (json.dumps(sorted(set(reasons))), operation_id),
            )
            conn.execute(
                "UPDATE items SET state='cleanup_pending' WHERE (collection_id,item_id) IN "
                "(SELECT collection_id,item_id FROM delete_jobs WHERE operation_id=?)",
                (operation_id,),
            )
            job = conn.execute(
                "SELECT * FROM delete_jobs WHERE operation_id=?", (operation_id,)
            ).fetchone()
            return self._receipt(job)

    def _unlink(self, file) -> None:
        path = self.store.object_path(file["collection_id"], file["item_id"], file["object_id"])
        if not path.exists() and not path.is_symlink():
            return
        self.store._verified_file(path, file)
        # This store assumes an exclusively managed private root. Verify again
        # immediately before unlink; unexpected identities are retained, pending.
        self.store.object_path(file["collection_id"], file["item_id"], file["object_id"])
        path.unlink()
        if path.exists() or path.is_symlink():
            raise StoreError("file_unavailable")

    def _unexpected_objects(self, collection_id: str, item_id: str) -> bool:
        probe = self.store.object_path(collection_id, item_id, "0" * 32)
        parent = probe.parent
        if not parent.exists():
            return False
        if is_link(parent):
            return True
        # Only an empty target namespace can complete. No recursive removal.
        return next(parent.iterdir(), None) is not None

    def _purge(self, conn, job) -> None:
        params = (job["collection_id"], job["item_id"])
        for table in (*PAYLOAD_TABLES, *FTS_TABLES, "import_members"):
            conn.execute(f"DELETE FROM {table} WHERE collection_id=? AND item_id=?", params)
        conn.execute(
            "DELETE FROM import_batches WHERE collection_id=? AND NOT EXISTS "
            "(SELECT 1 FROM import_members m WHERE m.batch_id=import_batches.batch_id)",
            (params[0],),
        )
        conn.execute("DELETE FROM cache_entries WHERE collection_id=?", (params[0],))
        conn.execute(
            "DELETE FROM owned_files WHERE collection_id=? AND (item_id=? OR role='cache')", params
        )

    @staticmethod
    def _stores_clear(conn, job) -> bool:
        params = (job["collection_id"], job["item_id"])
        for table in (*PAYLOAD_TABLES, *FTS_TABLES, "owned_files", "import_members"):
            if conn.execute(
                f"SELECT 1 FROM {table} WHERE collection_id=? AND item_id=? LIMIT 1", params
            ).fetchone():
                return False
        for table in ("cache_entries", "cache_dependencies"):
            if conn.execute(
                f"SELECT 1 FROM {table} WHERE collection_id=? LIMIT 1", (params[0],)
            ).fetchone():
                return False
        return True

    def _checkpoint(self) -> bool:
        for attempt in range(3):
            with self.store.connection() as conn:
                try:
                    busy, log, checkpointed = conn.execute(
                        "PRAGMA wal_checkpoint(TRUNCATE)"
                    ).fetchone()
                except Exception:
                    return False
            if busy == 0 and (log == 0 or log == checkpointed):
                return True
            if attempt != 2:
                time.sleep(0.01)
        return False

    def resume(self, operation_id: str) -> DeleteReceipt:
        checked_id(operation_id)
        try:
            return self._resume(operation_id)
        except StoreError as exc:
            if str(exc) not in {"database_busy", "stores_remaining"}:
                raise
            reason = str(exc)
            try:
                return self._pending(operation_id, (reason,))
            except StoreError:
                # The already committed mark is durable even if a later writer
                # prevents updating its diagnostic reason. Never say completed.
                with self.store.connection() as conn:
                    job = conn.execute(
                        "SELECT * FROM delete_jobs WHERE operation_id=?", (operation_id,)
                    ).fetchone()
                    if job is None:
                        raise StoreError("operation_missing") from None
                    if job["status"] == "deleted":
                        return self._receipt(job)
                    data = self._receipt(job).model_dump()
                    data["reasons"] = (reason,)
                    return DeleteReceipt.model_validate(data)

    def _resume(self, operation_id: str) -> DeleteReceipt:
        checked_id(operation_id)
        with self.store.connection() as conn:
            job = conn.execute(
                "SELECT * FROM delete_jobs WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if job is None:
                raise StoreError("operation_missing")
            if job["status"] == "deleted":
                return self._receipt(job)
            files = conn.execute(
                "SELECT * FROM delete_files WHERE operation_id=?", (operation_id,)
            ).fetchall()
        failures: list[DeleteReason] = []
        for file in files:
            try:
                self._unlink(file)
            except StoreError as exc:
                reason = str(exc)
                failures.append(
                    reason
                    if reason in {"unsafe_object", "file_identity_mismatch"}
                    else "file_unavailable"
                )
            except OSError:
                failures.append("file_unavailable")
            else:
                with self.store.transaction() as conn:
                    conn.execute(
                        "UPDATE delete_files SET absent=1 WHERE operation_id=? AND collection_id=? "
                        "AND item_id=? AND object_id=?",
                        (operation_id, file["collection_id"], file["item_id"], file["object_id"]),
                    )
        try:
            if self._unexpected_objects(job["collection_id"], job["item_id"]):
                failures.append("unexpected_objects")
        except (OSError, StoreError):
            failures.append("unsafe_object")
        # Purge logical content even when an OS handle prevents physical unlink.
        with self.store.transaction() as conn:
            job = conn.execute(
                "SELECT * FROM delete_jobs WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if job["status"] == "deleted":
                return self._receipt(job)
            self._purge(conn, job)
            absent = conn.execute(
                "SELECT COUNT(*) FROM delete_files WHERE operation_id=? AND absent=1",
                (operation_id,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE delete_jobs SET files_absent=? WHERE operation_id=?", (absent, operation_id)
            )
        if failures:
            return self._pending(operation_id, tuple(failures))
        if not self._checkpoint():
            return self._pending(operation_id, ("checkpoint_busy",))
        with self.store.transaction() as conn:
            # Re-read: another cleanup runner may have completed while checkpointing.
            job = conn.execute(
                "SELECT * FROM delete_jobs WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if job["status"] == "deleted":
                return self._receipt(job)
            if not self._stores_clear(conn, job):
                raise StoreError("stores_remaining")
            conn.execute(
                "DELETE FROM items WHERE collection_id=? AND item_id=?",
                (job["collection_id"], job["item_id"]),
            )
            if conn.execute(
                "SELECT 1 FROM items WHERE collection_id=? AND item_id=?",
                (job["collection_id"], job["item_id"]),
            ).fetchone():
                raise StoreError("stores_remaining")
            if not job["quota_released"]:
                conn.execute(
                    "UPDATE collections SET item_count=item_count-1,encoded_bytes=encoded_bytes-? "
                    "WHERE collection_id=?",
                    (job["source_bytes"], job["collection_id"]),
                )
            conn.execute("DELETE FROM delete_files WHERE operation_id=?", (operation_id,))
            conn.execute(
                "UPDATE delete_jobs SET status='deleted',verified_ns=?,"
                "reasons='[]',quota_released=1,"
                "source_bytes=0 WHERE operation_id=?",
                (time.time_ns(), operation_id),
            )
            result = self._receipt(
                conn.execute(
                    "SELECT * FROM delete_jobs WHERE operation_id=?", (operation_id,)
                ).fetchone()
            )
        self.store._generation_memo.clear()
        return result

    def delete(self, collection_id: str, item_id: str) -> DeleteReceipt:
        receipt = self.begin(collection_id, item_id)
        if receipt.status in {"not_found", "deleted"}:
            return receipt
        return self.resume(receipt.operation_id)

    def recover(self) -> tuple[DeleteReceipt, ...]:
        with self.store.connection() as conn:
            jobs = conn.execute(
                "SELECT operation_id FROM delete_jobs WHERE status!='deleted' "
                "ORDER BY created_ns LIMIT 30"
            ).fetchall()
        return tuple(self.resume(row[0]) for row in jobs)
