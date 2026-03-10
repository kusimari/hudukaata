"""Tests for exif.py — uses a synthetic Pillow-generated JPEG."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from indexer.exif import extract_exif
from indexer.pointer import MediaFile, _LocalFile


@pytest.fixture()
def jpeg_file(tmp_path) -> Path:
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")
    img = Image.new("RGB", (64, 64), color=(128, 0, 0))
    path = tmp_path / "test.jpg"
    img.save(path, "JPEG")
    return path


def _mf(path: Path, media_type: Literal["image", "video", "audio"] = "image") -> MediaFile:
    return MediaFile(
        relative_path=path.name,
        media_type=media_type,
        _ctx=_LocalFile(path),
    )


class TestExtractExif:
    def test_image_returns_dict(self, jpeg_file):
        mf = _mf(jpeg_file)
        with mf:
            result = extract_exif(mf)
        assert isinstance(result, dict)
        # All values must be strings
        for k, v in result.items():
            assert isinstance(k, str)
            assert isinstance(v, str)

    def test_image_has_dimensions(self, jpeg_file):
        mf = _mf(jpeg_file)
        with mf:
            result = extract_exif(mf)
        assert result.get("width") == "64"
        assert result.get("height") == "64"

    def test_missing_file_returns_empty(self, tmp_path):
        mf = MediaFile(
            relative_path="missing.jpg",
            media_type="image",
            _ctx=_LocalFile(tmp_path / "missing.jpg"),
        )
        with mf:
            result = extract_exif(mf)
        assert isinstance(result, dict)
