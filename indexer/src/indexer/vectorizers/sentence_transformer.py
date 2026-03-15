"""SentenceTransformer vectorizer."""

from __future__ import annotations

from typing import Any

from indexer.vectorizers.base import Vectorizer


class SentenceTransformerVectorizer(Vectorizer):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model: Any = None

    def _load(self) -> None:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)

    def vectorize(self, text: str) -> list[float]:
        self._load()
        result: list[float] = self._model.encode(text, convert_to_numpy=True).tolist()
        return result

    def vectorize_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed all texts in a single encode() call."""
        self._load()
        result: list[list[float]] = self._model.encode(
            texts, convert_to_numpy=True, batch_size=len(texts)
        ).tolist()
        return result

    @property
    def dimension(self) -> int:
        self._load()
        dim: int = int(self._model.get_sentence_embedding_dimension())
        return dim
