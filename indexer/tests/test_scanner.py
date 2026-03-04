"""Tests for scanner.py."""

from __future__ import annotations

import pytest

from indexer.pointer import MediaPointer
from indexer.scanner import scan


@pytest.fixture()
def media_dir(tmp_path):
    files = {
        "photo.jpg": "image",
        "clip.mp4": "video",
        "song.mp3": "audio",
        "readme.txt": None,   # should be ignored
        "sub/nested.png": "image",
    }
    for rel, _ in files.items():
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"data")
    return tmp_path, files


def _pointer(path):
    return MediaPointer(scheme="file", remote=None, path=str(path))


class TestScan:
    def test_recognised_extensions(self, media_dir):
        root, expected = media_dir
        results = {mf.relative_path: mf.media_type for mf in scan(_pointer(root))}

        assert results["photo.jpg"] == "image"
        assert results["clip.mp4"] == "video"
        assert results["song.mp3"] == "audio"
        assert "sub/nested.png" in results or "sub\\nested.png" in results

    def test_unrecognised_files_excluded(self, media_dir):
        root, _ = media_dir
        results = {mf.relative_path for mf in scan(_pointer(root))}
        assert not any(r.endswith(".txt") for r in results)

    def test_empty_directory(self, tmp_path):
        assert list(scan(_pointer(tmp_path))) == []

    def test_case_insensitive_extension(self, tmp_path):
        (tmp_path / "IMG.JPG").write_bytes(b"data")
        results = list(scan(_pointer(tmp_path)))
        assert len(results) == 1
        assert results[0].media_type == "image"
