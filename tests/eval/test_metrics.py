"""Hand-computed toy passage controls, no product fixtures or retrieval code."""

import math

import pytest

from screenshot_memory.shared.retrievaleval import (
    grouped_mean,
    paired_draw,
    score_method,
    score_ranking,
)

GALLERY = tuple(f"p{i}" for i in range(1, 31))


@pytest.mark.parametrize("rank", range(1, 31))
def test_full_mrr_keeps_first_relevant_rank_through_thirty(rank):
    result = score_ranking(GALLERY, (f"p{rank}",), GALLERY)
    assert result["metrics"]["mrr"] == 1 / rank
    assert result["metrics"]["recall@1"] == float(rank == 1)
    assert result["metrics"]["hit@5"] == float(rank <= 5)


def test_multi_gold_recall_is_not_hit_and_no_ranks_padded():
    result = score_ranking(("p1", "p3", "p4", "p2"), ("p1", "p2"), GALLERY)
    assert result["metrics"] == {
        "recall@1": 0.5,
        "recall@3": 0.5,
        "recall@5": 1.0,
        "hit@1": 1.0,
        "hit@3": 1.0,
        "hit@5": 1.0,
        "mrr": 1.0,
    }
    short = score_ranking(("p3",), ("p1",), GALLERY)
    assert short["produced_count"] == 1 and set(short["metrics"].values()) == {0.0}


def test_empty_targets_have_no_retrieval_denominator_not_zero_score():
    for ranking in ((), ("p1",)):
        result = score_ranking(ranking, (), GALLERY)
        assert result["status"] == "measured" and not result["positive"]
        assert set(result["metrics"].values()) == {None}


def test_macro_query_recall_differs_from_pooled_target_recall():
    result = score_method(
        {"q1": ("p1", "p2"), "q2": ("p2",), "qn": ()},
        {"q1": ("p1",), "q2": ("p2",), "qn": ("p3",)},
        GALLERY,
    )
    assert result["status"] == "measured"
    assert result["positive_cases"] == 2 and result["negative_cases"] == 1
    assert result["metrics"]["recall@1"] == 0.75
    assert result["metrics"]["hit@1"] == 1.0
    assert not math.isclose(result["metrics"]["recall@1"], 2 / 3)


def test_executed_empty_failure_counts_miss_unexecuted_never_becomes_zero():
    cases = {"q1": ("p1",), "q2": ("p2",)}
    failed = score_method(cases, {"q1": ("p1",), "q2": ()}, GALLERY)
    assert failed["status"] == "measured" and failed["metrics"]["mrr"] == 0.5
    absent = score_method(cases, {"q1": ("p1",), "q2": None}, GALLERY)
    assert absent["status"] == "incomplete" and absent["unexecuted_cases"] == 1
    assert set(absent["metrics"].values()) == {None}
    with pytest.raises(ValueError, match="coverage"):
        score_method(cases, {"q1": ("p1",)}, GALLERY)


def test_only_negative_cases_not_a_zero_retrieval_claim():
    result = score_method({"qn": ()}, {"qn": ()}, GALLERY)
    assert result["retrieval_applicability"] == "not_applicable"
    assert result["positive_cases"] == 0 and result["negative_cases"] == 1
    assert set(result["metrics"].values()) == {None}


@pytest.mark.parametrize(
    "ranking,gold,gallery",
    [
        (("p1", "p1"), ("p1",), GALLERY),
        (("unknown",), ("p1",), GALLERY),
        (("p1",), ("unknown",), GALLERY),
        (("p1",), ("p1", "p1"), GALLERY),
        (("p1",), ("p1",), ("p1", "p1")),
        (("p1",), ("p1",), ()),
        (["p1"], ("p1",), GALLERY),
        ((True,), ("p1",), GALLERY),
        (("p1",), ("p1",), tuple(f"p{i}" for i in range(31))),
    ],
)
def test_bad_duplicate_unknown_or_coerced_rank_records_fail(ranking, gold, gallery):
    with pytest.raises(ValueError):
        score_ranking(ranking, gold, gallery)


def test_case_id_is_not_asset_id():
    with pytest.raises(ValueError, match="query/case"):
        score_method({"p1": ("p2",)}, {"p1": ("p2",)}, GALLERY)


def test_group_draw_repeats_whole_groups_not_individual_queries():
    values = {"q1": 1.0, "q2": 0.0, "q3": 0.0}
    groups = {"q1": "g1", "q2": "g1", "q3": "g2"}
    one_each = grouped_mean(values, groups, ("g1", "g2"))
    assert one_each == {
        "value": 1 / 3,
        "eligible_cases": 3,
        "sampled_cases": 3,
        "sampled_groups": 2,
    }
    repeated = grouped_mean(values, groups, ("g1", "g1"))
    assert repeated == {"value": 0.5, "eligible_cases": 4, "sampled_cases": 4, "sampled_groups": 2}
    assert one_each["value"] != 0.25  # not equally averaging differently sized groups


def test_paired_methods_share_draw_and_denominator():
    values = {"a": {"q1": 1.0, "q2": 0.0, "q3": 0.0}, "b": {"q1": 0.0, "q2": 1.0, "q3": 1.0}}
    groups = {"q1": "g1", "q2": "g1", "q3": "g2"}
    result = paired_draw(values, groups, ("g1", "g2"), "a")
    assert result["eligible_cases"] == 3
    assert result["estimates"] == {"a": 1 / 3, "b": 2 / 3}
    assert result["deltas_from_reference"]["b"] == pytest.approx(1 / 3)
    assert paired_draw(values, groups, ("g1", "g1"), "a")["deltas_from_reference"]["b"] == 0


def test_negative_only_draw_is_invalid_support_not_zero():
    values = {"q1": 1.0, "qn": None}
    groups = {"q1": "g1", "qn": "gn"}
    result = grouped_mean(values, groups, ("gn", "gn"))
    assert result["value"] is None and result["eligible_cases"] == 0
    assert result["sampled_cases"] == 2
    paired = paired_draw({"a": values, "b": values}, groups, ("gn", "gn"), "a")
    assert paired["estimates"] == {"a": None, "b": None}
    assert paired["deltas_from_reference"] == {"a": None, "b": None}


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -0.1, 1.1, "0.5"])
def test_callback_refuses_nonfinite_coerced_or_out_of_range_score(bad):
    with pytest.raises(ValueError):
        grouped_mean({"q1": bad}, {"q1": "g1"}, ("g1",))


def test_mismatched_group_or_paired_eligibility_refused():
    with pytest.raises(ValueError, match="coverage"):
        grouped_mean({"q1": 1.0}, {"q2": "g1"}, ("g1",))
    with pytest.raises(ValueError, match="undeclared"):
        grouped_mean({"q1": 1.0}, {"q1": "g1"}, ("g2",))
    with pytest.raises(ValueError, match="declared number"):
        grouped_mean({"q1": 1.0}, {"q1": "g1"}, ("g1", "g1"))
    with pytest.raises(ValueError, match="eligibility"):
        paired_draw({"a": {"q1": None}, "b": {"q1": 0.0}}, {"q1": "g1"}, ("g1",), "a")
