"""SentenceTransformer vectorizer (default implementation)."""

from __future__ import annotations

from indexer.vectorizers.base import Vectorizer


class SentenceTransformerVectorizer(Vectorizer):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)

    def vectorize(self, text: str) -> list[float]:
        self._load()
        embedding = self._model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    @property
    def dimension(self) -> int:
        self._load()
        return self._model.get_sentence_embedding_dimension()


def format_text(caption: str, exif: dict[str, str]) -> str:
    """Build the combined text fed to the vectorizer."""
    lines = [caption, "", "EXIF:"]
    lines.extend(f"{k}: {v}" for k, v in sorted(exif.items()))
    return "\n".join(lines)
