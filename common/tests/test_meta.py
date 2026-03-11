"""Tests for IndexMeta."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from common.meta import INDEX_META_FILE, IndexMeta


class TestIndexMetaNow:
    def test_now_sets_current_utc_time(self) -> None:
        before = datetime.now(UTC)
        meta = IndexMeta.now(source="file:///foo", vectorizer="sv", vector_store="chroma")
        after = datetime.now(UTC)
        assert before <= meta.indexed_at <= after

    def test_now_stores_fields(self) -> None:
        meta = IndexMeta.now(source="file:///bar", vectorizer="st", vector_store="chroma")
        assert meta.source == "file:///bar"
        assert meta.vectorizer == "st"
        assert meta.vector_store == "chroma"


class TestIndexMetaSave:
    def test_save_creates_json_file(self, tmp_path: Path) -> None:
        meta = IndexMeta.now(source="file:///x", vectorizer="v", vector_store="s")
        path = tmp_path / INDEX_META_FILE
        meta.save(path)
        assert path.exists()

    def test_save_json_contains_all_fields(self, tmp_path: Path) -> None:
        meta = IndexMeta.now(source="file:///x", vectorizer="v", vector_store="s")
        path = tmp_path / INDEX_META_FILE
        meta.save(path)
        data = json.loads(path.read_text())
        assert "indexed_at" in data
        assert data["source"] == "file:///x"
        assert data["vectorizer"] == "v"
        assert data["vector_store"] == "s"

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        meta = IndexMeta.now(source="file:///x", vectorizer="v", vector_store="s")
        path = tmp_path / "nested" / "dir" / INDEX_META_FILE
        meta.save(path)
        assert path.exists()


class TestIndexMetaLoad:
    def test_roundtrip(self, tmp_path: Path) -> None:
        meta = IndexMeta.now(source="file:///roundtrip", vectorizer="vv", vector_store="cc")
        path = tmp_path / INDEX_META_FILE
        meta.save(path)
        loaded = IndexMeta.load(path)
        assert loaded.source == meta.source
        assert loaded.vectorizer == meta.vectorizer
        assert loaded.vector_store == meta.vector_store
        assert loaded.indexed_at == meta.indexed_at

    def test_load_raises_on_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            IndexMeta.load(tmp_path / "nonexistent.json")

    def test_load_raises_value_error_on_missing_field(self, tmp_path: Path) -> None:
        path = tmp_path / INDEX_META_FILE
        # Missing 'vectorizer' field
        path.write_text(
            json.dumps(
                {
                    "indexed_at": datetime.now(UTC).isoformat(),
                    "source": "x",
                    "vector_store": "c",
                }
            )
        )
        with pytest.raises(ValueError, match="Cannot parse field"):
            IndexMeta.load(path)

    def test_load_raises_value_error_on_bad_json(self, tmp_path: Path) -> None:
        path = tmp_path / INDEX_META_FILE
        path.write_text("not valid json {{{")
        with pytest.raises(ValueError, match="Malformed JSON"):
            IndexMeta.load(path)

    def test_load_raises_value_error_on_bad_datetime(self, tmp_path: Path) -> None:
        path = tmp_path / INDEX_META_FILE
        path.write_text(
            json.dumps(
                {
                    "indexed_at": "not-a-date",
                    "source": "x",
                    "vectorizer": "v",
                    "vector_store": "c",
                }
            )
        )
        with pytest.raises(ValueError):
            IndexMeta.load(path)
