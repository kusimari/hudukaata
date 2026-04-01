"""Tests for Blip2SentTokExifChromaIndexer stage methods and pipeline assembly."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from common.media import MediaFile

from indexer.indexers.blip2_sentok_exif_chroma import Blip2SentTokExifChromaIndexer
from indexer.pipeline import BatchItem
from indexer.stages import (
    caption_stage,
    close_stage,
    exif_stage,
    format_text_stage,
    open_stage,
    upsert_captions_stage,
)
from tests.stubs.caption_model import StubCaptionModel
from tests.stubs.index_store import StubIndexStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_mf(path: str = "a.jpg", mtime: float | None = 1234.0) -> MagicMock:
    mf = MagicMock(spec=MediaFile)
    mf.relative_path = path
    mf.mtime = mtime
    mf.media_type = "image"
    return mf


def _item(path: str = "a.jpg", mtime: float | None = 1234.0) -> BatchItem:
    return BatchItem(media_file=_mock_mf(path, mtime))


def _indexer(
    caption_model: StubCaptionModel | None = None,
    index_store: StubIndexStore | None = None,
) -> Blip2SentTokExifChromaIndexer:
    return Blip2SentTokExifChromaIndexer(
        caption_model=caption_model or StubCaptionModel(),
        index_store=index_store or StubIndexStore(),
    )


# ---------------------------------------------------------------------------
# open_stage
# ---------------------------------------------------------------------------


class TestOpenStage:
    def test_successful_open_sets_file_mtime(self) -> None:
        item = _item(mtime=9999.0)
        item.media_file.__enter__ = lambda s: s
        item.media_file.__exit__ = lambda s, *a: None

        fn = open_stage()[0].fn
        result = fn([item])

        assert len(result) == 1
        assert result[0].file_mtime == "9999.0"

    def test_none_mtime_yields_empty_string(self) -> None:
        item = _item(mtime=None)
        item.media_file.__enter__ = lambda s: s
        item.media_file.__exit__ = lambda s, *a: None

        fn = open_stage()[0].fn
        result = fn([item])
        assert result[0].file_mtime == ""

    def test_failed_open_drops_item_and_logs(self) -> None:
        item = _item()
        item.media_file.__enter__ = MagicMock(side_effect=OSError("no such file"))

        fn = open_stage()[0].fn
        with patch("indexer.stages.logger") as mock_log:
            result = fn([item])

        assert result == []
        mock_log.warning.assert_called_once()

    def test_empty_input(self) -> None:
        assert open_stage()[0].fn([]) == []


# ---------------------------------------------------------------------------
# caption_stage
# ---------------------------------------------------------------------------


class TestCaptionStage:
    def _open_item(self, path: str = "a.jpg") -> BatchItem:
        item = _item(path)
        item.media_file.__enter__ = lambda s: s
        item.media_file.__exit__ = lambda s, *a: None
        item._stack.enter_context(item.media_file)
        return item

    def test_sets_caption_on_each_item(self) -> None:
        items = [self._open_item("a.jpg"), self._open_item("b.jpg")]
        fn = caption_stage(StubCaptionModel())[0].fn
        result = fn(items)
        assert len(result) == 2
        assert result[0].caption == "a.jpg"
        assert result[1].caption == "b.jpg"

    def test_empty_input(self) -> None:
        assert caption_stage(StubCaptionModel())[0].fn([]) == []

    def test_failed_caption_marks_items_failed_and_does_not_close_stacks(self) -> None:
        items = [self._open_item("a.jpg"), self._open_item("b.jpg")]
        closed: list[str] = []

        for item in items:
            path = item.media_file.relative_path

            def closer(p: str = path) -> None:
                closed.append(p)

            item._stack.callback(closer)

        class FailModel(StubCaptionModel):
            def caption_batch(self, mfs):  # type: ignore[override]
                raise RuntimeError("model failed")

        fn = caption_stage(FailModel())[0].fn
        with patch("indexer.stages.logger"):
            result = fn(items)

        # All items are returned with _failed=True; drop_failed_stage handles cleanup.
        assert len(result) == 2
        assert all(item._failed for item in result)
        # Stacks are not closed here — that is drop_failed_stage's responsibility.
        assert closed == []


# ---------------------------------------------------------------------------
# exif_stage
# ---------------------------------------------------------------------------


class TestExifStage:
    def test_populates_exif_field(self) -> None:
        item = _item()
        with patch("indexer.stages.extract_exif", return_value={"width": "100"}):
            result = exif_stage()[0].fn([item])
        assert result[0].exif == {"width": "100"}

    def test_exif_failure_logs_and_continues(self) -> None:
        item = _item()
        with (
            patch("indexer.stages.extract_exif", side_effect=RuntimeError("bad")),
            patch("indexer.stages.logger") as mock_log,
        ):
            result = exif_stage()[0].fn([item])
        assert result == [item]
        mock_log.warning.assert_called_once()

    def test_empty_input(self) -> None:
        assert exif_stage()[0].fn([]) == []


# ---------------------------------------------------------------------------
# format_text_stage
# ---------------------------------------------------------------------------


class TestFormatTextStage:
    def test_sets_text_field(self) -> None:
        item = _item()
        item.caption = "a sunset"
        item.exif = {}
        result = format_text_stage()[0].fn([item])
        assert result[0].text == "a sunset"

    def test_includes_exif_in_text(self) -> None:
        item = _item()
        item.caption = "cat"
        item.exif = {"width": "100"}
        result = format_text_stage()[0].fn([item])
        assert "EXIF" in result[0].text
        assert "width: 100" in result[0].text


# ---------------------------------------------------------------------------
# upsert_stage
# ---------------------------------------------------------------------------


class TestUpsertStage:
    def test_calls_upsert_batch(self) -> None:
        store = StubIndexStore()
        store.create_empty()

        item = _item("a.jpg")
        item.caption = "a cat"
        item.file_mtime = "1234.0"
        item.text = "a cat"
        item.exif = {}

        result = upsert_captions_stage(store)[0].fn([item])

        assert result == [item]
        assert store.get_metadata("a.jpg") is not None

    def test_empty_input(self) -> None:
        store = StubIndexStore()
        store.create_empty()
        assert upsert_captions_stage(store)[0].fn([]) == []


# ---------------------------------------------------------------------------
# close_stage
# ---------------------------------------------------------------------------


class TestCloseStage:
    def test_closes_each_stack(self) -> None:
        items = [_item("a.jpg"), _item("b.jpg")]
        closed: list[str] = []
        for item in items:
            p = item.media_file.relative_path
            item._stack.callback(lambda path=p: closed.append(path))

        close_stage()[0].fn(items)
        assert set(closed) == {"a.jpg", "b.jpg"}

    def test_returns_all_items(self) -> None:
        items = [_item()]
        result = close_stage()[0].fn(items)
        assert result == items


# ---------------------------------------------------------------------------
# pipeline() — structure
# ---------------------------------------------------------------------------


class TestPipelineAssembly:
    def test_pipeline_has_six_stages(self) -> None:
        assert len(_indexer().pipeline()) == 6

    def test_stage_batched_flags(self) -> None:
        p = _indexer().pipeline()
        expected = [False, True, False, False, True, False]
        assert [s.batched for s in p] == expected

    def test_last_stage_closes_stacks(self) -> None:
        p = _indexer().pipeline()
        item = _item()
        closed: list[str] = []
        item._stack.callback(lambda: closed.append("done"))
        p[-1].fn([item])
        assert closed == ["done"]


# ---------------------------------------------------------------------------
# controller()
# ---------------------------------------------------------------------------


class TestController:
    def test_returns_controller_with_given_params(self) -> None:
        ctrl = _indexer().controller(initial_size=4, max_size=8, adaptive=False)
        assert ctrl.current_size == 4
