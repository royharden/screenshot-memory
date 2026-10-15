"""Independent fixed-equation arithmetic, without retrieval execution claims."""

import pytest

from screenshot_memory.shared.vindex.fusion import fuse


def legs(keyword=(), combined=(), image=()):
    return {"keyword": keyword, "combined": combined, "image": image}


def test_hand_computed_ranks_union_and_per_leg_contributions():
    result = fuse(legs(("a", "b"), ("b", "a"), ("b",)), ("a", "b", "c"))
    assert result.status == "available"
    assert [hit.item_id for hit in result.hits] == ["b", "a"]
    assert result.hits[0].score == pytest.approx(2 / 61 + 1 / 62)
    assert result.hits[0].ranks == (("keyword", 2), ("combined", 1), ("image", 1))
    assert result.hits[1].score == pytest.approx(1 / 61 + 1 / 62)


def test_tied_scores_sort_by_id_and_leg_mapping_order_cannot_change_result():
    source = legs(("z", "a"), ("a", "z"))
    result = fuse(source, ("z", "a"))
    assert [hit.item_id for hit in result.hits] == ["a", "z"]
    assert fuse(dict(reversed(list(source.items()))), ("a", "z")) == result


def test_unavailable_and_executed_empty_legs_retain_distinct_states():
    result = fuse(legs(("a",), (), None), ("a", "b"))
    assert result.status == "degraded"
    assert result.active_legs == ("keyword", "combined")
    assert result.unavailable_legs == ("image",)
    assert len(result.hits) == 1 and result.hits[0].score == 1 / 61
    empty = fuse(legs(), ("a",))
    assert empty.hits == () and empty.status == "available"
    unavailable = fuse(legs(None, None, None), ("a",))
    assert unavailable.hits == () and unavailable.status == "unavailable"


def test_all_thirty_produced_items_and_last_rank_are_retained():
    ids = tuple(f"p{i:02}" for i in range(30))
    result = fuse(legs(ids), ids)
    assert len(result.hits) == 30
    assert result.hits[-1].item_id == "p29" and result.hits[-1].score == 1 / 90
    assert result.hits[-1].ranks == (("keyword", 30),)


@pytest.mark.parametrize(
    "rankings,eligible",
    [
        (legs(("a", "a")), ("a",)),
        (legs(("foreign",)), ("a",)),
        (legs(), ()),
        (legs(), ("a", "a")),
        (legs(), (True,)),
        (legs(["a"]), ("a",)),
        (legs() | {"ocr": ()}, ("a",)),
        ({"keyword": ()}, ("a",)),
        (legs(), tuple(str(i) for i in range(31))),
    ],
)
def test_invalid_unknown_duplicate_or_extra_production_votes_refused(rankings, eligible):
    with pytest.raises(ValueError):
        fuse(rankings, eligible)
