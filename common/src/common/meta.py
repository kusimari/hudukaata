"""IndexMeta — typed representation of index_meta.json stored alongside the vector DB."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

INDEX_META_FILE = "index_meta.json"
"""Filename of the index metadata sidecar written inside the DB directory."""

INDEXER_VERSION = "1.0.0"
"""Current indexer implementation version.

Bump this constant whenever the captioning or vectorisation pipeline changes
in a way that requires all existing documents to be re-indexed.  The indexer
compares this value against the version stored in the existing DB's
``index_meta.json``; if they differ it forces a full rebuild.
"""


@dataclass
class IndexMeta:
    """Metadata written by the indexer and read by the search server.

    Stored as JSON at ``<db_dir>/index_meta.json``.
    """

    indexed_at: datetime
    source: str
    vectorizer: str
    vector_store: str
    indexer_version: str = ""

    @staticmethod
    def load(path: Path) -> IndexMeta:
        """Load from a JSON file.

        Raises:
            FileNotFoundError: if the file does not exist.
            ValueError: if the file contains invalid JSON or is missing required fields.
        """
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON in {path}: {exc}") from exc
        try:
            return IndexMeta(
                indexed_at=datetime.fromisoformat(data["indexed_at"]),
                source=data["source"],
                vectorizer=data["vectorizer"],
                vector_store=data["vector_store"],
                indexer_version=data.get("indexer_version", ""),
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Cannot parse field {exc} in {path}") from exc

    def save(self, path: Path) -> None:
        """Write to a JSON file, creating parent directories as needed."""
        path.parent.mkdir(parents=True, exist_ok=True)
        out = asdict(self)
        out["indexed_at"] = self.indexed_at.isoformat()
        path.write_text(json.dumps(out, indent=2))

    @staticmethod
    def now(
        source: str,
        vectorizer: str,
        vector_store: str,
        indexer_version: str = INDEXER_VERSION,
    ) -> IndexMeta:
        """Construct an ``IndexMeta`` stamped with the current UTC time."""
        return IndexMeta(
            indexed_at=datetime.now(UTC),
            source=source,
            vectorizer=vectorizer,
            vector_store=vector_store,
            indexer_version=indexer_version,
        )
