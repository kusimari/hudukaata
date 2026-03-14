# Feature: common-media-index-interfaces

## Goal

Refactor `common` to own two clean, domain-level abstractions:

1. **`MediaSource`** — scans and fetches individual media files from any backend
   (file, rclone, Google Drive).
2. **`IndexStore`** — reads and writes the semantic index; `search()` returns
   `IndexResult` objects whose `relative_path` can be passed directly to
   `MediaSource.getmedia()`.

The linkage contract: **`IndexResult.relative_path` == `MediaFile.relative_path`** —
every value stored in the index can be retrieved from the media source without any
path translation.

---

## Interface Design

### `common/src/common/media.py` (new file)

```python
# Extension sets + _EXT_TO_TYPE mapping (moved from indexer/pointer.py)
IMAGE_EXTENSIONS: set[str]
VIDEO_EXTENSIONS: set[str]
AUDIO_EXTENSIONS: set[str]
_EXT_TO_TYPE: dict[str, Literal["image", "video", "audio"]]

class MediaFile:
    """Context-manager wrapper around a single media file."""
    relative_path: str          # KEY — stable identifier across scan + getmedia
    media_type: Literal["image", "video", "audio"]
    mtime: float | None         # UTC seconds since epoch
    local_path: Path            # only valid inside `with mf:`
    # __enter__ / __exit__ download / cleanup as needed

class MediaSource(ABC):
    @property
    @abstractmethod
    def uri(self) -> str: ...

    @abstractmethod
    def scan(self, subfolder: str | None = None) -> Iterator[MediaFile]:
        """Yield every recognised media file.
        relative_path on each MediaFile is always relative to this source's
        root, even when subfolder is given."""

    @abstractmethod
    def getmedia(self, relative_path: str) -> MediaFile:
        """Return a MediaFile for a known relative_path (does not scan).
        Use as a context manager to access local_path."""

    @classmethod
    def from_uri(cls, uri: str) -> "MediaSource":
        """Factory: file:// → FileMediaSource, rclone: → RcloneMediaSource,
        gdrive:// → GdriveMediaSource."""

# Implementations
class FileMediaSource(MediaSource): ...   # local filesystem
class RcloneMediaSource(MediaSource): ... # rclone remote
class GdriveMediaSource(MediaSource): ... # Google Drive / Colab
```

Internal helpers (moved from indexer/pointer.py):
- `_LocalFile`, `_RcloneFile` (shared-tmpdir, per-scan), `_RcloneGetFile` (own-tmpdir, per-getmedia)
- module-level `_rclone_run()`, `_rclone_lsjson()`

### `common/src/common/stores/base.py` (replace VectorStore with IndexStore)

```python
@dataclass
class IndexResult:
    id: str
    relative_path: str   # KEY — pass directly to MediaSource.getmedia()
    caption: str
    score: float
    extra: dict[str, Any]

class IndexStore(ABC):
    # --- read ---
    @abstractmethod
    def search(self, query_vector: list[float], top_k: int) -> list[IndexResult]: ...

    @abstractmethod
    def get_metadata(self, id: str) -> dict[str, str] | None: ...

    # --- write ---
    @abstractmethod
    def add(self, id: str, vector: list[float], metadata: dict[str, str]) -> None: ...

    @abstractmethod
    def upsert(self, id: str, vector: list[float], metadata: dict[str, str]) -> None: ...

    # --- lifecycle ---
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

### `common/src/common/stores/chroma.py` (ChromaVectorStore → ChromaIndexStore)

- Rename class to `ChromaIndexStore(IndexStore)`.
- Replace `query()` → `search()`: extract `relative_path` from stored metadata,
  populate `IndexResult` objects (id, relative_path, caption, score, extra).
- Score = 1.0 − distance (Chroma returns L2 distances; clamp to [0, 1]).

### `common/src/common/registry.py`

```python
# rename VECTOR_STORES → INDEX_STORES
INDEX_STORES: dict[str, type[Any]] = {"chroma": ChromaIndexStore}

# add (for future MediaSource plugin resolution)
MEDIA_SOURCES: dict[str, type[Any]] = {
    "file": FileMediaSource,
    "rclone": RcloneMediaSource,
    "gdrive": GdriveMediaSource,
}
```

---

## Analysis: Changes to indexer

| File | Change |
|------|--------|
| `indexer/pointer.py` | Replace body with re-exports from `common.media`. Keep `MediaPointer.parse()` as a shim delegating to `MediaSource.from_uri()`. Remove now-redundant local `_rclone_run`, `_rclone_lsjson`, `_LocalFile`, `_RcloneFile`, extension dicts. |
| `indexer/runner.py` | `VectorStore` → `IndexStore` (import + type annotations). `vector_store.query()` is not called here — no logic change needed; `upsert`, `get_metadata`, `checkpoint`, `save`, `load_for_update`, `create_empty`, `created_at` all survive. |
| `indexer/cli.py` | `resolve_vector_store` already uses the registry; update registry key name if needed. No logic change. |
| `indexer/tests/stubs/vector_store.py` | Implement `IndexStore` instead of `VectorStore`; add stub `search()`. |

## Analysis: Changes to search

| File | Change |
|------|--------|
| `search/startup.py` | `media_ptr: StorePointer` → `media_src: MediaSource` (use `MediaSource.from_uri(settings.media)`). `vector_store: VectorStore` → `index_store: IndexStore`. Rename field in `AppState`. Remove rclone tmpdir management for media (MediaSource handles its own cleanup per `getmedia` call). |
| `search/config.py` | `uri_must_be_valid`: validate media URI with `MediaSource.from_uri()` instead of `StorePointer.parse()` (enables gdrive:// validation). |
| `search/app.py` | `/media/{path}`: `ctx.media_ptr.get_file_ctx(path)` → `ctx.media_src.getmedia(path)` (same context-manager protocol). `/search`: `ctx.vector_store.query(...)` → `ctx.index_store.search(...)` returning `list[IndexResult]`; `_to_result()` reads typed fields instead of raw dict. |
| `search/plugins.py` | `resolve_vector_store` → `resolve_index_store` (update import + registry key). |
| `search/tests/stubs/vector_store.py` | Implement `IndexStore` instead of `VectorStore`; add stub `search()`. |
| `search/tests/conftest.py` | Update fixture field names to match new `AppState`. |

---

## Task Breakdown

### Phase A — common
1. Create `common/src/common/media.py` (MediaFile, MediaSource, File/Rclone/Gdrive implementations, from_uri factory)
2. Rewrite `common/src/common/stores/base.py` (IndexResult + IndexStore ABC)
3. Update `common/src/common/stores/chroma.py` (ChromaIndexStore, search() method)
4. Update `common/src/common/registry.py` (INDEX_STORES, MEDIA_SOURCES)
5. Update `common/tests/` (adjust any tests that reference VectorStore/ChromaVectorStore)
6. Run common dev loop (setup → quality → test)

### Phase B — indexer
7. Thin-out `indexer/pointer.py` to re-exports from `common.media`
8. Update `indexer/runner.py` type annotations (VectorStore → IndexStore)
9. Update `indexer/tests/stubs/vector_store.py` (IndexStore stub)
10. Run indexer dev loop (setup → quality → test)

### Phase C — search
11. Update `search/startup.py` (MediaSource, IndexStore, renamed AppState fields)
12. Update `search/config.py` (media URI validation)
13. Update `search/app.py` (getmedia, search, _to_result)
14. Update `search/plugins.py` (resolve_index_store)
15. Update `search/tests/stubs/vector_store.py` + conftest
16. Run search dev loop (setup → quality → test)

### Phase D — push
17. Commit all phases (one commit per phase or combined)
18. Push to `claude/media-pointer-navigation-SXQPT`

---

## Invariants / Non-Goals

- `StorePointer` in `common/pointer.py` is **unchanged** — it is the index-DB
  transport layer and is not part of this refactor.
- `Vectorizer` / `VectorStore`-as-vectorizer is **unchanged**.
- `CaptionModel` in indexer is **unchanged**.
- `IndexMeta` / `meta.py` is **unchanged**.
- No webapp changes — the OpenAPI contract (`/search`, `/media/{path}`) is preserved.
- No new features — this is a pure interface refactor.

## Status
- [ ] Phase A: common
- [ ] Phase B: indexer
- [ ] Phase C: search
- [ ] Phase D: push
