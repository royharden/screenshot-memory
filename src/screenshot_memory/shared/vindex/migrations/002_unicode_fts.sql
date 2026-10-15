CREATE VIRTUAL TABLE item_fts_next USING fts5(collection_id UNINDEXED,item_id UNINDEXED,
    row_id UNINDEXED,generation UNINDEXED,body,tokenize='unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE line_fts_next USING fts5(collection_id UNINDEXED,item_id UNINDEXED,
    row_id UNINDEXED,generation UNINDEXED,body,tokenize='unicode61 remove_diacritics 2');
INSERT INTO item_fts_next(rowid,collection_id,item_id,row_id,generation,body)
    SELECT f.rowid,f.collection_id,f.item_id,f.row_id,f.generation,f.body
    FROM item_fts f JOIN items i USING(collection_id,item_id)
    WHERE f.generation=i.generation AND i.state NOT IN ('deleting','cleanup_pending');
INSERT INTO line_fts_next(rowid,collection_id,item_id,row_id,generation,body)
    SELECT f.rowid,f.collection_id,f.item_id,f.row_id,f.generation,f.body
    FROM line_fts f JOIN items i USING(collection_id,item_id)
    WHERE f.generation=i.generation AND i.state NOT IN ('deleting','cleanup_pending');
DROP VIEW visible_item_fts;
DROP VIEW visible_line_fts;
DROP TABLE item_fts;
DROP TABLE line_fts;
ALTER TABLE item_fts_next RENAME TO item_fts;
ALTER TABLE line_fts_next RENAME TO line_fts;
INSERT INTO item_fts(item_fts,rank) VALUES('secure-delete',1);
INSERT INTO line_fts(line_fts,rank) VALUES('secure-delete',1);
CREATE VIEW visible_item_fts AS SELECT f.* FROM item_fts f JOIN items i
    ON f.collection_id=i.collection_id AND f.item_id=i.item_id
    AND f.generation=i.generation WHERE i.state NOT IN ('deleting','cleanup_pending');
CREATE VIEW visible_line_fts AS SELECT f.* FROM line_fts f JOIN items i
    ON f.collection_id=i.collection_id AND f.item_id=i.item_id
    AND f.generation=i.generation WHERE i.state NOT IN ('deleting','cleanup_pending');
PRAGMA user_version=2;
