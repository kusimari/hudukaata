"""Unit tests for AdaptiveBatchController."""

from __future__ import annotations

import pytest

from indexer.batch import AdaptiveBatchController


def make(
    initial: int = 1,
    max_size: int = 32,
    target: float = 2.0,
    headroom: int = 0,  # 0 disables memory check in tests
    adaptive: bool = True,
) -> AdaptiveBatchController:
    return AdaptiveBatchController(
        initial_size=initial,
        max_size=max_size,
        target_secs_per_item=target,
        memory_headroom_mb=headroom,
        adaptive=adaptive,
    )


class TestInit:
    def test_starts_at_initial_size(self) -> None:
        ctrl = make(initial=1)
        assert ctrl.current_size == 1

    def test_initial_size_four(self) -> None:
        ctrl = make(initial=4, max_size=16)
        assert ctrl.current_size == 4

    def test_invalid_initial_size(self) -> None:
        with pytest.raises(ValueError, match="initial_size"):
            make(initial=0)

    def test_invalid_max_less_than_initial(self) -> None:
        with pytest.raises(ValueError, match="max_size"):
            make(initial=8, max_size=4)


class TestGrowth:
    def test_doubles_when_fast(self) -> None:
        ctrl = make(initial=1, max_size=32, target=2.0)
        # secs_per_item = 0.5 < 2.0 * 0.8 = 1.6 → grow
        ctrl.record_batch(n_items=4, elapsed_secs=2.0)
        assert ctrl.current_size == 2

    def test_does_not_exceed_max(self) -> None:
        ctrl = make(initial=16, max_size=16, target=2.0)
        ctrl.record_batch(n_items=1, elapsed_secs=0.1)
        assert ctrl.current_size == 16

    def test_doubles_multiple_times(self) -> None:
        ctrl = make(initial=1, max_size=32, target=2.0)
        for _ in range(3):
            ctrl.record_batch(n_items=4, elapsed_secs=2.0)  # 0.5 s/item
        assert ctrl.current_size == 8  # 1 → 2 → 4 → 8

    def test_stays_put_when_at_target(self) -> None:
        ctrl = make(initial=4, max_size=32, target=2.0)
        # secs_per_item = 2.0 — exactly at target, neither grow nor shrink
        ctrl.record_batch(n_items=4, elapsed_secs=8.0)
        assert ctrl.current_size == 4


class TestShrink:
    def test_halves_when_slow(self) -> None:
        ctrl = make(initial=8, max_size=32, target=2.0)
        # secs_per_item = 4.0 > 2.0 * 1.5 = 3.0 → shrink
        ctrl.record_batch(n_items=4, elapsed_secs=16.0)
        assert ctrl.current_size == 4

    def test_floor_is_one(self) -> None:
        ctrl = make(initial=1, max_size=32, target=2.0)
        ctrl.record_batch(n_items=1, elapsed_secs=10.0)
        assert ctrl.current_size == 1

    def test_on_oom_halves(self) -> None:
        ctrl = make(initial=8, max_size=32)
        ctrl.on_oom()
        assert ctrl.current_size == 4

    def test_on_oom_floors_at_one(self) -> None:
        ctrl = make(initial=1, max_size=32)
        ctrl.on_oom()
        assert ctrl.current_size == 1

    def test_repeated_oom(self) -> None:
        ctrl = make(initial=16, max_size=32)
        ctrl.on_oom()
        ctrl.on_oom()
        ctrl.on_oom()
        ctrl.on_oom()
        ctrl.on_oom()
        assert ctrl.current_size == 1


class TestNonAdaptive:
    def test_fixed_size_ignores_timing(self) -> None:
        ctrl = make(initial=4, max_size=32, adaptive=False)
        ctrl.record_batch(n_items=4, elapsed_secs=0.001)  # very fast
        assert ctrl.current_size == 4

    def test_fixed_size_ignores_slow(self) -> None:
        ctrl = make(initial=4, max_size=32, adaptive=False)
        ctrl.record_batch(n_items=1, elapsed_secs=1000.0)  # very slow
        assert ctrl.current_size == 4

    def test_oom_still_shrinks_in_fixed_mode(self) -> None:
        # on_oom() always shrinks regardless of adaptive flag
        ctrl = make(initial=8, max_size=32, adaptive=False)
        ctrl.on_oom()
        assert ctrl.current_size == 4
