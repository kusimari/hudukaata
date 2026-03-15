"""Stub IndexStore — in-memory dict, no vectorization."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from common.index import IndexResult, IndexStore


class StubIndexStore(IndexStore):
    def __init__(self) -> None:
        self.docs: dict[str, tuple[str, dict[str, str]]] = {}
        self._empty = False

    def search(self, query: str, top_k: int) -> list[IndexResult]:
        results = []
        for id_, (text, meta) in list(self.docs.items())[:top_k]:
            results.append(
                IndexResult(
                    id=id_,
                    relative_path=meta.get("relative_path", id_),
                    caption=meta.get("caption", text),
                    score=1.0,
                )
            )
        return results

    def get_metadata(self, id: str) -> dict[str, str] | None:
        entry = self.docs.get(id)
        return entry[1] if entry is not None else None

    def add(self, id: str, text: str, metadata: dict[str, str]) -> None:
        self.docs[id] = (text, metadata)

    def upsert(self, id: str, text: str, metadata: dict[str, str]) -> None:
        self.docs[id] = (text, metadata)

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
