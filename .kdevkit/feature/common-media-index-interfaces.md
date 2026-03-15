# Feature: common-media-index-interfaces

## Goal

Refactor `common` to a flat three-file structure that owns two clean
domain-level interfaces **and** their default implementations. External
consumers import only the interfaces; concrete classes are accessible via their
module but not advertised in `__init__.py`.

The **linkage contract**: `IndexResult.relative_path` == `MediaFile.relative_path`
— every value stored in the index can be fetched from the media source without
any path translation.

---

## common package layout after refactor

```
common/src/common/
├── __init__.py       # re-exports interfaces only: MediaSource, MediaFile,
│                     #   IndexStore, IndexResult, StorePointer, IndexMeta
├── base.py           # StorePointer, IndexMeta, resolve_instance()
├── media.py          # MediaFile, MediaSource (ABC)
│                     #   + FileMediaSource, RcloneMediaSource, GdriveMediaSource
└── index.py          # IndexResult, IndexStore (ABC)
│                     #   + ChromaCaptionIndexStore (Chroma + SentenceTransformer)
```

Everything else — `meta.py`, `pointer.py`, `plugins.py`, `registry.py`,
`stores/`, `vectorizers/` — is **deleted and consolidated** into the three files
above.

---

## File responsibilities

### `base.py`

Consolidates `pointer.py` + `meta.py` + `plugins.py`. Deletes `registry.py`
(no shared registry needed once implementations live here).

Public names: `StorePointer`, `IndexMeta`, `INDEX_META_FILE`, `INDEXER_VERSION`.
Internal: `resolve_instance()` (used by search to load IndexStore by dotted path).

### `media.py`

Public interface: `MediaFile`, `MediaSource` (ABC with `uri`, `scan()`, `getmedia()`,
`from_uri()` factory).

Implementations (accessible from `common.media`, not re-exported from `__init__`):
`FileMediaSource`, `RcloneMediaSource`, `GdriveMediaSource`.

Internal helpers: `_rclone_run()`, `_rclone_lsjson()`, `_LocalFile`, `_RcloneFile`,
`_RcloneGetFile`, extension sets, `_EXT_TO_TYPE`.

### `index.py`

Public interface: `IndexResult` (dataclass), `IndexStore` (ABC).

Implementation (accessible from `common.index`, not re-exported from `__init__`):
`ChromaCaptionIndexStore` — embeds SentenceTransformer vectorization + ChromaDB
storage. Callers pass and receive **plain text only**; no vectors exposed.

Internal: `Vectorizer` ABC, `SentenceTransformerVectorizer` (private, used only
by `ChromaCaptionIndexStore`).

---

## Interface signatures

### `media.py` — public surface

```python
class MediaFile:
    relative_path: str                           # stable ID = IndexResult.relative_path
    media_type: Literal["image", "video", "audio"]
    mtime: float | None
    # context manager: __enter__ → Path, __exit__ → cleanup

class MediaSource(ABC):
    @property
    @abstractmethod
    def uri(self) -> str: ...

    @abstractmethod
    def scan(self, subfolder: str | None = None) -> Iterator[MediaFile]: ...

    @abstractmethod
    def getmedia(self, relative_path: str) -> MediaFile:
        """No scanning; use as context manager to get a local Path."""

    @classmethod
    def from_uri(cls, uri: str) -> "MediaSource":
        """file:// → FileMediaSource  |  rclone: → RcloneMediaSource  |
           gdrive:// → GdriveMediaSource"""
```

### `index.py` — public surface

```python
@dataclass
class IndexResult:
    id: str
    relative_path: str   # pass directly to MediaSource.getmedia()
    caption: str
    score: float         # [0, 1]; implementation-defined
    extra: dict[str, Any]

class IndexStore(ABC):
    # read
    @abstractmethod
    def search(self, query: str, top_k: int) -> list[IndexResult]: ...
    @abstractmethod
    def get_metadata(self, id: str) -> dict[str, str] | None: ...

    # write (text in — no vectors)
    @abstractmethod
    def add(self, id: str, text: str, metadata: dict[str, str]) -> None: ...
    @abstractmethod
    def upsert(self, id: str, text: str, metadata: dict[str, str]) -> None: ...

    # lifecycle
    @abstractmethod
    def load(self, local_path: Path) -> None: ...
    @abstractmethod
    def create_empty(self) -> None: ...
    @abstractmethod
    def save(self, local_path: Path) -> None: ...
    @abstractmethod
    def created_at(self, local_path: Path) -> datetime | None: ...
    @abstractmethod
    def load_for_update(self, local_path: Path) -> None: ...
    @abstractmethod
    def checkpoint(self, local_path: Path) -> None: ...
```

### `ChromaCaptionIndexStore` (in `index.py`, not exported from `__init__`)

```python
class ChromaCaptionIndexStore(IndexStore):
    def __init__(self, vectorizer: _Vectorizer | None = None) -> None: ...
    # search(query: str) → vectorizes internally, queries Chroma, returns IndexResult list
    # upsert/add(id, text, metadata) → vectorizes internally, stores in Chroma
    # lifecycle: load / create_empty / save / created_at / load_for_update / checkpoint
    #            (all logic moved verbatim from ChromaVectorStore)
    # score = max(0.0, 1.0 - distance)
```

### `base.py` — `IndexMeta` changes

```python
INDEXER_VERSION = "2.0.0"   # bumped — forces reindex of v1 DBs

@dataclass
class IndexMeta:
    indexed_at: datetime
    source: str
    index_store: str        # dotted class path written by indexer, read by search
    indexer_version: str = ""
    # vectorizer / vector_store fields removed
```

`load()` raises `ValueError` with a clear re-run message if `index_store` is
absent but old `vectorizer`/`vector_store` fields are present.

---

## Changes to indexer

| File | Action |
|------|--------|
| `pointer.py` | Thin shim: re-export `MediaSource`, `MediaFile`, `FileMediaSource`, `RcloneMediaSource`, `GdriveMediaSource` from `common.media`; keep `MediaPointer` factory |
| `runner.py` | Single `index_store: IndexStore` param replaces `vectorizer + vector_store`; `index_store.upsert(id, text, meta)` replaces separate vectorize + store calls |
| `cli.py` | `--index-store` (default `"common.index.ChromaCaptionIndexStore"`) replaces `--vectorizer` + `--vector-store` |
| `tests/stubs/index_store.py` | **Create** `StubIndexStore(IndexStore)` with no-op write + stub `search()` |
| `tests/stubs/vector_store.py` | **Delete** |
| `tests/stubs/vectorizer.py` | **Delete** |
| `tests/test_runner.py` | `StubIndexStore` replaces separate vectorizer/vector_store stubs |
| `tests/test_runner_update.py` | same |

## Changes to search

| File | Action |
|------|--------|
| `startup.py` | `AppState`: `index_store: IndexStore` + `media_src: MediaSource`; load via `resolve_instance(meta.index_store, ...)` |
| `app.py` | `index_store.search(q, top_k)` + `media_src.getmedia(path)` |
| `plugins.py` | `resolve_index_store(name)` — empty registry, dotted path only |
| `config.py` | Split validator: `store` → `StorePointer.parse()`, `media` → `MediaSource.from_uri()` |
| `tests/stubs/vector_store.py` | **Delete** |
| `tests/stubs/index_store.py` | **Create** `StubIndexStore(IndexStore)` |
| `tests/conftest.py` | Update `AppState` fixture fields |
| `tests/test_startup.py` | `index_store` field in meta |
| `tests/test_search_route.py` | updated `AppState` field names |

---

## common `__init__.py` public surface

```python
from common.base import IndexMeta, StorePointer
from common.media import MediaFile, MediaSource
from common.index import IndexResult, IndexStore
```

Concrete classes (`FileMediaSource`, `ChromaCaptionIndexStore`, etc.) are
importable from their modules but not listed here.

---

## Task breakdown

### Phase A — common
1. Write `common/src/common/base.py` (StorePointer + IndexMeta + resolve_instance)
2. Write `common/src/common/media.py` (MediaFile + MediaSource + 3 implementations)
3. Write `common/src/common/index.py` (IndexResult + IndexStore + ChromaCaptionIndexStore)
4. Write new `common/src/common/__init__.py` (interface-only exports)
5. Delete: `pointer.py`, `meta.py`, `plugins.py`, `registry.py`, `stores/`, `vectorizers/`
6. Update `common/tests/`: delete `test_chroma_store.py`, update `test_meta.py` →
   `test_base.py`, update `test_pointer.py` → `test_base.py`, create `test_media.py`,
   create `test_index.py`
7. Run common dev loop

### Phase B — indexer
8. Thin `indexer/pointer.py` to re-exports from `common.media`
9. Update `indexer/runner.py` — `IndexStore` replaces `Vectorizer + VectorStore`
10. Update `indexer/cli.py` — `--index-store` option
11. Create `indexer/tests/stubs/index_store.py`; delete `vector_store.py`, `vectorizer.py`
12. Update `indexer/tests/test_runner.py`, `test_runner_update.py`
13. Run indexer dev loop

### Phase C — search
14. Update `search/startup.py` (new `AppState` fields)
15. Update `search/app.py` (`search()` + `getmedia()`)
16. Update `search/plugins.py` (`resolve_index_store`)
17. Update `search/config.py` (split validator)
18. Create `search/tests/stubs/index_store.py`; delete `vector_store.py`
19. Update `search/tests/conftest.py`, `test_startup.py`, `test_search_route.py`
20. Run search dev loop

### Phase D — push
21. Commit (one commit per phase or combined)
22. Push to `claude/media-pointer-navigation-SXQPT`

---

## Status
- [ ] Phase A: common
- [ ] Phase B: indexer
- [ ] Phase C: search
- [ ] Phase D: push
