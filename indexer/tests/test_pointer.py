"""Tests for pointer.py — MediaPointer and StorePointer."""

from __future__ import annotations

import pytest

from indexer.pointer import MediaPointer, StorePointer

# ---------------------------------------------------------------------------
# Parsing — shared by both pointer types
# ---------------------------------------------------------------------------


class TestParseMediaPointer:
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


class TestParseStorePointer:
    def test_file_scheme(self):
        p = StorePointer.parse("file:///tmp/store")
        assert p.scheme == "file"
        assert p.remote is None
        assert p.path == "/tmp/store"

    def test_rclone_scheme(self):
        p = StorePointer.parse("rclone:backup:///db")
        assert p.scheme == "rclone"
        assert p.remote == "backup"
        assert p.path == "db"


# ---------------------------------------------------------------------------
# URI property
# ---------------------------------------------------------------------------


class TestUri:
    def test_file_uri_roundtrip(self):
        p = MediaPointer.parse("file:///some/path")
        assert p.uri == "file:///some/path"

    def test_rclone_uri_roundtrip(self):
        p = MediaPointer.parse("rclone:gdrive:///photos")
        assert p.uri == "rclone:gdrive:///photos"

    def test_store_pointer_uri(self):
        p = StorePointer.parse("file:///tmp/store")
        assert p.uri == "file:///tmp/store"


# ---------------------------------------------------------------------------
# iter_files — file:// (no rclone needed)
# ---------------------------------------------------------------------------


class TestIterFiles:
    def test_yields_all_files(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.png").write_bytes(b"x")

        p = MediaPointer.parse(f"file://{tmp_path}")
        result = []
        for rel, ctx in p.iter_files():
            with ctx as local:
                result.append((rel, local.name))

        assert sorted(r[0] for r in result) == ["a.jpg", "sub/b.png"]

    def test_context_manager_returns_path(self, tmp_path):
        (tmp_path / "img.jpg").write_bytes(b"data")
        p = MediaPointer.parse(f"file://{tmp_path}")
        for _rel, ctx in p.iter_files():
            with ctx as local:
                assert local.exists()

    def test_empty_directory(self, tmp_path):
        p = MediaPointer.parse(f"file://{tmp_path}")
        assert list(p.iter_files()) == []


# ---------------------------------------------------------------------------
# scan — filters by recognised extension
# ---------------------------------------------------------------------------


class TestScan:
    def test_filters_to_known_media_types(self, tmp_path):
        (tmp_path / "photo.jpg").write_bytes(b"x")
        (tmp_path / "clip.mp4").write_bytes(b"x")
        (tmp_path / "song.mp3").write_bytes(b"x")
        (tmp_path / "readme.txt").write_bytes(b"x")

        p = MediaPointer.parse(f"file://{tmp_path}")
        files = list(p.scan())

        exts = {f.relative_path.split(".")[-1] for f in files}
        assert exts == {"jpg", "mp4", "mp3"}
        assert "readme.txt" not in {f.relative_path for f in files}

    def test_media_types_assigned_correctly(self, tmp_path):
        (tmp_path / "img.jpg").write_bytes(b"x")
        (tmp_path / "vid.mp4").write_bytes(b"x")
        (tmp_path / "aud.wav").write_bytes(b"x")

        p = MediaPointer.parse(f"file://{tmp_path}")
        by_name = {f.relative_path: f.media_type for f in p.scan()}

        assert by_name["img.jpg"] == "image"
        assert by_name["vid.mp4"] == "video"
        assert by_name["aud.wav"] == "audio"

    def test_nested_directories(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "nested.png").write_bytes(b"x")

        p = MediaPointer.parse(f"file://{tmp_path}")
        files = list(p.scan())
        assert any(f.relative_path == "sub/nested.png" for f in files)


# ---------------------------------------------------------------------------
# StorePointer — local filesystem operations
# ---------------------------------------------------------------------------


class TestStorePointer:
    def test_has_dir_true(self, tmp_path):
        (tmp_path / "db").mkdir()
        store = StorePointer.parse(f"file://{tmp_path}")
        assert store.has_dir("db") is True

    def test_has_dir_false(self, tmp_path):
        store = StorePointer.parse(f"file://{tmp_path}")
        assert store.has_dir("db") is False

    def test_put_and_get_dir(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "data.txt").write_text("hello")

        store_root = tmp_path / "store"
        store_root.mkdir()
        store = StorePointer.parse(f"file://{store_root}")

        store.put_dir(src, dest_name="uploaded")
        assert (store_root / "uploaded" / "data.txt").read_text() == "hello"

        local = store.get_dir("uploaded")
        assert (local / "data.txt").read_text() == "hello"

    def test_rename_dir(self, tmp_path):
        (tmp_path / "old").mkdir()
        store = StorePointer.parse(f"file://{tmp_path}")
        store.rename_dir("old", "new")
        assert not (tmp_path / "old").exists()
        assert (tmp_path / "new").is_dir()

    def test_delete_dir(self, tmp_path):
        (tmp_path / "target").mkdir()
        store = StorePointer.parse(f"file://{tmp_path}")
        store.delete_dir("target")
        assert not (tmp_path / "target").exists()

    def test_delete_dir_noop_when_missing(self, tmp_path):
        store = StorePointer.parse(f"file://{tmp_path}")
        store.delete_dir("nonexistent")  # should not raise
