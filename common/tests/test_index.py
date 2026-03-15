"""Tests for IndexResult and IndexStore interface."""

from __future__ import annotations

from common.index import IndexResult


class TestIndexResult:
    def test_basic_fields(self) -> None:
        r = IndexResult(id="1", relative_path="photo.jpg", caption="a sunset", score=0.9)
        assert r.id == "1"
        assert r.relative_path == "photo.jpg"
        assert r.caption == "a sunset"
        assert r.score == 0.9

    def test_extra_defaults_to_empty_dict(self) -> None:
        r = IndexResult(id="1", relative_path="photo.jpg", caption="caption", score=0.5)
        assert r.extra == {}

    def test_extra_can_be_set(self) -> None:
        r = IndexResult(
            id="1",
            relative_path="photo.jpg",
            caption="caption",
            score=0.5,
            extra={"key": "value"},
        )
        assert r.extra == {"key": "value"}
