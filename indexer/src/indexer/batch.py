"""Adaptive batch-size controller for constrained-hardware indexing."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_GROW_THRESHOLD = 0.8  # grow when secs_per_item < target * this
_SHRINK_THRESHOLD = 1.5  # shrink when secs_per_item > target * this


@dataclass
class _BatchRecord:
    n_items: int
    elapsed_secs: float

    @property
    def secs_per_item(self) -> float:
        return self.elapsed_secs / self.n_items if self.n_items > 0 else float("inf")


class AdaptiveBatchController:
    """Tracks timing across batches and adjusts batch size dynamically.

    Strategy:
    - After each batch, compute secs-per-item.
    - If well below target → double batch size (up to max_size).
    - If well above target → halve batch size (floor 1).
    - If system RAM < memory_headroom_mb → halve immediately.
    - On explicit OOM signal (``on_oom()``) → halve immediately.

    When *adaptive* is False the batch size stays fixed at *initial_size*.
    """

    def __init__(
        self,
        initial_size: int = 1,
        max_size: int = 32,
        target_secs_per_item: float = 2.0,
        memory_headroom_mb: int = 512,
        adaptive: bool = True,
    ) -> None:
        if initial_size < 1:
            raise ValueError("initial_size must be >= 1")
        if max_size < initial_size:
            raise ValueError("max_size must be >= initial_size")
        self._size = initial_size
        self._max = max_size
        self._target = target_secs_per_item
        self._headroom_bytes = memory_headroom_mb * 1024 * 1024
        self._adaptive = adaptive
        self._history: list[_BatchRecord] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_size(self) -> int:
        """Current recommended batch size."""
        return self._size

    def record_batch(self, n_items: int, elapsed_secs: float) -> None:
        """Record a completed batch and adjust size for the next one."""
        if not self._adaptive:
            return
        rec = _BatchRecord(n_items=n_items, elapsed_secs=elapsed_secs)
        self._history.append(rec)

        spt = rec.secs_per_item
        if spt < self._target * _GROW_THRESHOLD:
            self._grow()
        elif spt > self._target * _SHRINK_THRESHOLD:
            self._shrink("slow batch (%.2fs/item > %.2fs target)", spt, self._target)

        self._check_memory()

    def on_oom(self) -> None:
        """Call when an out-of-memory error occurs to halve the batch size."""
        self._shrink("OOM signal")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _grow(self) -> None:
        new_size = min(self._size * 2, self._max)
        if new_size != self._size:
            logger.info("Adaptive batch: %d → %d (fast batch)", self._size, new_size)
            self._size = new_size

    def _shrink(self, reason: str, *args: object) -> None:
        new_size = max(self._size // 2, 1)
        if new_size != self._size:
            logger.warning("Adaptive batch: %d → %d (" + reason + ")", self._size, new_size, *args)
            self._size = new_size

    def _check_memory(self) -> None:
        if self._headroom_bytes <= 0:
            return
        try:
            import psutil

            available = psutil.virtual_memory().available
            if available < self._headroom_bytes:
                self._shrink(
                    "low RAM (%dMB available < %dMB headroom)",
                    available // (1024 * 1024),
                    self._headroom_bytes // (1024 * 1024),
                )
        except ImportError:
            pass  # psutil not installed; skip memory check
