"""common — shared interfaces and utilities for hudukaata.

Public surface (interfaces only):

    from common import MediaSource, MediaFile      # media access
    from common import IndexStore, IndexResult     # index read/write
    from common import StorePointer, IndexMeta     # DB transport + metadata

Concrete implementations live in ``common.media`` (filesystem adapters) and
in the ``indexer`` package (index strategies).  Use :meth:`MediaSource.from_uri`
to construct a media source and ``common.base.resolve_instance`` to load an
IndexStore implementation by dotted class path.
"""

from common.base import IndexMeta, StorePointer
from common.index import CaptionItem, FaceItem, IndexResult, IndexStore
from common.media import MediaFile, MediaSource

__all__ = [
    "IndexMeta",
    "StorePointer",
    "CaptionItem",
    "FaceItem",
    "IndexResult",
    "IndexStore",
    "MediaFile",
    "MediaSource",
]
