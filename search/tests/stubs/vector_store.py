"""Stub vector store for search tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from common.stores.base import VectorStore


class StubVectorStore(VectorStore):
    def __init__(self, results: list[dict[str, Any]] | None = None) -> None:
        self._results: list[dict[str, Any]] = results or []
        self.loaded = False

    def load(self, local_path: Path) -> None:
        self.loaded = True

    def create_empty(self) -> None:
        pass

    def add(self, id: str, vector: list[float], metadata: dict[str, str]) -> None:
        pass

    def query(self, vector: list[float], n_results: int = 5) -> list[dict[str, Any]]:
        return self._results[:n_results]

    def save(self, local_path: Path) -> None:
        pass

    def created_at(self, local_path: Path) -> datetime | None:
        return None

    def load_for_update(self, local_path: Path) -> None:
        pass

    def upsert(self, id: str, vector: list[float], metadata: dict[str, str]) -> None:
        pass

    def get_metadata(self, id: str) -> dict[str, str] | None:
        return None

    def checkpoint(self, local_path: Path) -> None:
        pass
