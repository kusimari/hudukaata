"""Tests for IndexMeta."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from common.base import INDEX_META_FILE, INDEXER_VERSION, IndexMeta


class TestIndexMetaNow:
    def test_now_sets_current_utc_time(self) -> None:
        before = datetime.now(UTC)
        meta = IndexMeta.now(
            source="file:///foo",
            index_store="indexer.stores.chroma_caption.ChromaCaptionIndexStore",
        )
        after = datetime.now(UTC)
        assert before <= meta.indexed_at <= after

    def test_now_stores_fields(self) -> None:
        meta = IndexMeta.now(
            source="file:///bar",
            index_store="indexer.stores.chroma_caption.ChromaCaptionIndexStore",
        )
        assert meta.source == "file:///bar"
        assert meta.index_store == "indexer.stores.chroma_caption.ChromaCaptionIndexStore"


class TestIndexMetaSave:
    def test_save_creates_json_file(self, tmp_path: Path) -> None:
        meta = IndexMeta.now(
            source="file:///x", index_store="indexer.stores.chroma_caption.ChromaCaptionIndexStore"
        )
        path = tmp_path / INDEX_META_FILE
        meta.save(path)
        assert path.exists()

    def test_save_json_contains_all_fields(self, tmp_path: Path) -> None:
        meta = IndexMeta.now(
            source="file:///x", index_store="indexer.stores.chroma_caption.ChromaCaptionIndexStore"
        )
        path = tmp_path / INDEX_META_FILE
        meta.save(path)
        data = json.loads(path.read_text())
        assert "indexed_at" in data
        assert data["source"] == "file:///x"
        assert data["index_store"] == "indexer.stores.chroma_caption.ChromaCaptionIndexStore"

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        meta = IndexMeta.now(
            source="file:///x", index_store="indexer.stores.chroma_caption.ChromaCaptionIndexStore"
        )
        path = tmp_path / "nested" / "dir" / INDEX_META_FILE
        meta.save(path)
        assert path.exists()


class TestIndexerVersion:
    def test_now_includes_indexer_version(self) -> None:
        meta = IndexMeta.now(
            source="file:///x", index_store="indexer.stores.chroma_caption.ChromaCaptionIndexStore"
        )
        assert meta.indexer_version == INDEXER_VERSION

    def test_now_accepts_custom_version(self) -> None:
        meta = IndexMeta.now(
            source="file:///x",
            index_store="indexer.stores.chroma_caption.ChromaCaptionIndexStore",
            indexer_version="2.0.0",
        )
        assert meta.indexer_version == "2.0.0"

    def test_save_load_roundtrip_with_version(self, tmp_path: Path) -> None:
        meta = IndexMeta.now(
            source="file:///x", index_store="indexer.stores.chroma_caption.ChromaCaptionIndexStore"
        )
        path = tmp_path / INDEX_META_FILE
        meta.save(path)
        loaded = IndexMeta.load(path)
        assert loaded.indexer_version == INDEXER_VERSION

    def test_save_json_contains_indexer_version(self, tmp_path: Path) -> None:
        meta = IndexMeta.now(
            source="file:///x", index_store="indexer.stores.chroma_caption.ChromaCaptionIndexStore"
        )
        path = tmp_path / INDEX_META_FILE
        meta.save(path)
        data = json.loads(path.read_text())
        assert data["indexer_version"] == INDEXER_VERSION

    def test_load_old_meta_without_version_defaults_to_empty_string(self, tmp_path: Path) -> None:
        """New-format files without indexer_version load without error."""
        path = tmp_path / INDEX_META_FILE
        path.write_text(
            json.dumps(
                {
                    "indexed_at": datetime.now(UTC).isoformat(),
                    "source": "file:///x",
                    "index_store": "indexer.stores.chroma_caption.ChromaCaptionIndexStore",
                }
            )
        )
        loaded = IndexMeta.load(path)
        assert loaded.indexer_version == ""

    def test_load_old_format_raises_with_helpful_message(self, tmp_path: Path) -> None:
        """Files built before 2.0.0 (with vectorizer/vector_store) raise ValueError."""
        path = tmp_path / INDEX_META_FILE
        path.write_text(
            json.dumps(
                {
                    "indexed_at": datetime.now(UTC).isoformat(),
                    "source": "file:///x",
                    "vectorizer": "sentence-transformers",
                    "vector_store": "chroma",
                }
            )
        )
        with pytest.raises(ValueError, match="Re-run the indexer"):
            IndexMeta.load(path)


class TestIndexMetaLoad:
    def test_roundtrip(self, tmp_path: Path) -> None:
        meta = IndexMeta.now(
            source="file:///roundtrip",
            index_store="indexer.stores.chroma_caption.ChromaCaptionIndexStore",
        )
        path = tmp_path / INDEX_META_FILE
        meta.save(path)
        loaded = IndexMeta.load(path)
        assert loaded.source == meta.source
        assert loaded.index_store == meta.index_store
        assert loaded.indexed_at == meta.indexed_at

    def test_load_raises_on_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            IndexMeta.load(tmp_path / "nonexistent.json")

    def test_load_raises_value_error_on_missing_field(self, tmp_path: Path) -> None:
        path = tmp_path / INDEX_META_FILE
        # Missing 'index_store' field
        path.write_text(
            json.dumps(
                {
                    "indexed_at": datetime.now(UTC).isoformat(),
                    "source": "x",
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
                    "index_store": "indexer.stores.chroma_caption.ChromaCaptionIndexStore",
                }
            )
        )
        with pytest.raises(ValueError):
            IndexMeta.load(path)
