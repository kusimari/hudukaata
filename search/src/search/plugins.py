"""Plugin registry — resolve vectorizer and vector-store names to instances."""

from __future__ import annotations

from typing import Any

from common.plugins import resolve_instance
from common.stores.base import VectorStore
from common.stores.chroma import ChromaVectorStore
from common.vectorizers.base import Vectorizer
from common.vectorizers.sentence_transformer import SentenceTransformerVectorizer

_VECTORIZERS: dict[str, type[Any]] = {
    "sentence-transformer": SentenceTransformerVectorizer,
}
_VECTOR_STORES: dict[str, type[Any]] = {
    "chroma": ChromaVectorStore,
}


def resolve_vectorizer(name: str) -> Vectorizer:
    """Return a :class:`~common.vectorizers.base.Vectorizer` instance for *name*."""
    result: Vectorizer = resolve_instance(name, _VECTORIZERS, "vectorizer", Vectorizer)
    return result


def resolve_vector_store(name: str) -> VectorStore:
    """Return a :class:`~common.stores.base.VectorStore` instance for *name*."""
    result: VectorStore = resolve_instance(name, _VECTOR_STORES, "vector-store", VectorStore)
    return result
