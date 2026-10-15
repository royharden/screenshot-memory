# Local storage and deletion core

This module stores S7-owned metadata, bounded opaque payloads and managed files.
It does not decode an image, recognize text, caption, embed, search, rank, call a
provider or validate a model output. Payload row names reserve stores for those
later integrations. Synthetic tests exercise bytes and records only.

`Store(private_root)` explicitly creates a SQLite database in WAL mode and runs
the immutable version1 SQL migration followed by version2. Both run within one
writer transaction, with the current version read after obtaining the lock.
Version2 rebuilds both FTS tables using `unicode61 remove_diacritics 2`, retaining
only current visible rows and their row IDs. Failure rolls back the schema,
version and rows together. Non-FTS stores and deletion journals are preserved.
Future schema versions refuse startup. SQLite core secure-delete is enabled on
each connection; version2 enables the FTS5 secure-delete setting on both tables.
These settings do not extend the logical deletion guarantee to forensic erasure.
Importing the module performs no IO. The root
must be exclusively managed private application storage, outside a repository.
Never point it at a shared directory, user gallery or attacker-writable folder.
No caller-supplied filesystem paths are accepted by object APIs. Objects use
opaque collection/item/object handles below `objects/`. Static symlinks,
Windows reparse points, replaced roots and unexpected file identities are
refused. Files are not shared between collections, including identical images.
This is not protection against a privileged process concurrently replacing
filesystem components between OS operations.

Admission validates strict Item/Collection records and atomically enforces the
collection item cap (maximum30), declared8MiB/image and100MiB/gallery byte caps,
and declared20M pixel cap. These are metadata checks; actual bounded decoding
remains the ingest adapter's obligation. An original managed file must also
match the admitted raw encoded hash and size. It cannot establish decode validity.

Every read and write rechecks both item and collection generations inside a
SQLite transaction. Transactions use `BEGIN IMMEDIATE`, at most three attempts,
bounded busy time (default50ms, maximum250ms) and10ms inter-attempt pauses.
Metadata generation memoization contains no payloads and confers no authority.
Payloads are at most1MiB/row, database caches4MiB/entry, managed files8MiB/file.
These per-record bounds do not impose a total derived-data disk quota.

Managed files use a durable reserved intent before a second transaction checks
the generation, exclusively creates the object and records its actual OS file
identity. A stale producer cannot finish after deletion marks the item. An
interrupted partial write whose bytes/identity cannot be verified remains pending
for explicit operator reconciliation; it is never silently removed as an owned
complete object. No recursive directory removal is performed.

`Deleter.begin` first commits a deleting state, increments item and collection
generations, retires the item ID and journals owned object keys. All Store APIs
and visible FTS views hide the item immediately. Collection cache entries and
dependencies are invalidated conservatively; cache creation is held during a
pending deletion in that collection. Other collections remain independent.
Existing sibling work must obtain a fresh collection token. Originals,
thumbnails, derived files and collection cache files are captured for cleanup.

`resume` explicitly purges content, native-line/word payload slots, captions,
feature spaces, vectors, stages, both FTS tables, database caches/dependencies
and owned-file records. It verifies files against their captured identity,
size and hash, unlinks only verified owned files and checks for unexpected
objects in the target namespace. A missing file is counted as absent. A changed
file, unsafe path or permission failure is retained and yields cleanup_pending.
The private durable journal holds keys and verification metadata, never source
content, captions, vectors or raw error strings. Its object manifests are removed
on completion; the retained tombstone/job contains opaque IDs, counts,
generations, status and timing only. Quota is released exactly once on completion.

Completion additionally requires every enumerated logical store to be clear,
all planned files absent and a successful bounded WAL TRUNCATE checkpoint. An
active SQLite snapshot reader can prevent the checkpoint and keeps the receipt
pending until a retry after that reader closes. `recover` processes at most30
pending jobs per call after restart. Repeated delete/resume returns the same
completed operation and verification timestamp. Missing items yield not_found,
never a completed deletion claim. A schema-valid DeleteReceipt declaration is
not proof that these operations executed.

The guarantee is logical deletion from these enumerated stores and verified
managed objects at the recorded time. It is not forensic erasure of free pages,
backups, SSD remnants, external copies or bytes already returned to a caller.
A content-free completion journal transaction can itself write WAL metadata
after the checkpoint; the API does not promise a permanently empty WAL file.
Raw SQL handles or external open snapshots are not revocable application APIs.

The same owned modules, metadata dependency and SQL migration must travel
together in a detached consumer. The separate keyword search module uses these
generation boundaries; see [keyword-search.md](keyword-search.md). Later feature adapters must use the same
generation and cache-dependency boundaries rather than writing tables or paths
directly. No executable foreign canonical module has been supplied by this core.
