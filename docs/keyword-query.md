# Explicit keyword queries

`smem query --root ROOT --collection COLLECTION TEXT --mode keyword` reads existing
literal text projections. It never decodes source images, initializes an OCR/model
runtime, generates features or silently enables semantic search. The default
construction mode continues to return unavailable. Import alone supplies decode
metadata; use the explicit Python OCR adapter to publish recognized text separately.

The command uses SQLite FTS5 unicode61 tokenization and collection-local BM25
ordering. Input operators are literal tokens, not executable FTS grammar. Scores
are ordering values, not probabilities. Each item appears at most once; ties use
opaque IDs. Foreign collections, staging imports and deleting/stale rows are excluded.

Results include `visible_items`, `indexed_items`, `empty_ocr_items` and
`unindexed_items`. A retained empty OCR artifact counts only after checking its
canonical byte digest, completed stage identity, document/page/source revision,
grid, dimensions and processing revision. Missing text rows alone never prove a
blank screenshot. Empty FTS payloads remain invalid. An item with a text projection
counts as indexed even when its text has no match for the current query.

- `ok`, `executed:true`: every visible item has a text projection or a verified
  empty OCR artifact. An empty collection also returns this result.
- `partial`, `executed:true`: some visible items have usable coverage, while others
  are missing it. Ranked hits cover only available text.
- `unavailable`, `executed:false`, exit2: a nonempty collection has no usable coverage.

Hits carry the generation token, rank, SQLite ordering score and declared OCR/caption
stage provenance. They contain no snippets, source pixels, boxes or resolved pointers.
Generation checks during result materialization refuse a collection changed by
deletion; a new query cannot return the removed item. Regions, embeddings and reranking
remain explicitly unavailable. Metadata controls do not establish native OCR quality,
runtime packaging, the viewer journey or whole-application acceptance.
