"""Time allocation test.

Phase 1 outcome: "Generate plans for different lecture durations. Verify that the
time allocation changes appropriately and remains within the available duration."
"""
from __future__ import annotations

import pytest

from app.services.timealloc import allocate


@pytest.mark.parametrize("duration", [30, 45, 50, 60, 75, 90, 120])
def test_allocation_sums_to_exactly_the_duration(duration):
    minutes = allocate([3, 1, 2, 1, 2, 1], duration)
    assert sum(minutes) == duration


@pytest.mark.parametrize("duration", [30, 50, 90])
def test_every_segment_gets_at_least_the_floor(duration):
    minutes = allocate([5, 1, 1, 1], duration, floor_minutes=2)
    assert min(minutes) >= 2


def test_larger_weight_never_gets_less_time():
    minutes = allocate([1, 5, 3], 60)
    assert minutes[1] > minutes[2] > minutes[0]


def test_allocation_scales_with_duration():
    short = allocate([3, 1, 2], 30)
    long = allocate([3, 1, 2], 90)
    assert sum(short) == 30 and sum(long) == 90
    assert all(l >= s for l, s in zip(long, short))


def test_missing_or_invalid_weights_still_get_time():
    minutes = allocate([0, -4, None, "x"], 40)  # type: ignore[list-item]
    assert sum(minutes) == 40
    assert min(minutes) > 0


def test_floor_is_relaxed_when_the_class_is_too_short_for_it():
    minutes = allocate([1] * 10, 12, floor_minutes=2)
    assert sum(minutes) == 12
    assert min(minutes) >= 1


def test_refuses_an_impossible_allocation():
    with pytest.raises(ValueError):
        allocate([1] * 10, 5)


def test_empty_plan_allocates_nothing():
    assert allocate([], 50) == []
