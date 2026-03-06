"""Tests for scanner functionality — now part of MediaPointer.scan()."""

from __future__ import annotations

import pytest

from indexer.pointer import MediaPointer


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
        root, expected = media_dir
        p = MediaPointer.parse(f"file://{root}")
        results = list(p.scan())
        names = {f.relative_path for f in results}
        assert "photo.jpg" in names
        assert "clip.mp4" in names
        assert "song.mp3" in names
        assert "sub/nested.png" in names

    def test_unknown_extensions_excluded(self, media_dir):
        root, _ = media_dir
        p = MediaPointer.parse(f"file://{root}")
        results = list(p.scan())
        assert all(not f.relative_path.endswith(".txt") for f in results)

    def test_correct_media_types(self, media_dir):
        root, expected = media_dir
        p = MediaPointer.parse(f"file://{root}")
        by_name = {f.relative_path: f.media_type for f in p.scan()}
        assert by_name["photo.jpg"] == "image"
        assert by_name["clip.mp4"] == "video"
        assert by_name["song.mp3"] == "audio"
        assert by_name["sub/nested.png"] == "image"

    def test_local_path_exists(self, media_dir):
        root, _ = media_dir
        p = MediaPointer.parse(f"file://{root}")
        for mf in p.scan():
            assert mf.local_path.exists()
