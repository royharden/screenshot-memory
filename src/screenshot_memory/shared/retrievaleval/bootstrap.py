"""S7 private retrieval callback to the unchanged canonical paired-group engine.

No corpus IO, randomness, generic interval code or execution authority lives here.
An injected coverage resolver must inspect actual recorded feature lineage.
"""

import hashlib
import math
import re
from collections.abc import Callable, Mapping

from ..evalkit.identity import canonical_bytes
from ..evalkit.models import (
    DomainLabels,
    GoldRecord,
    Outcome,
    Prediction,
    ResamplingSpec,
    SourceRef,
)
from ..evalkit.resampling import PairedResampling, paired_group_resample
from ..evalkit.statistics import Statistic
from .metrics import MAX_CASES, METRICS, _id, score_ranking

DOMAIN = "s7-retrieval/1"
FIELD = "retrieval"
UNMEASURED = {"not_run", "stale", "unavailable"}


def _reference(payload: object, query_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if type(payload) is not dict or set(payload) != {"gallery", "relevant"}:
        raise ValueError("closed retrieval reference required")
    if type(payload["gallery"]) is not list or type(payload["relevant"]) is not list:
        raise ValueError("reference lists required")
    gallery, relevant = tuple(payload["gallery"]), tuple(payload["relevant"])
    score_ranking((), relevant, gallery)
    _id(query_id)
    if query_id in gallery:
        raise ValueError("query ID must differ from gallery asset IDs")
    return gallery, relevant


def retrieval_outcome(
    prediction: Prediction,
    gold: GoldRecord,
    *,
    coverage_resolver: Callable[[Prediction, GoldRecord], str | None],
) -> Outcome:
    """Bind actual canonical records; refuse absent/incomplete coverage authority.

    Resolver must fail/return None unless the exact prediction/config/gallery
    has complete required feature execution. Failed eligible attempts can then
    remain misses. This interface has no permissive default resolver. A string
    receipt is a reference to the caller's inspected record, not authenticity proof.
    """
    if not isinstance(prediction, Prediction) or not isinstance(gold, GoldRecord):
        raise ValueError("actual canonical prediction and gold required")
    if prediction.item_id != gold.item_id or gold.domain_kind != DOMAIN:
        raise ValueError("prediction/reference identity mismatch")
    if not isinstance(gold.label_payload, DomainLabels):
        raise ValueError("domain reference required")
    gallery, relevant = _reference(gold.label_payload.payload, gold.item_id)
    if prediction.status in UNMEASURED:
        raise ValueError("unexecuted or unavailable method has no measured resampling")
    if not callable(coverage_resolver):
        raise ValueError("actual feature coverage resolver required")
    prediction_bytes = canonical_bytes(prediction.model_dump(mode="json"))
    gold_bytes = canonical_bytes(gold.model_dump(mode="json"))
    receipt = coverage_resolver(prediction, gold)
    if (
        canonical_bytes(prediction.model_dump(mode="json")) != prediction_bytes
        or canonical_bytes(gold.model_dump(mode="json")) != gold_bytes
    ):
        raise ValueError("coverage resolver changed bound input")
    if type(receipt) is not str:
        raise ValueError("incomplete required feature coverage")
    _id(receipt)
    if prediction.status == "ok":
        payload = prediction.domain_payload
        if type(payload) is not dict or set(payload) != {"ranking"}:
            raise ValueError("closed machine ranking required")
        if type(payload["ranking"]) is not list:
            raise ValueError("ranking list required")
        ranking = tuple(payload["ranking"])
    else:
        # The actual closed failure status is retained below, rather than relabelled ok.
        ranking = ()
    score_ranking(ranking, relevant, gallery)
    return Outcome(
        item_id=gold.item_id,
        group_id=gold.group_id,
        dataset=gold.dataset,
        split=gold.split,
        method=prediction.method,
        field=FIELD,
        **{"class": None},
        eligibility="eligible",
        status=prediction.status,
        correct=None,
        predicted={
            "ranking": list(ranking),
            "prediction_sha256": hashlib.sha256(prediction_bytes).hexdigest(),
            "coverage_receipt": receipt,
            "method_version": prediction.method_version,
            "config_sha256": prediction.config_sha256,
            "source_refs": [r.model_dump(mode="json") for r in prediction.source_refs],
        },
        expected={"gallery": list(gallery), "relevant": list(relevant)},
        human_touched_prediction=prediction.human_effective_output is not None,
        evidence_origin=prediction.origin,
        issues=prediction.issues,
        ledger_refs=prediction.ledger_refs,
    )


def retrieval_statistic(rows: tuple[Outcome, ...], metric: str) -> Statistic:
    """Mean over positive queries; repeated whole groups retain every duplicate."""
    if metric not in METRICS or type(rows) is not tuple:
        raise ValueError("declared retrieval metric and tuple required")
    values = []
    for row in rows:
        if (
            not isinstance(row, Outcome)
            or row.field != FIELD
            or row.class_name is not None
            or row.eligibility != "eligible"
            or row.correct is not None
            or row.status in UNMEASURED
        ):
            raise ValueError("incomplete or wrong retrieval outcome")
        gallery, relevant = _reference(row.expected, row.item_id)
        payload = row.predicted
        if (
            type(payload) is not dict
            or set(payload)
            != {
                "ranking",
                "prediction_sha256",
                "coverage_receipt",
                "method_version",
                "config_sha256",
                "source_refs",
            }
            or type(payload["ranking"]) is not list
        ):
            raise ValueError("bound prediction and complete feature coverage required")
        _id(payload["coverage_receipt"])
        if (
            type(payload["method_version"]) is not str
            or not 1 <= len(payload["method_version"]) <= 512
            or type(payload["source_refs"]) is not list
            or any(
                type(payload[key]) is not str or not re.fullmatch(r"[a-f0-9]{64}", payload[key])
                for key in ("prediction_sha256", "config_sha256")
            )
        ):
            raise ValueError("invalid bound prediction lineage")
        for reference in payload["source_refs"]:
            SourceRef.model_validate(reference)
        ranking = tuple(payload["ranking"])
        if row.status != "ok" and ranking:
            raise ValueError("failed attempt cannot become a successful ranking")
        result = score_ranking(ranking, relevant, gallery)
        if relevant:
            values.append(result["metrics"][metric])
    return (
        Statistic(math.fsum(values) / len(values), len(values))
        if values
        else Statistic(None, 0, "no_positive_queries")
    )


def statistic_version(metric: str) -> str:
    if metric not in METRICS:
        raise ValueError("unknown retrieval metric")
    return f"s7-positive-query-{metric}/1"


def resample_retrieval(
    outcomes_by_method: Mapping[str, tuple[Outcome, ...]],
    spec: ResamplingSpec,
    metric: str,
) -> PairedResampling:
    """One actual canonical common-stream resampling call for one frozen metric."""
    if not isinstance(spec, ResamplingSpec) or (
        spec.min_support != 1
        or spec.min_valid_draws != 1900
        or spec.statistic_version != statistic_version(metric)
    ):
        raise ValueError("fixed S7 retrieval support/version policy required")
    if not 1 <= len(outcomes_by_method) <= 32:
        raise ValueError("bounded named methods required")
    # Reject a varying-gallery population even when each method used the same
    # inconsistent reference. The canonical engine separately checks paired axes.
    gallery_view = None
    for rows in outcomes_by_method.values():
        if type(rows) is not tuple or not 1 <= len(rows) <= MAX_CASES:
            raise ValueError("bounded expected query population required")
        for row in rows:
            gallery, _ = _reference(row.expected, row.item_id)
            view = canonical_bytes(gallery)
            if gallery_view is not None and view != gallery_view:
                raise ValueError("frozen gallery changed within population")
            gallery_view = view
    return paired_group_resample(
        outcomes_by_method, spec, lambda rows: retrieval_statistic(rows, metric)
    )
