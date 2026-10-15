"""Hand-computed anonymous passages, no original dataset/Gold/models."""

import math

import pytest

from screenshot_memory.shared.retrievaleval.bm25 import bm25, tokens


def test_hand_computed_positive_idf_and_length_normalization():
    result = bm25({"a": "red red", "b": "blue", "c": ""}, "red")
    # N3,df1,average_length1, tf2,length2, norm1.2*(.25+.75*2)=2.1.
    assert len(result) == 1 and result[0].item_id == "a"
    assert result[0].score == pytest.approx(math.log(8 / 3) * 4.4 / 4.1)


def test_every_document_in_full_gallery_is_searched_not_only_first_ten():
    corpus = {f"p{i:02}": "ordinary content" for i in range(30)}
    corpus["p29"] += " bottom needle"
    result = bm25(corpus, "needle")
    assert [hit.item_id for hit in result] == ["p29"]


def test_query_duplicates_do_not_inflate_votes_and_ties_are_id_sorted():
    corpus = {"z": "same word", "a": "same word", "m": "unrelated"}
    assert bm25(corpus, "word word WORD") == bm25(corpus, "word")
    assert [hit.item_id for hit in bm25(corpus, "word")] == ["a", "z"]
    assert bm25(dict(reversed(list(corpus.items()))), "word") == bm25(corpus, "word")


@pytest.mark.parametrize(
    "corpus,query",
    [
        ({"a": ""}, "word"),
        ({"a": "word"}, "missing"),
        ({"a": "word"}, "___ !"),
        ({"a": "word"}, "   "),
    ],
)
def test_absent_terms_and_empty_tokens_never_pad_ranks(corpus, query):
    assert bm25(corpus, query) == ()


def test_tokenizer_is_explicit_unicode_nfkc_casefold_with_accents_retained():
    assert tokens("Ｒｅｄ Straße café foo_bar １２ 東京") == (
        "red",
        "strasse",
        "café",
        "foo",
        "bar",
        "12",
        "東京",
    )
    assert bm25({"a": "café", "b": "cafe"}, "cafe")[0].item_id == "b"


def test_common_term_stays_positive_and_more_hits_are_not_truncated():
    corpus = {f"p{i:02}": "shared" for i in range(30)}
    result = bm25(corpus, "shared")
    assert len(result) == 30 and all(hit.score > 0 for hit in result)


@pytest.mark.parametrize(
    "corpus,query",
    [
        ({}, "x"),
        ({str(i): "x" for i in range(31)}, "x"),
        ({"../bad": "x"}, "x"),
        ({True: "x"}, "x"),
        ({"a": None}, "x"),
        ({"a": "x" * 25001}, "x"),
        ({"a": "x"}, ""),
        ({"a": "x"}, "x" * 1001),
        ({"a": "x"}, True),
        ({"a": "\ud800"}, "x"),
    ],
)
def test_invalid_or_oversized_input_is_not_silently_truncated(corpus, query):
    with pytest.raises((ValueError, TypeError)):
        bm25(corpus, query)
