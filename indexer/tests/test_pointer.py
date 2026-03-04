"""Tests for pointer.py."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from indexer.pointer import MediaPointer


class TestParse:
    def test_file_scheme(self):
        p = MediaPointer.parse("file:///tmp/media")
        assert p.scheme == "file"
        assert p.remote is None
        assert p.path == "/tmp/media"

    def test_rclone_scheme(self):
        p = MediaPointer.parse("rclone:my-remote:///path/on/remote")
        assert p.scheme == "rclone"
        assert p.remote == "my-remote"
        assert p.path == "path/on/remote"

    def test_rclone_single_slash(self):
        p = MediaPointer.parse("rclone:gdrive:/photos")
        assert p.scheme == "rclone"
        assert p.remote == "gdrive"
        assert p.path == "photos"

    def test_unsupported_scheme_raises(self):
        with pytest.raises(ValueError, match="Unsupported URI scheme"):
            MediaPointer.parse("s3://bucket/path")


class TestFileIterFiles:
    def test_yields_all_files(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"img")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.mp4").write_bytes(b"vid")

        p = MediaPointer(scheme="file", remote=None, path=str(tmp_path))
        files = dict(p.iter_files())

        assert "a.jpg" in files
        assert os.path.join("sub", "b.mp4") in files

    def test_yields_nothing_for_empty_dir(self, tmp_path):
        p = MediaPointer(scheme="file", remote=None, path=str(tmp_path))
        assert list(p.iter_files()) == []


class TestFileHasDir:
    def test_existing_dir(self, tmp_path):
        (tmp_path / "db").mkdir()
        p = MediaPointer(scheme="file", remote=None, path=str(tmp_path))
        assert p.has_dir("db") is True

    def test_missing_dir(self, tmp_path):
        p = MediaPointer(scheme="file", remote=None, path=str(tmp_path))
        assert p.has_dir("db") is False


class TestFileRenameDir:
    def test_rename(self, tmp_path):
        (tmp_path / "old").mkdir()
        p = MediaPointer(scheme="file", remote=None, path=str(tmp_path))
        p.rename_dir("old", "new")
        assert (tmp_path / "new").is_dir()
        assert not (tmp_path / "old").exists()
