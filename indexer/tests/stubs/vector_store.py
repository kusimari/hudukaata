"""Stub vector store — in-memory dict."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from indexer.stores.base import VectorStore


class StubVectorStore(VectorStore):
    def __init__(self) -> None:
        self.docs: dict[str, tuple[list[float], dict[str, str]]] = {}
        self._loaded = False
        self._empty = False

    def load(self, local_path: Path) -> None:
        self._loaded = True

    def create_empty(self) -> None:
        self.docs = {}
        self._empty = True

    def add(
        self,
        id: str,
        vector: list[float],
        metadata: dict[str, str],
    ) -> None:
        self.docs[id] = (vector, metadata)

    def save(self, local_path: Path) -> None:
        local_path.mkdir(parents=True, exist_ok=True)

    def created_at(self, local_path: Path) -> datetime | None:
        return None
