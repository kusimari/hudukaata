"""Tests for scanner functionality — FileMediaSource.scan()."""

from __future__ import annotations

import pytest
from common.media import FileMediaSource


@pytest.fixture()
def media_dir(tmp_path):
    files = {
        "photo.jpg": "image",
        "clip.mp4": "video",
        "song.mp3": "audio",
        "readme.txt": None,  # should be ignored
        "sub/nested.png": "image",
    }
    for rel in files:
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"data")
    return tmp_path, files


class TestScan:
    def test_known_types_are_yielded(self, media_dir):
        root, _ = media_dir
        src = FileMediaSource(path=str(root))
        names = {mf.relative_path for mf in src.scan()}
        assert "photo.jpg" in names
        assert "clip.mp4" in names
        assert "song.mp3" in names
        assert "sub/nested.png" in names

    def test_unknown_extensions_excluded(self, media_dir):
        root, _ = media_dir
        src = FileMediaSource(path=str(root))
        assert all(not mf.relative_path.endswith(".txt") for mf in src.scan())

    def test_correct_media_types(self, media_dir):
        root, _ = media_dir
        src = FileMediaSource(path=str(root))
        by_name = {mf.relative_path: mf.media_type for mf in src.scan()}
        assert by_name["photo.jpg"] == "image"
        assert by_name["clip.mp4"] == "video"
        assert by_name["song.mp3"] == "audio"
        assert by_name["sub/nested.png"] == "image"

    def test_local_path_exists_inside_with(self, media_dir):
        root, _ = media_dir
        src = FileMediaSource(path=str(root))
        for mf in src.scan():
            with mf:
                assert mf.local_path.exists()
