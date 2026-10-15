"""Literal SQLite keyword ranking, scoped to one current visible collection."""

import math
from dataclasses import dataclass

from .storage import GenerationToken, Store, StoreError, checked_id


@dataclass(frozen=True)
class KeywordHit:
    token: GenerationToken
    sqlite_bm25: float


def keyword_search(store: Store, collection_id: str, query: str) -> tuple[KeywordHit, ...]:
    """Return every matching item; consumers must recheck each generation token.

    Temporary MEMORY indexes keep tokenizer and BM25 statistics local to the
    eligible collection. Foreign, deleting and stale rows cannot affect ranks.
    SQLite's score is an ordering value, not a calibrated probability.
    """
    checked_id(collection_id)
    if type(query) is not str or not 1 <= len(query) <= 1000:
        raise StoreError("invalid_query")
    with store.transaction() as conn:
        conn.execute("PRAGMA temp_store=MEMORY")
        if conn.execute("PRAGMA temp_store").fetchone()[0] != 2:
            raise StoreError("memory_temp_unavailable")
        collection = conn.execute(
            "SELECT generation FROM collections WHERE collection_id=?", (collection_id,)
        ).fetchone()
        if collection is None:
            raise StoreError("collection_missing")
        count = conn.execute(
            "SELECT count(*) FROM items WHERE collection_id=? "
            "AND state NOT IN ('deleting','cleanup_pending')",
            (collection_id,),
        ).fetchone()[0]
        if count > 30:
            raise StoreError("collection_full")
        conn.execute(
            "CREATE VIRTUAL TABLE temp.query_terms USING fts5(body,"
            "tokenize='unicode61 remove_diacritics 2')"
        )
        conn.execute("INSERT INTO query_terms(body) VALUES(?)", (query,))
        conn.execute(
            "CREATE VIRTUAL TABLE temp.query_vocab USING fts5vocab(temp,'query_terms','row')"
        )
        terms = tuple(row[0] for row in conn.execute("SELECT term FROM query_vocab ORDER BY term"))
        if not terms:
            return ()
        expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
        conn.execute(
            "CREATE VIRTUAL TABLE temp.search_docs USING fts5(item_id UNINDEXED,"
            "generation UNINDEXED,body,tokenize='unicode61 remove_diacritics 2')"
        )
        conn.execute(
            "INSERT INTO search_docs(item_id,generation,body) "
            "SELECT f.item_id,f.generation,f.body FROM visible_item_fts f "
            "WHERE f.collection_id=? ORDER BY f.item_id,f.row_id",
            (collection_id,),
        )
        best: dict[str, tuple[int, float]] = {}
        for row in conn.execute(
            "SELECT item_id,generation,bm25(search_docs) AS score "
            "FROM search_docs WHERE search_docs MATCH ?",
            (expression,),
        ):
            score = float(row["score"])
            if not math.isfinite(score):
                raise StoreError("invalid_search_score")
            previous = best.get(row["item_id"])
            if previous is None or score < previous[1]:
                best[row["item_id"]] = (row["generation"], score)
        return tuple(
            KeywordHit(
                GenerationToken(
                    collection_id=collection_id,
                    item_id=item_id,
                    collection_generation=collection[0],
                    item_generation=generation,
                ),
                score,
            )
            for item_id, (generation, score) in sorted(
                best.items(), key=lambda pair: (pair[1][1], pair[0])
            )
        )
