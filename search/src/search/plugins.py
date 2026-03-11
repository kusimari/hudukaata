"""Plugin registry — resolve vectorizer and vector-store names to instances."""

from __future__ import annotations

from common.plugins import resolve_instance
from common.registry import VECTOR_STORES, VECTORIZERS
from common.stores.base import VectorStore
from common.vectorizers.base import Vectorizer


def resolve_vectorizer(name: str) -> Vectorizer:
    """Return a :class:`~common.vectorizers.base.Vectorizer` instance for *name*."""
    result: Vectorizer = resolve_instance(name, VECTORIZERS, "vectorizer", Vectorizer)
    return result


def resolve_vector_store(name: str) -> VectorStore:
    """Return a :class:`~common.stores.base.VectorStore` instance for *name*."""
    result: VectorStore = resolve_instance(name, VECTOR_STORES, "vector-store", VectorStore)
    return result
