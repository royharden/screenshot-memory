# SQLite keyword retrieval

`shared.vindex.search.keyword_search(store, collection_id, query)` accepts one
opaque collection ID and a plain-text query of 1 through 1000 characters. Its
connection-local in-memory FTS5 tokenizer is explicitly `unicode61
remove_diacritics 2`, matching migration002. Actual SQLite tokenization determines
terms; distinct terms become individually quoted OR operands. Quotes, operators,
asterisks and parentheses in user text do not become query grammar. No-token and
no-match queries return an executed empty tuple.

Search constructs a temporary MEMORY FTS index from all current visible item
rows in that collection inside a consistent writer transaction. Foreign,
deleting and stale rows are excluded before SQLite calculates BM25, so they
cannot change scores. The visible gallery is bounded to30 items. Every matching
item is returned once, using its best matching row's SQLite BM25 score, ascending
score and then opaque item ID. There is no candidate top10 gate or rank padding.
No match is not a semantic absence or no-answer judgment. Scores are ordering
values rather than probabilities, and are not equivalent to the portable BM25
reference implementation's tokenizer or scoring population.

Each immutable result carries the collection and item generation observed in
that transaction. Consumers must recheck that token through Store before opening
content or persisting downstream results. An old result is not perpetual access
authority; deleting a sibling also invalidates its collection generation.

Tests use actual SQLite with synthetic text and metadata, including migration,
Unicode, literal syntax, collection isolation and deletion. They do not establish
native OCR, ingestion completeness, embedding quality, real-gallery relevance or
an application evaluation result. New wheel/full-application verification is
still required before delivery.
