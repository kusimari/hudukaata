"""Tests for ParallelStage in OneByOneRunner and AdaptiveBatchRunner,
and for drop_failed_stage in stages.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from common.media import MediaFile

from indexer.batch import AdaptiveBatchController
from indexer.pipeline import AdaptiveBatchRunner, BatchItem, OneByOneRunner, ParallelStage, Stage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(path: str = "a.jpg") -> BatchItem:
    mf = MagicMock(spec=MediaFile)
    mf.relative_path = path
    mf.mtime = None
    return BatchItem(media_file=mf)


def _fixed_ctrl(size: int = 4) -> AdaptiveBatchController:
    return AdaptiveBatchController(initial_size=size, max_size=size, adaptive=False)


def _set_field(name: str, value: object = "x"):
    """Return a stage fn that sets item.<name> = value on every item."""

    def fn(items: list[BatchItem]) -> list[BatchItem]:
        for item in items:
            setattr(item, name, value)
        return items

    return fn


def _drop_all(items: list[BatchItem]) -> list[BatchItem]:
    return []


def _raise_always(items: list[BatchItem]) -> list[BatchItem]:
    raise RuntimeError("stage error")


# ---------------------------------------------------------------------------
# ParallelStage.batched property
# ---------------------------------------------------------------------------


class TestParallelStageBatched:
    def test_batched_true_if_any_sub_stage_batched(self) -> None:
        ps = ParallelStage(
            [Stage(_set_field("caption"), batched=False), Stage(_set_field("exif"), batched=True)]
        )
        assert ps.batched is True

    def test_batched_false_if_no_sub_stage_batched(self) -> None:
        ps = ParallelStage(
            [Stage(_set_field("caption"), batched=False), Stage(_set_field("exif"), batched=False)]
        )
        assert ps.batched is False


# ---------------------------------------------------------------------------
# OneByOneRunner + ParallelStage
# ---------------------------------------------------------------------------


class TestOneByOneRunnerParallel:
    def test_both_stages_run(self) -> None:
        item = _item()
        ps = ParallelStage(
            [Stage(_set_field("caption", "cap")), Stage(_set_field("exif", {"k": "v"}))]
        )
        runner = OneByOneRunner()
        result = list(runner.stream([ps], [item]))
        assert len(result) == 1
        assert result[0].caption == "cap"
        assert result[0].exif == {"k": "v"}

    def test_item_dropped_if_any_stage_drops(self) -> None:
        item = _item()
        closed: list[bool] = []
        item._stack.callback(lambda: closed.append(True))

        ps = ParallelStage([Stage(_drop_all), Stage(_set_field("caption", "cap"))])
        runner = OneByOneRunner()
        with patch("indexer.pipeline.logger"):
            result = list(runner.stream([ps], [item]))
        assert result == []
        assert closed == [True]

    def test_item_dropped_if_any_stage_raises(self) -> None:
        item = _item()
        closed: list[bool] = []
        item._stack.callback(lambda: closed.append(True))

        ps = ParallelStage([Stage(_raise_always), Stage(_set_field("caption", "cap"))])
        runner = OneByOneRunner()
        with patch("indexer.pipeline.logger"):
            result = list(runner.stream([ps], [item]))
        assert result == []
        assert closed == [True]

    def test_surviving_item_yields(self) -> None:
        item = _item()
        ps = ParallelStage([Stage(_set_field("caption", "ok")), Stage(_set_field("exif", {}))])
        runner = OneByOneRunner()
        result = list(runner.stream([ps], [item]))
        assert result == [item]


# ---------------------------------------------------------------------------
# AdaptiveBatchRunner + ParallelStage
# ---------------------------------------------------------------------------


class TestAdaptiveBatchRunnerParallel:
    def test_both_stages_run_on_batch(self) -> None:
        items = [_item(f"{i}.jpg") for i in range(3)]
        ps = ParallelStage(
            [
                Stage(_set_field("caption", "cap"), batched=True),
                Stage(_set_field("exif", {"k": "v"}), batched=True),
            ]
        )
        runner = AdaptiveBatchRunner(_fixed_ctrl(size=4))
        result = list(runner.stream([ps], items))
        assert len(result) == 3
        for r in result:
            assert r.caption == "cap"
            assert r.exif == {"k": "v"}

    def test_intersection_drops_item_dropped_by_one_stage(self) -> None:
        a, b = _item("a.jpg"), _item("b.jpg")
        closed: list[str] = []
        a._stack.callback(lambda: closed.append("a"))

        def drop_first(items: list[BatchItem]) -> list[BatchItem]:
            return items[1:]  # drop 'a'

        ps = ParallelStage(
            [
                Stage(drop_first, batched=True),
                Stage(_set_field("exif", {}), batched=True),
            ]
        )
        runner = AdaptiveBatchRunner(_fixed_ctrl(size=4))
        result = list(runner.stream([ps], [a, b]))
        assert len(result) == 1
        assert result[0] is b
        assert "a" in closed

    def test_oom_falls_back_to_one_by_one(self) -> None:
        items = [_item(f"{i}.jpg") for i in range(2)]
        call_count = 0

        def oom_on_batch(batch: list[BatchItem]) -> list[BatchItem]:
            nonlocal call_count
            call_count += 1
            if len(batch) > 1:
                raise MemoryError("out of memory")
            return batch

        ps = ParallelStage([Stage(oom_on_batch, batched=True)])
        ctrl = AdaptiveBatchController(initial_size=2, max_size=2, adaptive=False)
        runner = AdaptiveBatchRunner(ctrl)
        with patch("indexer.pipeline.logger"):
            result = list(runner.stream([ps], items))
        assert len(result) == 2


# ---------------------------------------------------------------------------
# drop_failed_stage
# ---------------------------------------------------------------------------


class TestDropFailedStage:
    def test_keeps_non_failed_items(self) -> None:
        from indexer.stages import drop_failed_stage

        item = _item()
        stages = drop_failed_stage()
        assert len(stages) == 1
        result = stages[0].fn([item])
        assert result == [item]

    def test_drops_failed_items_and_closes_stack(self) -> None:
        from indexer.stages import drop_failed_stage

        item = _item()
        item._failed = True
        closed: list[bool] = []
        item._stack.callback(lambda: closed.append(True))

        stages = drop_failed_stage()
        result = stages[0].fn([item])
        assert result == []
        assert closed == [True]

    def test_mixed_batch(self) -> None:
        from indexer.stages import drop_failed_stage

        ok = _item("ok.jpg")
        bad = _item("bad.jpg")
        bad._failed = True
        closed: list[bool] = []
        bad._stack.callback(lambda: closed.append(True))

        stages = drop_failed_stage()
        result = stages[0].fn([ok, bad])
        assert result == [ok]
        assert closed == [True]
