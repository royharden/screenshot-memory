CREATE TABLE import_batches (
    batch_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collections(collection_id),
    member_count INTEGER NOT NULL CHECK(member_count BETWEEN 1 AND 30),
    status TEXT NOT NULL DEFAULT 'staging' CHECK(status IN ('staging','aborting'))
);
CREATE TABLE import_members (
    batch_id TEXT NOT NULL REFERENCES import_batches(batch_id) ON DELETE CASCADE,
    collection_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    PRIMARY KEY(collection_id,item_id),
    FOREIGN KEY(collection_id,item_id) REFERENCES items ON DELETE CASCADE
);
DROP VIEW visible_item_fts;
DROP VIEW visible_line_fts;
CREATE VIEW visible_item_fts AS SELECT f.* FROM item_fts f JOIN items i
    ON f.collection_id=i.collection_id AND f.item_id=i.item_id
    AND f.generation=i.generation WHERE i.state NOT IN ('deleting','cleanup_pending')
    AND NOT EXISTS (SELECT 1 FROM import_members m
        WHERE m.collection_id=i.collection_id AND m.item_id=i.item_id);
CREATE VIEW visible_line_fts AS SELECT f.* FROM line_fts f JOIN items i
    ON f.collection_id=i.collection_id AND f.item_id=i.item_id
    AND f.generation=i.generation WHERE i.state NOT IN ('deleting','cleanup_pending')
    AND NOT EXISTS (SELECT 1 FROM import_members m
        WHERE m.collection_id=i.collection_id AND m.item_id=i.item_id);
PRAGMA user_version=3;
