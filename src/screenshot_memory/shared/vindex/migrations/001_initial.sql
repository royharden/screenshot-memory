CREATE TABLE collections (
    collection_id TEXT PRIMARY KEY,
    generation INTEGER NOT NULL CHECK(generation >= 0),
    cap INTEGER NOT NULL CHECK(cap BETWEEN 1 AND 30),
    item_count INTEGER NOT NULL DEFAULT 0 CHECK(item_count BETWEEN 0 AND cap),
    encoded_bytes INTEGER NOT NULL DEFAULT 0 CHECK(encoded_bytes BETWEEN 0 AND 104857600)
);
CREATE TABLE items (
    collection_id TEXT NOT NULL REFERENCES collections(collection_id),
    item_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK(generation >= 0),
    state TEXT NOT NULL CHECK(state IN ('pending','partial','ready','failed','deleting','cleanup_pending')),
    encoded_bytes INTEGER NOT NULL CHECK(encoded_bytes BETWEEN 1 AND 8388608),
    metadata TEXT NOT NULL,
    PRIMARY KEY(collection_id,item_id)
);
CREATE TABLE tombstones (
    collection_id TEXT NOT NULL REFERENCES collections(collection_id),
    item_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    PRIMARY KEY(collection_id,item_id)
);
CREATE TABLE content (
    collection_id TEXT NOT NULL,item_id TEXT NOT NULL,row_id TEXT NOT NULL,
    generation INTEGER NOT NULL,payload BLOB NOT NULL,
    PRIMARY KEY(collection_id,item_id,row_id),
    FOREIGN KEY(collection_id,item_id) REFERENCES items ON DELETE CASCADE
);
CREATE TABLE lines (
    collection_id TEXT NOT NULL,item_id TEXT NOT NULL,row_id TEXT NOT NULL,
    generation INTEGER NOT NULL,payload BLOB NOT NULL,
    PRIMARY KEY(collection_id,item_id,row_id),
    FOREIGN KEY(collection_id,item_id) REFERENCES items ON DELETE CASCADE
);
CREATE TABLE words (
    collection_id TEXT NOT NULL,item_id TEXT NOT NULL,row_id TEXT NOT NULL,
    generation INTEGER NOT NULL,payload BLOB NOT NULL,
    PRIMARY KEY(collection_id,item_id,row_id),
    FOREIGN KEY(collection_id,item_id) REFERENCES items ON DELETE CASCADE
);
CREATE TABLE captions (
    collection_id TEXT NOT NULL,item_id TEXT NOT NULL,row_id TEXT NOT NULL,
    generation INTEGER NOT NULL,payload BLOB NOT NULL,
    PRIMARY KEY(collection_id,item_id,row_id),
    FOREIGN KEY(collection_id,item_id) REFERENCES items ON DELETE CASCADE
);
CREATE TABLE spaces (
    collection_id TEXT NOT NULL,item_id TEXT NOT NULL,row_id TEXT NOT NULL,
    generation INTEGER NOT NULL,payload BLOB NOT NULL,
    PRIMARY KEY(collection_id,item_id,row_id),
    FOREIGN KEY(collection_id,item_id) REFERENCES items ON DELETE CASCADE
);
CREATE TABLE vectors (
    collection_id TEXT NOT NULL,item_id TEXT NOT NULL,row_id TEXT NOT NULL,
    generation INTEGER NOT NULL,payload BLOB NOT NULL,
    PRIMARY KEY(collection_id,item_id,row_id),
    FOREIGN KEY(collection_id,item_id) REFERENCES items ON DELETE CASCADE
);
CREATE TABLE stages (
    collection_id TEXT NOT NULL,item_id TEXT NOT NULL,row_id TEXT NOT NULL,
    generation INTEGER NOT NULL,payload BLOB NOT NULL,
    PRIMARY KEY(collection_id,item_id,row_id),
    FOREIGN KEY(collection_id,item_id) REFERENCES items ON DELETE CASCADE
);
CREATE VIRTUAL TABLE item_fts USING fts5(collection_id UNINDEXED,item_id UNINDEXED,
    row_id UNINDEXED,generation UNINDEXED,body);
CREATE VIRTUAL TABLE line_fts USING fts5(collection_id UNINDEXED,item_id UNINDEXED,
    row_id UNINDEXED,generation UNINDEXED,body);
CREATE VIEW visible_item_fts AS SELECT f.* FROM item_fts f JOIN items i
    ON f.collection_id=i.collection_id AND f.item_id=i.item_id
    AND f.generation=i.generation WHERE i.state NOT IN ('deleting','cleanup_pending');
CREATE VIEW visible_line_fts AS SELECT f.* FROM line_fts f JOIN items i
    ON f.collection_id=i.collection_id AND f.item_id=i.item_id
    AND f.generation=i.generation WHERE i.state NOT IN ('deleting','cleanup_pending');
CREATE TABLE cache_entries (
    collection_id TEXT NOT NULL REFERENCES collections(collection_id),
    cache_id TEXT NOT NULL,collection_generation INTEGER NOT NULL,payload BLOB NOT NULL,
    PRIMARY KEY(collection_id,cache_id)
);
CREATE TABLE cache_dependencies (
    collection_id TEXT NOT NULL,cache_id TEXT NOT NULL,item_id TEXT NOT NULL,
    item_generation INTEGER NOT NULL,
    PRIMARY KEY(collection_id,cache_id,item_id),
    FOREIGN KEY(collection_id,cache_id) REFERENCES cache_entries ON DELETE CASCADE
);
CREATE TABLE owned_files (
    collection_id TEXT NOT NULL,item_id TEXT NOT NULL,object_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('original','thumbnail','derived','cache')),
    expected_sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL,
    device TEXT,inode TEXT,mtime_ns INTEGER,
    state TEXT NOT NULL CHECK(state IN ('reserved','ready')),
    PRIMARY KEY(collection_id,item_id,object_id),
    FOREIGN KEY(collection_id,item_id) REFERENCES items ON DELETE CASCADE
);
CREATE UNIQUE INDEX one_original ON owned_files(collection_id,item_id) WHERE role='original';
CREATE TABLE delete_jobs (
    operation_id TEXT PRIMARY KEY,collection_id TEXT NOT NULL,item_id TEXT NOT NULL,
    item_generation INTEGER NOT NULL,collection_generation INTEGER NOT NULL,
    source_bytes INTEGER NOT NULL,status TEXT NOT NULL CHECK(status IN ('marked','cleanup_pending','deleted')),
    files_planned INTEGER NOT NULL DEFAULT 0,files_absent INTEGER NOT NULL DEFAULT 0,
    created_ns INTEGER NOT NULL,verified_ns INTEGER,reasons TEXT NOT NULL DEFAULT '[]',
    quota_released INTEGER NOT NULL DEFAULT 0,
    UNIQUE(collection_id,item_id)
);
CREATE TABLE delete_files (
    operation_id TEXT NOT NULL REFERENCES delete_jobs(operation_id),
    collection_id TEXT NOT NULL,item_id TEXT NOT NULL,object_id TEXT NOT NULL,role TEXT NOT NULL,
    expected_sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL,
    device TEXT,inode TEXT,mtime_ns INTEGER,absent INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(operation_id,collection_id,item_id,object_id)
);
PRAGMA user_version=1;
