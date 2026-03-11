"""Tests for StorePointer (file:// scheme — no rclone in tests)."""

from __future__ import annotations

import pytest

from common.pointer import StorePointer


class TestParse:
    def test_file_scheme_absolute_path(self) -> None:
        sp = StorePointer.parse("file:///data/store")
        assert sp.scheme == "file"
        assert sp.path == "/data/store"
        assert sp.remote is None

    def test_file_scheme_uri_roundtrip(self) -> None:
        uri = "file:///data/store"
        assert StorePointer.parse(uri).uri == uri

    def test_rclone_scheme_parsed(self) -> None:
        sp = StorePointer.parse("rclone:mybucket:///some/path")
        assert sp.scheme == "rclone"
        assert sp.remote == "mybucket"
        assert sp.path == "some/path"

    def test_rclone_strips_leading_slashes(self) -> None:
        sp = StorePointer.parse("rclone:r:///a/b")
        assert sp.path == "a/b"

    def test_file_relative_path_raises(self) -> None:
        with pytest.raises(ValueError, match="absolute path"):
            StorePointer.parse("file://relative/path")

    def test_unknown_scheme_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported URI scheme"):
            StorePointer.parse("s3://bucket/path")

    def test_rclone_missing_path_separator_raises(self) -> None:
        with pytest.raises(ValueError, match="missing path separator"):
            StorePointer.parse("rclone:nocodon")

    def test_rclone_invalid_remote_name_raises(self) -> None:
        with pytest.raises(ValueError, match="remote name"):
            StorePointer.parse("rclone:bad remote!:///path")


class TestFileSchemeDirOps:
    def test_put_dir_copies_directory(self, tmp_path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.txt").write_text("hello")
        store_root = tmp_path / "store"
        store_root.mkdir()

        sp = StorePointer(scheme="file", remote=None, path=str(store_root))
        sp.put_dir(src, dest_name="mydir")

        assert (store_root / "mydir").is_dir()
        assert (store_root / "mydir" / "file.txt").read_text() == "hello"

    def test_put_dir_overwrites_existing(self, tmp_path) -> None:
        store_root = tmp_path / "store"
        store_root.mkdir()
        existing = store_root / "mydir"
        existing.mkdir()
        (existing / "old.txt").write_text("old")

        src = tmp_path / "src"
        src.mkdir()
        (src / "new.txt").write_text("new")

        sp = StorePointer(scheme="file", remote=None, path=str(store_root))
        sp.put_dir(src, dest_name="mydir")

        assert not (store_root / "mydir" / "old.txt").exists()
        assert (store_root / "mydir" / "new.txt").read_text() == "new"

    def test_get_dir_returns_path(self, tmp_path) -> None:
        store_root = tmp_path / "store"
        store_root.mkdir()
        (store_root / "db").mkdir()

        sp = StorePointer(scheme="file", remote=None, path=str(store_root))
        result = sp.get_dir("db")
        assert result == store_root / "db"

    def test_get_dir_ctx_yields_path(self, tmp_path) -> None:
        store_root = tmp_path / "store"
        store_root.mkdir()
        (store_root / "db").mkdir()

        sp = StorePointer(scheme="file", remote=None, path=str(store_root))
        with sp.get_dir_ctx("db") as p:
            assert p == store_root / "db"

    def test_has_dir_true(self, tmp_path) -> None:
        store_root = tmp_path / "store"
        store_root.mkdir()
        (store_root / "db").mkdir()

        sp = StorePointer(scheme="file", remote=None, path=str(store_root))
        assert sp.has_dir("db") is True

    def test_has_dir_false(self, tmp_path) -> None:
        store_root = tmp_path / "store"
        store_root.mkdir()

        sp = StorePointer(scheme="file", remote=None, path=str(store_root))
        assert sp.has_dir("missing") is False

    def test_rename_dir(self, tmp_path) -> None:
        store_root = tmp_path / "store"
        store_root.mkdir()
        (store_root / "old").mkdir()

        sp = StorePointer(scheme="file", remote=None, path=str(store_root))
        sp.rename_dir("old", "new")

        assert not (store_root / "old").exists()
        assert (store_root / "new").is_dir()

    def test_delete_dir(self, tmp_path) -> None:
        store_root = tmp_path / "store"
        store_root.mkdir()
        (store_root / "target").mkdir()

        sp = StorePointer(scheme="file", remote=None, path=str(store_root))
        sp.delete_dir("target")

        assert not (store_root / "target").exists()

    def test_delete_dir_nonexistent_is_noop(self, tmp_path) -> None:
        store_root = tmp_path / "store"
        store_root.mkdir()

        sp = StorePointer(scheme="file", remote=None, path=str(store_root))
        # Should not raise
        sp.delete_dir("nonexistent")


class TestGetFileCtxFileScheme:
    def test_yields_correct_path(self, tmp_path) -> None:
        root = tmp_path / "media"
        root.mkdir()
        (root / "photo.jpg").write_bytes(b"\xff\xd8\xff")

        sp = StorePointer(scheme="file", remote=None, path=str(root))
        with sp.get_file_ctx("photo.jpg") as p:
            assert p == root / "photo.jpg"
            assert p.read_bytes() == b"\xff\xd8\xff"

    def test_yields_nested_path(self, tmp_path) -> None:
        root = tmp_path / "media"
        sub = root / "2024"
        sub.mkdir(parents=True)
        (sub / "img.png").write_bytes(b"PNG")

        sp = StorePointer(scheme="file", remote=None, path=str(root))
        with sp.get_file_ctx("2024/img.png") as p:
            assert p == root / "2024" / "img.png"
            assert p.read_bytes() == b"PNG"

    def test_no_cleanup_of_file_on_exit(self, tmp_path) -> None:
        root = tmp_path / "media"
        root.mkdir()
        f = root / "keep.jpg"
        f.write_bytes(b"data")

        sp = StorePointer(scheme="file", remote=None, path=str(root))
        with sp.get_file_ctx("keep.jpg"):
            pass
        # file:// source — original file must still exist after the context exits
        assert f.exists()
