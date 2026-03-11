"""Canonical plugin registries — shared between indexer and search.

Both packages import from here so the short-name → class mapping has a single
source of truth.
"""

from __future__ import annotations

from typing import Any

from common.stores.chroma import ChromaVectorStore
from common.vectorizers.sentence_transformer import SentenceTransformerVectorizer

VECTORIZERS: dict[str, type[Any]] = {
    "sentence-transformer": SentenceTransformerVectorizer,
}

VECTOR_STORES: dict[str, type[Any]] = {
    "chroma": ChromaVectorStore,
}
