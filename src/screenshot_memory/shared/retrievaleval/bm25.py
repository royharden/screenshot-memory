"""Bounded portable BM25 reference; no IO, model or FTS equivalence claim."""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

TOKENIZER = "s7-nfkc-casefold-unicode-alnum/1"
FORMULA = "positive-idf-bm25-k1=1.2-b=0.75-unique-query-terms/1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_WORD = re.compile(r"[^\W_]+", flags=re.UNICODE)


@dataclass(frozen=True)
class LexicalHit:
    item_id: str
    score: float


def tokens(text: str, *, max_chars: int = 25_000) -> tuple[str, ...]:
    """NFKC then casefold; contiguous Unicode alphanumerics, no accent removal.

    Underscores/punctuation delimit, numbers remain, no stemming/stopword list.
    CJK runs remain whole tokens. This intentionally differs from SQLite FTS.
    """
    if type(text) is not str or len(text) > max_chars:
        raise ValueError("invalid or oversized lexical text")
    text.encode("utf-8", errors="strict")
    return tuple(_WORD.findall(unicodedata.normalize("NFKC", text).casefold()))


def bm25(corpus: Mapping[str, str], query: str) -> tuple[LexicalHit, ...]:
    """All positive-score matches from at most30 caller-eligible documents.

    Empty documents count in N and average length. Query term repetition does
    not create extra votes. No match yields (), never padded zero-score items.
    This reference does not verify collection/generation or feature coverage.
    """
    if not isinstance(corpus, Mapping) or not 1 <= len(corpus) <= 30:
        raise ValueError("corpus must contain 1..30 documents")
    if type(query) is not str or not 1 <= len(query) <= 1000:
        raise ValueError("query must contain 1..1000 characters")
    for item_id in corpus:
        if type(item_id) is not str or not _ID.fullmatch(item_id):
            raise ValueError("invalid opaque item ID")
    frequencies = {item_id: Counter(tokens(text)) for item_id, text in corpus.items()}
    lengths = {item_id: sum(counts.values()) for item_id, counts in frequencies.items()}
    query_terms = sorted(set(tokens(query, max_chars=1000)))
    average_length = math.fsum(lengths.values()) / len(corpus)
    if not query_terms or average_length == 0:
        return ()
    document_frequency = {
        term: sum(term in counts for counts in frequencies.values()) for term in query_terms
    }
    results = []
    for item_id, counts in frequencies.items():
        contributions = []
        for term in query_terms:
            frequency = counts[term]
            if frequency:
                df = document_frequency[term]
                idf = math.log1p((len(corpus) - df + 0.5) / (df + 0.5))
                norm = 1.2 * (0.25 + 0.75 * lengths[item_id] / average_length)
                contributions.append(idf * frequency * 2.2 / (frequency + norm))
        score = math.fsum(contributions)
        if score > 0:
            results.append(LexicalHit(item_id, score))
    return tuple(sorted(results, key=lambda hit: (-hit.score, hit.item_id)))
