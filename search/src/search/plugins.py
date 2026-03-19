"""Plugin registry — resolve index-store names to instances."""

from __future__ import annotations

from typing import Any

from common.base import resolve_instance
from common.index import IndexStore


def resolve_index_store(name: str) -> IndexStore[Any]:
    """Return an :class:`~common.index.IndexStore` instance for *name*.

    *name* may be a short registry key or a dotted import path such as
    ``"indexer.stores.chroma_caption.ChromaCaptionIndexStore"``.
    """
    result: IndexStore[Any] = resolve_instance(name, {}, "index-store", IndexStore)
    return result
