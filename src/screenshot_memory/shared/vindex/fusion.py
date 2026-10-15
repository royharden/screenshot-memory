"""Pure fixed-leg reciprocal-rank fusion; callers own actual eligibility."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

LEGS = ("keyword", "combined", "image")
RRF_OFFSET = 60
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


@dataclass(frozen=True)
class FusedHit:
    item_id: str
    score: float
    ranks: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class FusionResult:
    hits: tuple[FusedHit, ...]
    active_legs: tuple[str, ...]
    unavailable_legs: tuple[str, ...]
    status: str


def _ids(values: tuple[str, ...], *, nonempty: bool = False) -> None:
    if (
        type(values) is not tuple
        or len(values) > 30
        or (nonempty and not values)
        or any(type(value) is not str or not _ID.fullmatch(value) for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("invalid, duplicate or oversized item IDs")


def fuse(rankings: Mapping[str, tuple[str, ...] | None], eligible: tuple[str, ...]) -> FusionResult:
    """Sum1/(60+rank), union only, one vote per fixed production leg/item.

    None means unavailable. () means executed with no hits, an active leg.
    Input ranks must already cover the caller's intended full eligible corpus;
    this math cannot prove execution, namespace/generation or completeness.
    Scores are rank-fusion weights, never probabilities or calibrated no-answer.
    """
    _ids(eligible, nonempty=True)
    if not isinstance(rankings, Mapping) or set(rankings) != set(LEGS):
        raise ValueError("exact keyword/combined/image production legs required")
    allowed = set(eligible)
    votes: dict[str, list[tuple[str, int]]] = {}
    active = []
    unavailable = []
    for leg in LEGS:
        ranking = rankings[leg]
        if ranking is None:
            unavailable.append(leg)
            continue
        _ids(ranking)
        if not set(ranking) <= allowed:
            raise ValueError("ranked item outside caller-eligible gallery")
        active.append(leg)
        for rank, item_id in enumerate(ranking, 1):
            votes.setdefault(item_id, []).append((leg, rank))
    hits = tuple(
        sorted(
            (
                FusedHit(
                    item_id,
                    math.fsum(1 / (RRF_OFFSET + rank) for _, rank in ranks),
                    tuple(ranks),
                )
                for item_id, ranks in votes.items()
            ),
            key=lambda hit: (-hit.score, hit.item_id),
        )
    )
    status = "unavailable" if not active else "degraded" if unavailable else "available"
    return FusionResult(hits, tuple(active), tuple(unavailable), status)
