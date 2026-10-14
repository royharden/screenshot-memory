"""Pure S7 retrieval mathematics, separate from generic owner evalkit.

Inputs are caller declarations, not execution or reference authenticity proof.
Relevant IDs are scorer-private gallery asset IDs. Case IDs remain query IDs.
No source text, gold file, feature, prediction file or provider is accessed.
"""

import math
import re
from collections.abc import Mapping

METRICS = ("recall@1", "recall@3", "recall@5", "hit@1", "hit@3", "hit@5", "mrr")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
MAX_GALLERY = 30
MAX_CASES = 512


def _id(value: str) -> None:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError("invalid opaque identifier")


def _ids(values: tuple[str, ...], cap: int, *, empty: bool = True) -> None:
    if type(values) is not tuple or len(values) > cap or (not empty and not values):
        raise ValueError("invalid identifier tuple")
    for value in values:
        _id(value)
    if len(set(values)) != len(values):
        raise ValueError("duplicate identifiers")


def score_ranking(
    ranking: tuple[str, ...] | None,
    relevant: tuple[str, ...],
    gallery: tuple[str, ...],
) -> dict:
    """Full produced rank, no padding. None means unexecuted, () executed miss.

    Positive-case recall is |top-k intersect gold| / |gold|. Hit is separate.
    MRR uses the first relevant rank anywhere in the produced ranking, up to30.
    Empty target sets have no retrieval denominator, even if a rank was produced.
    """
    _ids(gallery, MAX_GALLERY, empty=False)
    _ids(relevant, MAX_GALLERY)
    allowed = set(gallery)
    if not set(relevant) <= allowed:
        raise ValueError("relevant asset outside declared gallery")
    if ranking is not None:
        _ids(ranking, MAX_GALLERY)
        if not set(ranking) <= allowed:
            raise ValueError("produced asset outside declared gallery")
    positive = bool(relevant)
    metrics = dict.fromkeys(METRICS)
    if ranking is not None and positive:
        gold = set(relevant)
        for k in (1, 3, 5):
            found = len(gold.intersection(ranking[:k]))
            metrics[f"recall@{k}"] = found / len(gold)
            metrics[f"hit@{k}"] = float(found > 0)
        first = next((i for i, value in enumerate(ranking, 1) if value in gold), None)
        metrics["mrr"] = 0.0 if first is None else 1.0 / first
    return {
        "status": "not_measured" if ranking is None else "measured",
        "positive": positive,
        "produced_count": None if ranking is None else len(ranking),
        "metrics": metrics,
    }


def score_method(
    cases: Mapping[str, tuple[str, ...]],
    produced: Mapping[str, tuple[str, ...] | None],
    gallery: tuple[str, ...],
) -> dict:
    """Macro over positive queries. An incomplete method has no aggregate score.

    Every case needs an explicit produced entry; no missing-as-zero coercion.
    An executor may represent a recorded eligible failed attempt by (). It must
    retain its actual failure status separately; this pure math cannot verify it.
    Guard/no-answer decisions and region grounding need separate measurements.
    """
    if not 1 <= len(cases) <= MAX_CASES or set(cases) != set(produced):
        raise ValueError("case coverage mismatch")
    for case_id in cases:
        _id(case_id)
        if case_id in gallery:
            raise ValueError("query/case ID is not a gallery asset ID")
    rows = {
        case_id: score_ranking(produced[case_id], gold, gallery) for case_id, gold in cases.items()
    }
    positives = sum(row["positive"] for row in rows.values())
    unexecuted = sum(row["status"] != "measured" for row in rows.values())
    metrics = dict.fromkeys(METRICS)
    if not unexecuted and positives:
        for metric in METRICS:
            metrics[metric] = (
                math.fsum(row["metrics"][metric] for row in rows.values() if row["positive"])
                / positives
            )
    return {
        "status": "incomplete" if unexecuted else "measured",
        "retrieval_applicability": "applicable" if positives else "not_applicable",
        "case_count": len(cases),
        "positive_cases": positives,
        "negative_cases": len(cases) - positives,
        "unexecuted_cases": unexecuted,
        "metrics": metrics,
        "per_case": rows,
    }


def grouped_mean(
    per_case: Mapping[str, float | None],
    group_by_case: Mapping[str, str],
    sampled_groups: tuple[str, ...],
) -> dict:
    """Domain callback for an externally supplied whole-group resample.

    Repeated groups repeat ALL their cases. None denotes an ineligible metric
    denominator (e.g. empty gold for recall), not an executed failure or a miss.
    A draw containing no eligible case returns None, never a made-up zero.
    This function neither draws samples nor supplies an uncertainty estimate.
    """
    if not 1 <= len(per_case) <= MAX_CASES or set(per_case) != set(group_by_case):
        raise ValueError("group/case coverage mismatch")
    groups: dict[str, list[float | None]] = {}
    for case_id, value in per_case.items():
        _id(case_id)
        group = group_by_case[case_id]
        _id(group)
        if value is not None and (
            type(value) not in {float, int} or not math.isfinite(value) or not 0 <= value <= 1
        ):
            raise ValueError("metric must be finite within zero and one")
        groups.setdefault(group, []).append(value)
    if type(sampled_groups) is not tuple or len(sampled_groups) != len(groups):
        raise ValueError("draw must sample the declared number of whole groups")
    values = []
    total = 0
    for group in sampled_groups:
        _id(group)
        if group not in groups:
            raise ValueError("draw contains undeclared group")
        total += len(groups[group])
        values.extend(value for value in groups[group] if value is not None)
    return {
        "value": math.fsum(values) / len(values) if values else None,
        "eligible_cases": len(values),
        "sampled_cases": total,
        "sampled_groups": len(sampled_groups),
    }


def paired_draw(
    per_case_by_method: Mapping[str, Mapping[str, float | None]],
    group_by_case: Mapping[str, str],
    sampled_groups: tuple[str, ...],
    reference_method: str,
) -> dict:
    """Apply the SAME group draw and eligibility to every method's domain score.

    Caller must first reject incomplete/unexecuted methods via score_method.
    Eligibility mismatches fail rather than silently comparing different cases.
    A delta here is arithmetic for one draw, not a measured benchmark or CI.
    """
    if not 2 <= len(per_case_by_method) <= 32 or reference_method not in per_case_by_method:
        raise ValueError("paired comparison requires declared reference and methods")
    reference = per_case_by_method[reference_method]
    estimates = {}
    eligible = None
    for method, values in per_case_by_method.items():
        _id(method)
        if set(values) != set(reference) or any(
            (values[key] is None) != (reference[key] is None) for key in reference
        ):
            raise ValueError("paired eligibility mismatch")
        result = grouped_mean(values, group_by_case, sampled_groups)
        estimates[method] = result["value"]
        if eligible is not None and result["eligible_cases"] != eligible:
            raise ValueError("paired denominator mismatch")
        eligible = result["eligible_cases"]
    baseline = estimates[reference_method]
    return {
        "estimates": estimates,
        "deltas_from_reference": {
            method: None if baseline is None else value - baseline
            for method, value in estimates.items()
        },
        "eligible_cases": eligible,
    }
