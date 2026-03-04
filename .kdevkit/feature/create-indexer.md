# Feature: Create Indexer Package

## Summary

Build the `indexer/` Python package — a CLI tool that scans a media directory
(local or rclone-backed), generates text captions + extracts EXIF data for
every media file, vectorizes the results, and writes them into a vector
database stored at a configurable location. Every component (captioner,
vectorizer, vector DB) is pluggable via abstract base classes.

---

## Directory Layout

```
hudukaata/
└── indexer/
    ├── pyproject.toml
    ├── src/
    │   └── indexer/
    │       ├── __init__.py
    │       ├── cli.py              # click CLI entry point
    │       ├── runner.py           # top-level orchestration
    │       ├── pointer.py          # MediaPointer — file:// vs rclone: abstraction
    │       ├── scanner.py          # recursive media-file discovery
    │       ├── exif.py             # EXIF / media metadata extraction
    │       ├── models/
    │       │   ├── __init__.py
    │       │   ├── base.py         # CaptionModel ABC
    │       │   └── blip2.py        # BLIP-2 via 🤗 transformers (default)
    │       ├── vectorizers/
    │       │   ├── __init__.py
    │       │   ├── base.py         # Vectorizer ABC
    │       │   └── sentence_transformer.py  # sentence-transformers (default)
    │       ├── stores/
    │       │   ├── __init__.py
    │       │   ├── base.py         # VectorStore ABC
    │       │   └── chroma.py       # ChromaDB (default)
    │       └── swap.py             # atomic DB swap logic
    └── tests/
        ├── __init__.py
        ├── conftest.py
        ├── stubs/
        │   ├── __init__.py
        │   ├── caption_model.py    # stub: returns filename as caption
        │   ├── vectorizer.py       # stub: returns fixed-length zero vector
        │   └── vector_store.py     # stub: in-memory dict
        ├── test_pointer.py
        ├── test_scanner.py
        ├── test_exif.py
        ├── test_swap.py
        └── test_runner.py
```

---

## Pointer Abstraction (`pointer.py`)

Accepts two URI schemes:
- `file:///absolute/path` — plain filesystem
- `rclone:remote-name:///path/on/remote` — delegates to rclone subprocess

```python
@dataclass
class MediaPointer:
    scheme: Literal["file", "rclone"]
    remote: str | None      # rclone remote name; None for file://
    path: str               # absolute path (on FS or remote)

    @staticmethod
    def parse(uri: str) -> "MediaPointer": ...

    # Yield (relative_path, local_temp_path) for every media file found.
    # For rclone, files are copied to a temp dir on demand.
    def iter_files(self) -> Iterator[tuple[str, Path]]: ...

    # Upload a local directory to this pointer location (used for store writes).
    def put_dir(self, local_src: Path) -> None: ...

    # Download the directory at this pointer into a local temp dir.
    # Returns the temp dir path. Caller must clean up.
    def get_dir(self) -> Path: ...

    # True if any DB directory exists at this pointer location.
    def has_dir(self, name: str) -> bool: ...

    # Rename a directory at this location (best-effort; no-op for rclone — see swap.py).
    def rename_dir(self, old: str, new: str) -> None: ...
```

**rclone commands used:**
| Operation | rclone command |
|-----------|---------------|
| List files | `rclone lsjson <remote>:<path> --recursive` |
| Download single file | `rclone copyto <remote>:<path/file> <local_dest>` |
| Download directory | `rclone copy <remote>:<path> <local_dest>` |
| Upload directory | `rclone copy <local_src> <remote>:<path>` |
| Rename directory | `rclone moveto <remote>:<old> <remote>:<new>` |

---

## Scanner (`scanner.py`)

Recursively finds all media files under a pointer. Recognised extensions:

| Type   | Extensions |
|--------|-----------|
| Image  | `.jpg .jpeg .png .gif .bmp .webp .tiff .heic .heif .avif` |
| Video  | `.mp4 .mkv .mov .avi .wmv .flv .webm .m4v` |
| Audio  | `.mp3 .flac .wav .aac .ogg .m4a .opus .wma` |

```python
def scan(pointer: MediaPointer) -> Iterator[MediaFile]:
    ...

@dataclass
class MediaFile:
    relative_path: str   # path relative to the media root (used as DB key)
    local_path: Path     # temp file path (caller must not delete until done)
    media_type: Literal["image", "video", "audio"]
```

---

## EXIF Extraction (`exif.py`)

Returns a flat `dict[str, str]` of key→value pairs for a given `MediaFile`.

| Media type | Library | Notes |
|------------|---------|-------|
| image | `Pillow` + `exifread` | GPS, datetime, camera make/model, orientation |
| video | `ffprobe` subprocess (JSON output) | duration, codec, resolution, creation_time |
| audio | `mutagen` | title, artist, album, duration, bitrate |

Unknown / unreadable tags are silently skipped. Result is always a flat dict
of strings so it serialises trivially to the vector DB metadata field.

```python
def extract_exif(mf: MediaFile) -> dict[str, str]: ...
```

---

## Captioning Model (`models/`)

### Base class

```python
class CaptionModel(ABC):
    @abstractmethod
    def caption(self, mf: MediaFile) -> str:
        """Return a human-readable text description of the media file."""
        ...

    def supports(self, media_type: str) -> bool:
        """Return True if this model handles the given media_type."""
        return True
```

### Default: BLIP-2 (`models/blip2.py`)

- **Images**: loaded with `transformers.Blip2Processor` + `Blip2ForConditionalGeneration`
  (default checkpoint: `Salesforce/blip2-opt-2.7b`). Run on CPU if no CUDA.
- **Video**: extract the middle keyframe via `ffmpeg` subprocess → treat as
  image → feed to BLIP-2.
- **Audio**: transcribe with `openai-whisper` (default model: `base`), return
  transcript as caption.

Model checkpoints are configurable via constructor args so callers can swap
them without subclassing.

```python
class Blip2CaptionModel(CaptionModel):
    def __init__(
        self,
        image_checkpoint: str = "Salesforce/blip2-opt-2.7b",
        whisper_model: str = "base",
        device: str | None = None,  # auto-detect
    ): ...

    def caption(self, mf: MediaFile) -> str: ...
```

---

## Vectorizer (`vectorizers/`)

### Base class

```python
class Vectorizer(ABC):
    @abstractmethod
    def vectorize(self, text: str) -> list[float]:
        """Embed text into a float vector."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output vector length."""
        ...
```

### Default: SentenceTransformer (`vectorizers/sentence_transformer.py`)

Uses `sentence-transformers` with checkpoint `all-MiniLM-L6-v2` (384 dims).

Input text is constructed as:

```
<caption>

EXIF:
<key>: <value>
<key>: <value>
...
```

```python
class SentenceTransformerVectorizer(Vectorizer):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"): ...
    def vectorize(self, text: str) -> list[float]: ...
    @property
    def dimension(self) -> int: ...
```

---

## Vector Store (`stores/`)

### Base class

```python
class VectorStore(ABC):
    @abstractmethod
    def load(self, local_path: Path) -> None:
        """Load existing DB from disk."""
        ...

    @abstractmethod
    def create_empty(self) -> None:
        """Initialise a new, empty DB in memory."""
        ...

    @abstractmethod
    def add(
        self,
        id: str,                  # relative media path — stable unique key
        vector: list[float],
        metadata: dict[str, str], # caption + exif merged
    ) -> None: ...

    @abstractmethod
    def save(self, local_path: Path) -> None:
        """Persist DB to disk at local_path."""
        ...

    @abstractmethod
    def created_at(self, local_path: Path) -> datetime | None:
        """Return the creation timestamp recorded inside the DB, or None."""
        ...
```

### Default: ChromaDB (`stores/chroma.py`)

- Uses `chromadb.Client(Settings(chroma_db_impl="duckdb+parquet", persist_directory=str(path)))`
  (embedded, file-based, no server needed).
- Collection name: `media`.
- `created_at` is stored as a JSON sidecar file `db_meta.json` written
  alongside the ChromaDB directory at save time.

```python
class ChromaVectorStore(VectorStore):
    def __init__(self, collection_name: str = "media"): ...
    def load(self, local_path: Path) -> None: ...
    def create_empty(self) -> None: ...
    def add(self, id, vector, metadata) -> None: ...
    def save(self, local_path: Path) -> None: ...
    def created_at(self, local_path: Path) -> datetime | None: ...
```

---

## Safe DB Swap (`swap.py`)

The store pointer always contains a directory named `db/` as the live DB.
During a run the indexer writes into `db_new/`. On completion:

```
Step 1  Write all vectors → store/db_new/
Step 2  If store/db/ exists:
            read created_at from store/db/db_meta.json
            rename store/db/ → store/db_YYYY-MM-DD/
                (for rclone: rclone moveto remote:path/db remote:path/db_YYYY-MM-DD)
Step 3  Rename store/db_new/ → store/db/
Step 4  Delete store/db_new/ if rename failed (cleanup guard)
```

If the run aborts mid-way, `db_new/` is left behind and `db/` is untouched.
On the next run `db_new/` is detected and cleaned up before starting.

```python
def prepare_temp_dir(store: MediaPointer, local_tmp: Path) -> None: ...
def commit(store: MediaPointer, local_tmp: Path, created_at: datetime | None) -> None: ...
def cleanup_stale_tmp(store: MediaPointer) -> None: ...
```

---

## Runner (`runner.py`)

Top-level orchestration — called by the CLI.

```python
def run(
    media: MediaPointer,
    store: MediaPointer,
    caption_model: CaptionModel,
    vectorizer: Vectorizer,
    vector_store: VectorStore,
) -> None:
    cleanup_stale_tmp(store)

    # Load or create DB into a local temp copy
    local_tmp = Path(tempfile.mkdtemp())
    existing_created_at: datetime | None = None

    if store has "db/":
        local_db = store.get_dir("db")           # download if rclone
        existing_created_at = vector_store.created_at(local_db)
        # We do NOT load the old DB — we build from scratch each run.

    vector_store.create_empty()

    for media_file in scan(media):               # yields MediaFile one at a time
        caption = caption_model.caption(media_file)
        exif    = extract_exif(media_file)
        text    = format_text(caption, exif)
        vector  = vectorizer.vectorize(text)
        meta    = {"caption": caption, **exif}
        vector_store.add(media_file.relative_path, vector, meta)

    # Persist new DB to local temp path
    vector_store.save(local_tmp / "db_new")

    # Upload + swap
    store.put_dir(local_tmp / "db_new", dest_name="db_new")
    commit(store, local_tmp, existing_created_at)
```

---

## CLI (`cli.py`)

```
indexer run --media <pointer> --store <pointer> [options]

Options:
  --media   TEXT   Media directory pointer. Required.
                   Formats: file:///path  or  rclone:remote:///path
  --store   TEXT   Store directory pointer. Required.
                   Same formats as --media.
  --caption-model TEXT  Captioner class to use [default: blip2]
  --vectorizer    TEXT  Vectorizer class to use [default: sentence-transformer]
  --vector-store  TEXT  Vector store class to use [default: chroma]
  --log-level     TEXT  Logging level [default: INFO]
```

Built with `click`. Defaults to the built-in implementations; advanced users
can pass a dotted import path to swap in custom classes.

---

## Dependencies (`pyproject.toml`)

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "indexer"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    # captioning
    "transformers>=4.38",
    "torch>=2.2",
    "Pillow>=10.3",
    "openai-whisper>=20231117",
    # exif
    "exifread>=3.0",
    "mutagen>=1.47",
    # vectorizer
    "sentence-transformers>=3.0",
    # vector store
    "chromadb>=0.5",
    # CLI
    "click>=8.1",
    # progress
    "tqdm>=4.66",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
]

[project.scripts]
indexer = "indexer.cli:main"
```

---

## Test Strategy

### Unit tests (no real models, no GPU, no rclone)

All tests use stub implementations injected via the pluggable interface.

| Test file | Tests |
|-----------|-------|
| `test_pointer.py` | URI parsing for both schemes; `file://` iter_files on a tmp dir fixture |
| `test_scanner.py` | Extension filtering; correct `media_type` assignment |
| `test_exif.py` | EXIF extraction on a small synthetic JPEG (Pillow-generated) |
| `test_swap.py` | Temp-dir naming; rename-old logic; stale-tmp cleanup |
| `test_runner.py` | Full run using stubs: assert every file gets added; assert swap called |

### Integration test outline (not automated by default)

- Requires `rclone` installed and a configured remote named `test-remote`.
- `tests/integration/test_rclone_pointer.py` — round-trip: put files, list, get.
- `tests/integration/test_full_run.py` — full run against a small fixture
  media directory on `file://`; assert ChromaDB written and populated.

---

## Implementation Order

1. `pyproject.toml` + package scaffold (`src/indexer/__init__.py`, `tests/`)
2. `pointer.py` — parse + `file://` implementation; rclone subprocess wrappers
3. `scanner.py` — extension map + `scan()`
4. `exif.py` — image branch first (Pillow/exifread); video + audio after
5. `models/base.py` + `models/blip2.py` (image branch first)
6. `vectorizers/base.py` + `vectorizers/sentence_transformer.py`
7. `stores/base.py` + `stores/chroma.py`
8. `swap.py`
9. `runner.py`
10. `cli.py`
11. `tests/stubs/` + unit tests
