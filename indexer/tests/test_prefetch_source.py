"""Tests for PrefetchSource in pipeline.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from common.media import MediaFile

from indexer.pipeline import BatchItem, PrefetchSource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(path: str = "a.jpg", media_type: str = "image") -> BatchItem:
    mf = MagicMock(spec=MediaFile)
    mf.relative_path = path
    mf.media_type = media_type
    mf.local_path = f"/fake/{path}"
    return BatchItem(media_file=mf)


def _collect(source: PrefetchSource) -> list[BatchItem]:
    items = list(source)
    source.close()
    return items


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPrefetchSource:
    def test_yields_all_items(self) -> None:
        items = [_item(f"{i}.jpg") for i in range(5)]
        with patch("PIL.Image.open"):
            src = PrefetchSource(iter(items), max_prefetch=4, max_workers=2)
            result = _collect(src)
        assert len(result) == 5

    def test_sets_pil_image_on_image_items(self) -> None:
        sentinel = object()
        item = _item("photo.jpg", media_type="image")

        fake_image = MagicMock()
        fake_image.convert.return_value = sentinel

        with patch("PIL.Image.open", return_value=fake_image):
            src = PrefetchSource(iter([item]), max_prefetch=2, max_workers=1)
            result = _collect(src)

        assert len(result) == 1
        assert result[0].pil_image is sentinel

    def test_non_image_item_unchanged(self) -> None:
        item = _item("clip.mp4", media_type="video")
        src = PrefetchSource(iter([item]), max_prefetch=2, max_workers=1)
        result = _collect(src)
        assert len(result) == 1
        assert result[0].pil_image is None

    def test_empty_source(self) -> None:
        src = PrefetchSource(iter([]), max_prefetch=4, max_workers=2)
        result = _collect(src)
        assert result == []

    def test_failed_load_logs_warning_and_continues(self) -> None:
        item = _item("bad.jpg", media_type="image")

        with (
            patch("PIL.Image.open", side_effect=OSError("disk error")),
            patch("indexer.pipeline.logger") as mock_log,
        ):
            src = PrefetchSource(iter([item]), max_prefetch=2, max_workers=1)
            result = _collect(src)

        assert len(result) == 1
        assert result[0].pil_image is None
        mock_log.warning.assert_called_once()

    def test_close_shuts_down_cleanly(self) -> None:
        items = [_item(f"{i}.jpg") for i in range(3)]
        with patch("PIL.Image.open"):
            src = PrefetchSource(iter(items), max_prefetch=8, max_workers=2)
            list(src)
            src.close()  # should not raise
