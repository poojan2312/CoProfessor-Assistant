"""Deterministic time allocation.

The model is asked for a relative `weight` per segment, never for minutes. This
module turns weights into whole minutes that sum to EXACTLY the lecture duration,
using largest-remainder (Hare-Niemeyer) apportionment with a per-segment floor.

Rationale: language models are unreliable at arithmetic, and "the plan does not
fit the class hour" is the most visible possible failure in front of a professor.
Taking the arithmetic away from the model makes the time-allocation test pass by
construction at any duration.
"""
from __future__ import annotations


def allocate(weights: list[float], total_minutes: int, floor_minutes: int = 2) -> list[int]:
    """Apportion `total_minutes` across segments in proportion to `weights`.

    Guarantees: len(result) == len(weights), sum(result) == total_minutes, and
    every entry >= floor_minutes whenever the duration allows it.
    """
    n = len(weights)
    if n == 0:
        return []
    if total_minutes < n:
        raise ValueError(
            f"cannot allocate {total_minutes} minutes across {n} segments "
            "(fewer than one minute each)"
        )

    # A segment with a missing or nonsensical weight still deserves a share.
    clean = [float(w) if isinstance(w, (int, float)) and w > 0 else 1.0 for w in weights]

    # Drop the floor if the duration is too short to honour it.
    floor = min(floor_minutes, total_minutes // n)
    remaining = total_minutes - floor * n

    total_weight = sum(clean)
    exact = [w / total_weight * remaining for w in clean]
    base = [int(x) for x in exact]

    # Hand out the leftover minutes to the largest fractional remainders.
    leftover = remaining - sum(base)
    order = sorted(range(n), key=lambda i: (exact[i] - base[i], clean[i]), reverse=True)
    for i in order[:leftover]:
        base[i] += 1

    return [floor + b for b in base]
