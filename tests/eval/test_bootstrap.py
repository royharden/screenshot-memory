"""Anonymous hand-calculated synthetic controls, no product data or live authority."""

import dataclasses
from unittest.mock import patch

import pytest

from screenshot_memory.shared.evalkit.models import (
    DomainLabels,
    GoldRecord,
    Prediction,
    ResamplingSpec,
    SourceRef,
)
from screenshot_memory.shared.evalkit.resampling import paired_group_resample
from screenshot_memory.shared.retrievaleval.bootstrap import (
    DOMAIN,
    resample_retrieval,
    retrieval_outcome,
    retrieval_statistic,
    statistic_version,
)
from screenshot_memory.shared.retrievaleval.metrics import METRICS

GALLERY = ("p1", "p2", "p3")


def gold(query="q1", group="g1", relevant=("p1",), gallery=GALLERY):
    return GoldRecord(
        item_id=query,
        dataset="toy",
        group_id=group,
        split="dev",
        label_version="toy/1",
        source_ref=SourceRef(handle="toy-source", sha256="a" * 64),
        input_sha256="b" * 64,
        label_source="synthetic",
        label_provenance_ref=None,
        domain_kind=DOMAIN,
        label_payload=DomainLabels(
            kind="domain_labels",
            payload={
                "gallery": list(gallery),
                "relevant": list(relevant),
            },
        ),
    )


def prediction(query="q1", method="a", ranking=("p1",), status="ok", **updates):
    values = dict(
        item_id=query,
        method=method,
        method_version="toy/1",
        config_sha256="c" * 64,
        model=None,
        origin="synthetic",
        status=status,
        domain_payload={"ranking": list(ranking)} if status == "ok" else None,
        machine_output={"ranking": list(ranking)} if status == "ok" else None,
        human_effective_output=None,
        human_provenance_ref=None,
        issues=() if status == "ok" else ("synthetic_failure",),
        ledger_refs=(),
        source_refs=(SourceRef(handle="toy-feature", sha256="d" * 64),),
    )
    values.update(updates)
    return Prediction(**values)


def toy_resolver(pred, ref):
    # Explicit synthetic test double; it authenticates no real feature coverage.
    assert pred.origin == "synthetic" and ref.label_source == "synthetic"
    return "synthetic-coverage-1"


def row(query="q1", group="g1", relevant=("p1",), ranking=("p1",), method="a", **kw):
    return retrieval_outcome(
        prediction(query, method, ranking, **kw),
        gold(query, group, relevant),
        coverage_resolver=toy_resolver,
    )


def spec(metric="recall@1", groups=("g1", "g2"), **kw):
    values = dict(
        version="s7-toy/1",
        unit="group_id",
        seed=7317,
        draws=2000,
        level=0.95,
        method="percentile",
        group_order=groups,
        stratum_map=None,
        min_support=1,
        min_valid_draws=1900,
        statistic_version=statistic_version(metric),
        rng_version="Python3.12/random",
    )
    values.update(kw)
    return ResamplingSpec(**values)


@pytest.mark.parametrize(
    "metric,expected", list(zip(METRICS, (0.75, 0.75, 0.75, 1.0, 1.0, 1.0, 1.0), strict=True))
)
def test_actual_statistic_is_positive_query_mean_not_pooled_targets(metric, expected):
    rows = (
        row(relevant=("p1", "p2")),
        row("q2", "g1", ("p2",), ("p2",)),
        row("qn", "g2", (), ("p3",)),
    )
    result = retrieval_statistic(rows, metric)
    assert result.value == expected and result.support == 2
    assert all(r.correct is None for r in rows)


def test_full_mrr_not_top10_and_no_padding():
    gallery = tuple(f"p{i}" for i in range(30))
    result = retrieval_outcome(
        prediction(ranking=gallery),
        gold(relevant=("p29",), gallery=gallery),
        coverage_resolver=toy_resolver,
    )
    assert retrieval_statistic((result,), "mrr").value == 1 / 30


def test_repeated_groups_repeat_all_queries_and_negatives_do_not_gain_support():
    a = row(relevant=("p1", "p2"))
    b = row("q2", "g1", ("p2",), ("p2",))
    c = row("q3", "g2", ("p3",), ())
    neg = row("qn", "g1", (), ("p3",))
    result = retrieval_statistic((a, b, neg, a, b, neg, c), "recall@1")
    assert result.value == 0.6 and result.support == 5


def test_all_negative_reference_is_undefined_not_zero_or_perfect():
    result = retrieval_statistic((row(relevant=()),), "mrr")
    assert result.value is None and result.support == 0
    assert result.null_reason == "no_positive_queries"


@pytest.mark.parametrize("status", ["provider_error", "blocked", "invalid", "abstained"])
def test_actual_eligible_failure_remains_closed_status_and_zero_miss(status):
    failed = row(status=status)
    assert failed.status == status and failed.evidence_origin == "synthetic"
    assert failed.issues == ("synthetic_failure",)
    assert retrieval_statistic((failed,), "recall@1").value == 0
    assert retrieval_statistic((failed,), "recall@1").support == 1


@pytest.mark.parametrize("status", ["not_run", "stale", "unavailable"])
def test_unexecuted_stale_or_unavailable_refuses_measured_interval(status):
    pred = prediction(
        status=status, origin="not_run" if status == "not_run" else "synthetic", source_refs=()
    )
    with pytest.raises(ValueError, match="unexecuted or unavailable"):
        retrieval_outcome(pred, gold(), coverage_resolver=toy_resolver)


@pytest.mark.parametrize("answer", [None, False, True, ""])
def test_incomplete_or_unbound_coverage_never_becomes_empty_success(answer):
    with pytest.raises(ValueError):
        retrieval_outcome(prediction(), gold(), coverage_resolver=lambda p, g: answer)


def test_resolver_mutation_of_transitively_mutable_reference_refuses():
    def bad(pred, ref):
        ref.label_payload.payload["relevant"] = []
        return "synthetic-coverage-1"

    with pytest.raises(ValueError, match="changed bound input"):
        retrieval_outcome(prediction(), gold(), coverage_resolver=bad)


def test_origin_human_config_ledger_and_source_bindings_are_actual():
    pred = prediction(
        human_effective_output={"ranking": ["p2"]},
        human_provenance_ref="toy-human-record",
        ledger_refs=("toy-ledger",),
    )
    result = retrieval_outcome(pred, gold(), coverage_resolver=toy_resolver)
    assert result.evidence_origin == pred.origin and result.human_touched_prediction
    assert result.ledger_refs == pred.ledger_refs
    assert result.predicted["config_sha256"] == pred.config_sha256
    assert result.predicted["source_refs"] == [r.model_dump(mode="json") for r in pred.source_refs]
    assert len(result.predicted["prediction_sha256"]) == 64
    assert result.predicted["ranking"] == ["p1"]


def test_query_asset_alias_foreign_or_duplicate_rank_refuses():
    for ref, pred in [
        (gold(query="p1"), prediction(query="p1")),
        (gold(), prediction(ranking=("foreign",))),
        (gold(), prediction(ranking=("p1", "p1"))),
    ]:
        with pytest.raises(ValueError):
            retrieval_outcome(pred, ref, coverage_resolver=toy_resolver)


def test_same_canonical_engine_and_common_stream_paired_delta():
    a = (row(), row("q2", "g2", ("p2",), ("p2",)))
    b = (row(method="b"), row("q2", "g2", ("p2",), ("p2",), method="b"))
    inputs = {"a": a, "b": b}
    policy = spec()
    module = "screenshot_memory.shared.retrievaleval.bootstrap.paired_group_resample"
    with patch(module, wraps=paired_group_resample) as actual:
        result = resample_retrieval(inputs, policy, "recall@1")
    assert actual.call_count == 1
    assert result.methods["a"].point.value == result.methods["b"].point.value == 1
    assert result.methods["a"].valid_draws == result.methods["b"].valid_draws == 2000
    assert dataclasses.asdict(result.methods["a"]) == dataclasses.asdict(result.methods["b"])
    delta = result.differences["a", "b"]
    assert delta.point.value == delta.interval.low == delta.interval.high == 0
    assert delta.interval.draw_ids_sha256 == result.draws_sha256


def test_undefined_group_draws_not_redrawn_to_obtain_interval():
    rows = (row(), row("qn", "g2", (), ()))
    result = resample_retrieval({"a": rows}, spec(), "recall@1")
    estimate = result.methods["a"]
    assert estimate.point.value == 1 and estimate.point.support == 1
    assert 1400 < estimate.valid_draws < 1600
    assert estimate.interval is None and estimate.null_reason == "insufficient_valid_draws"
    assert len(result.draws_sha256) == 64


def test_one_independent_group_has_no_interval():
    result = resample_retrieval({"a": (row(),)}, spec(groups=("g1",)), "recall@1")
    assert result.methods["a"].interval is None
    assert result.methods["a"].null_reason == "insufficient_independent_groups"


@pytest.mark.parametrize(
    "change", [{"min_support": 2}, {"min_valid_draws": 1}, {"statistic_version": "other"}]
)
def test_frozen_support_policy_cannot_be_relaxed_or_silently_changed(change):
    with pytest.raises(ValueError, match="support/version"):
        resample_retrieval({"a": (row(), row("q2", "g2"))}, spec(**change), "recall@1")


def test_paired_reference_axis_change_rejected_before_score_callback():
    a = (row(), row("q2", "g2"))
    b = (row(method="b"), row("q2", "g2", ("p2",), method="b"))
    with patch("screenshot_memory.shared.retrievaleval.bootstrap.retrieval_statistic") as callback:
        with pytest.raises(ValueError, match="paired_population_changed"):
            resample_retrieval({"a": a, "b": b}, spec(), "recall@1")
    callback.assert_not_called()


def test_varying_gallery_even_with_same_methods_is_not_one_frozen_population():
    changed = retrieval_outcome(
        prediction("q2"), gold("q2", "g2", gallery=("p1", "p2")), coverage_resolver=toy_resolver
    )
    with pytest.raises(ValueError, match="gallery changed"):
        resample_retrieval({"a": (row(), changed)}, spec(), "recall@1")


@pytest.mark.parametrize(
    "key,value",
    [
        ("prediction_sha256", "fake"),
        ("config_sha256", "bad"),
        ("source_refs", "string"),
        ("method_version", ""),
    ],
)
def test_direct_outcome_cannot_skip_domain_lineage_validation(key, value):
    outcome = row()
    outcome.predicted[key] = value
    with pytest.raises(ValueError, match="prediction lineage"):
        retrieval_statistic((outcome,), "recall@1")
