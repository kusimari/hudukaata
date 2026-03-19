"""Tests for IndexResult, CaptionItem, FaceItem, and IndexStore interface."""

from __future__ import annotations

from common.index import CaptionItem, FaceItem, IndexResult


class TestCaptionItem:
    def test_text_field(self) -> None:
        item = CaptionItem(text="a sunset")
        assert item.text == "a sunset"


class TestFaceItem:
    def test_fields(self) -> None:
        item = FaceItem(embedding=[0.1, 0.2, 0.3], cluster_id="cluster-1")
        assert item.embedding == [0.1, 0.2, 0.3]
        assert item.cluster_id == "cluster-1"


class TestIndexResult:
    def test_basic_fields_with_caption_item(self) -> None:
        r: IndexResult[CaptionItem] = IndexResult(
            id="1",
            relative_path="photo.jpg",
            item=CaptionItem(text="a sunset"),
            score=0.9,
        )
        assert r.id == "1"
        assert r.relative_path == "photo.jpg"
        assert r.item.text == "a sunset"
        assert r.score == 0.9

    def test_basic_fields_with_face_item(self) -> None:
        r: IndexResult[FaceItem] = IndexResult(
            id="c1",
            relative_path="photo.jpg",
            item=FaceItem(embedding=[0.1, 0.2], cluster_id="c1"),
            score=0.8,
        )
        assert r.item.cluster_id == "c1"
        assert r.item.embedding == [0.1, 0.2]

    def test_extra_defaults_to_empty_dict(self) -> None:
        r: IndexResult[CaptionItem] = IndexResult(
            id="1",
            relative_path="photo.jpg",
            item=CaptionItem(text="caption"),
            score=0.5,
        )
        assert r.extra == {}

    def test_extra_can_be_set(self) -> None:
        r: IndexResult[CaptionItem] = IndexResult(
            id="1",
            relative_path="photo.jpg",
            item=CaptionItem(text="caption"),
            score=0.5,
            extra={"key": "value"},
        )
        assert r.extra == {"key": "value"}
