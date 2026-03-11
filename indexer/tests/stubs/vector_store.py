"""Stub vector store — in-memory dict."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from common.stores.base import VectorStore


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

    def query(
        self,
        vector: list[float],
        n_results: int = 5,
    ) -> list[dict[str, object]]:
        # Return up to n_results docs (no actual similarity ranking in stub).
        results = []
        for id_, (_vec, meta) in list(self.docs.items())[:n_results]:
            results.append({"id": id_, **meta})
        return results

    def save(self, local_path: Path) -> None:
        local_path.mkdir(parents=True, exist_ok=True)

    def created_at(self, local_path: Path) -> datetime | None:
        return None
