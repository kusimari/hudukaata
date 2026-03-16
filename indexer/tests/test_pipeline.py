"""Tests for pipeline.py — Stage, BatchItem, OneByOneRunner, AdaptiveBatchRunner."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from common.media import MediaFile

from indexer.batch import AdaptiveBatchController
from indexer.pipeline import AdaptiveBatchRunner, BatchItem, OneByOneRunner, Stage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(path: str = "a.jpg") -> BatchItem:
    mf = MagicMock(spec=MediaFile)
    mf.relative_path = path
    mf.mtime = None
    return BatchItem(media_file=mf)


def _passthrough(items: list[BatchItem]) -> list[BatchItem]:
    return items


def _drop_all(items: list[BatchItem]) -> list[BatchItem]:
    return []


def _double(items: list[BatchItem]) -> list[BatchItem]:
    """Return each item twice — stage that changes length."""
    return [item for item in items for _ in range(2)]


def _fixed_ctrl(size: int = 2) -> AdaptiveBatchController:
    return AdaptiveBatchController(initial_size=size, max_size=size, adaptive=False)


# ---------------------------------------------------------------------------
# BatchItem
# ---------------------------------------------------------------------------


class TestBatchItem:
    def test_defaults(self) -> None:
        item = _item()
        assert item.file_mtime == ""
        assert item.caption == ""
        assert item.exif == {}
        assert item.text == ""
        assert item.face_vectors == []

    def test_stack_is_fresh_exitstack(self) -> None:
        item = _item()
        assert isinstance(item._stack, ExitStack)

    def test_two_items_have_independent_stacks(self) -> None:
        a, b = _item(), _item()
        assert a._stack is not b._stack


# ---------------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------------


class TestStage:
    def test_frozen(self) -> None:
        s = Stage(_passthrough, batched=True)
        with pytest.raises(AttributeError):
            s.batched = False  # type: ignore[misc]

    def test_default_not_batched(self) -> None:
        s = Stage(_passthrough)
        assert s.batched is False


# ---------------------------------------------------------------------------
# OneByOneRunner
# ---------------------------------------------------------------------------


class TestOneByOneRunner:
    def test_empty_source(self) -> None:
        runner = OneByOneRunner()
        pipeline = [Stage(_passthrough)]
        assert list(runner.stream(pipeline, [])) == []

    def test_single_item_passthrough(self) -> None:
        runner = OneByOneRunner()
        item = _item()
        result = list(runner.stream([Stage(_passthrough)], [item]))
        assert result == [item]

    def test_multiple_stages_applied_in_order(self) -> None:
        seen: list[str] = []

        def stage_a(items: list[BatchItem]) -> list[BatchItem]:
            seen.append("a")
            return items

        def stage_b(items: list[BatchItem]) -> list[BatchItem]:
            seen.append("b")
            return items

        runner = OneByOneRunner()
        list(runner.stream([Stage(stage_a), Stage(stage_b)], [_item()]))
        assert seen == ["a", "b"]

    def test_exception_in_stage_logs_warning_and_drops_item(self) -> None:
        def bad_stage(items: list[BatchItem]) -> list[BatchItem]:
            raise ValueError("boom")

        runner = OneByOneRunner()
        with patch("indexer.pipeline.logger") as mock_log:
            result = list(runner.stream([Stage(bad_stage)], [_item()]))
        assert result == []
        mock_log.warning.assert_called_once()

    def test_drop_does_not_propagate_to_next_stage(self) -> None:
        calls: list[str] = []

        def recorder(items: list[BatchItem]) -> list[BatchItem]:
            calls.append("called")
            return items

        runner = OneByOneRunner()
        list(runner.stream([Stage(_drop_all), Stage(recorder)], [_item()]))
        # recorder should never be called because _drop_all returned []
        assert calls == []

    def test_passes_item_singly_regardless_of_batched_flag(self) -> None:
        received_lengths: list[int] = []

        def recorder(items: list[BatchItem]) -> list[BatchItem]:
            received_lengths.append(len(items))
            return items

        runner = OneByOneRunner()
        items = [_item("a.jpg"), _item("b.jpg")]
        list(runner.stream([Stage(recorder, batched=True)], items))
        assert received_lengths == [1, 1]


# ---------------------------------------------------------------------------
# AdaptiveBatchRunner — unbatched stages
# ---------------------------------------------------------------------------


class TestAdaptiveBatchRunnerUnbatched:
    def test_empty_source(self) -> None:
        runner = AdaptiveBatchRunner(_fixed_ctrl())
        assert list(runner.stream([Stage(_passthrough)], [])) == []

    def test_items_pass_through(self) -> None:
        runner = AdaptiveBatchRunner(_fixed_ctrl())
        items = [_item("a.jpg"), _item("b.jpg")]
        result = list(runner.stream([Stage(_passthrough)], items))
        assert result == items

    def test_exception_drops_item_and_logs(self) -> None:
        def bad(items: list[BatchItem]) -> list[BatchItem]:
            raise RuntimeError("bad")

        runner = AdaptiveBatchRunner(_fixed_ctrl())
        with patch("indexer.pipeline.logger") as mock_log:
            result = list(runner.stream([Stage(bad)], [_item()]))
        assert result == []
        mock_log.warning.assert_called_once()


# ---------------------------------------------------------------------------
# AdaptiveBatchRunner — batched stages
# ---------------------------------------------------------------------------


class TestAdaptiveBatchRunnerBatched:
    def test_flushes_when_buffer_full(self) -> None:
        flush_sizes: list[int] = []

        def recorder(items: list[BatchItem]) -> list[BatchItem]:
            flush_sizes.append(len(items))
            return items

        runner = AdaptiveBatchRunner(_fixed_ctrl(size=2))
        items = [_item(f"{i}.jpg") for i in range(4)]
        list(runner.stream([Stage(recorder, batched=True)], items))
        assert flush_sizes == [2, 2]

    def test_tail_items_flushed(self) -> None:
        flush_sizes: list[int] = []

        def recorder(items: list[BatchItem]) -> list[BatchItem]:
            flush_sizes.append(len(items))
            return items

        runner = AdaptiveBatchRunner(_fixed_ctrl(size=2))
        items = [_item(f"{i}.jpg") for i in range(3)]
        list(runner.stream([Stage(recorder, batched=True)], items))
        assert flush_sizes == [2, 1]

    def test_records_batch_timing(self) -> None:
        ctrl = AdaptiveBatchController(initial_size=2, max_size=8, adaptive=True)
        runner = AdaptiveBatchRunner(ctrl)

        def slow(items: list[BatchItem]) -> list[BatchItem]:
            return items

        with patch("indexer.pipeline.time") as mock_time:
            mock_time.monotonic.side_effect = [0.0, 5.0, 5.0, 9.0]
            items = [_item(f"{i}.jpg") for i in range(4)]
            list(runner.stream([Stage(slow, batched=True)], items))

        assert len(ctrl._history) == 2


# ---------------------------------------------------------------------------
# AdaptiveBatchRunner — OOM handling
# ---------------------------------------------------------------------------


class TestAdaptiveBatchRunnerOOM:
    def test_oom_fallback_to_one_by_one(self) -> None:
        call_count = 0

        def first_batch_fails(items: list[BatchItem]) -> list[BatchItem]:
            nonlocal call_count
            call_count += 1
            if len(items) > 1 and call_count == 1:
                raise RuntimeError("CUDA out of memory: tried to allocate 1 GiB")
            return items

        ctrl = AdaptiveBatchController(initial_size=2, max_size=4, adaptive=True)
        runner = AdaptiveBatchRunner(ctrl)
        items = [_item("a.jpg"), _item("b.jpg")]

        with patch("indexer.pipeline.logger"):
            result = list(runner.stream([Stage(first_batch_fails, batched=True)], items))

        assert len(result) == 2

    def test_oom_calls_on_oom(self) -> None:
        def always_oom(items: list[BatchItem]) -> list[BatchItem]:
            if len(items) > 1:
                raise MemoryError("out of memory")
            return items

        ctrl = AdaptiveBatchController(initial_size=2, max_size=4, adaptive=True)
        original_size = ctrl.current_size
        runner = AdaptiveBatchRunner(ctrl)

        with patch("indexer.pipeline.logger"):
            list(runner.stream([Stage(always_oom, batched=True)], [_item(), _item()]))

        assert ctrl.current_size < original_size

    def test_non_oom_runtimeerror_propagates(self) -> None:
        def bad(items: list[BatchItem]) -> list[BatchItem]:
            raise RuntimeError("unrelated error")

        runner = AdaptiveBatchRunner(_fixed_ctrl(size=1))
        with pytest.raises(RuntimeError, match="unrelated error"):
            list(runner.stream([Stage(bad, batched=True)], [_item()]))
