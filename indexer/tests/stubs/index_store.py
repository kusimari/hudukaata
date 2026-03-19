"""Stub IndexStore[CaptionItem] — in-memory dict, no vectorization."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from common.index import CaptionItem, IndexResult, IndexStore


class StubIndexStore(IndexStore[CaptionItem]):
    def __init__(self) -> None:
        self.docs: dict[str, tuple[CaptionItem, dict[str, str]]] = {}
        self._empty = False

    def search(self, query: CaptionItem, top_k: int) -> list[IndexResult[CaptionItem]]:
        results = []
        for id_, (item, meta) in list(self.docs.items())[:top_k]:
            results.append(
                IndexResult(
                    id=id_,
                    relative_path=meta.get("relative_path", id_),
                    item=item,
                    score=1.0,
                )
            )
        return results

    def get_metadata(self, id: str) -> dict[str, str] | None:
        entry = self.docs.get(id)
        return entry[1] if entry is not None else None

    def add(self, id: str, item: CaptionItem, metadata: dict[str, str]) -> None:
        self.docs[id] = (item, metadata)

    def upsert(self, id: str, item: CaptionItem, metadata: dict[str, str]) -> None:
        self.docs[id] = (item, metadata)

    def load(self, local_path: Path) -> None:
        pass

    def create_empty(self) -> None:
        self.docs = {}
        self._empty = True

    def save(self, local_path: Path) -> None:
        local_path.mkdir(parents=True, exist_ok=True)

    def created_at(self, local_path: Path) -> datetime | None:
        return None

    def load_for_update(self, local_path: Path) -> None:
        pass

    def checkpoint(self, local_path: Path) -> None:
        local_path.mkdir(parents=True, exist_ok=True)
