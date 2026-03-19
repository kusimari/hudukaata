"""Stub IndexStore for search tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from common.index import CaptionItem, IndexResult, IndexStore


class StubIndexStore(IndexStore[CaptionItem]):
    def __init__(self, results: list[dict[str, str]] | None = None) -> None:
        self._raw: list[dict[str, str]] = results or []
        self.loaded = False

    def search(self, query: CaptionItem, top_k: int) -> list[IndexResult[CaptionItem]]:
        out = []
        for raw in self._raw[:top_k]:
            known = {"id", "caption", "relative_path"}
            extra = {k: str(v) for k, v in raw.items() if k not in known}
            out.append(
                IndexResult(
                    id=str(raw.get("id", "")),
                    relative_path=str(raw.get("relative_path", "")),
                    item=CaptionItem(text=str(raw.get("caption", ""))),
                    score=1.0,
                    extra=extra,
                )
            )
        return out

    def get_metadata(self, id: str) -> dict[str, str] | None:
        return None

    def add(self, id: str, item: CaptionItem, metadata: dict[str, str]) -> None:
        pass

    def upsert(self, id: str, item: CaptionItem, metadata: dict[str, str]) -> None:
        pass

    def load(self, local_path: Path) -> None:
        self.loaded = True

    def create_empty(self) -> None:
        pass

    def save(self, local_path: Path) -> None:
        pass

    def created_at(self, local_path: Path) -> datetime | None:
        return None

    def load_for_update(self, local_path: Path) -> None:
        pass

    def checkpoint(self, local_path: Path) -> None:
        pass
