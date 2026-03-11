# Feature: create-search

## Status: In Progress (quality gate running)

## Summary
Create a semantic search server for the hudukaata monorepo.

## What Was Done

### common/ package (new)
- `common/src/common/pointer.py` — `_BasePointer` + `StorePointer` extracted from indexer
- `common/src/common/meta.py` — `IndexMeta` dataclass + `INDEX_META_FILE` constant
- `common/src/common/stores/base.py` — `VectorStore` ABC
- `common/src/common/stores/chroma.py` — `ChromaVectorStore` (moved from indexer)
- `common/src/common/vectorizers/base.py` — `Vectorizer` ABC
- `common/src/common/vectorizers/sentence_transformer.py` — `SentenceTransformerVectorizer` (moved)
- `common/src/common/plugins.py` — `resolve_instance()` with isinstance validation
- `common/pyproject.toml` + `py.typed` marker
- Tests: test_meta.py, test_pointer.py (27 tests all passing)

### indexer/ changes
- `indexer/src/indexer/pointer.py` — removed `_BasePointer`/`StorePointer`, imports from common
- `indexer/src/indexer/swap.py` — imports `StorePointer` from common
- `indexer/src/indexer/runner.py` — uses `IndexMeta.now()` to write extended `index_meta.json`
  with `vectorizer` and `vector_store` fields
- `indexer/src/indexer/cli.py` — imports from common, uses `resolve_instance` from common.plugins
- Deleted: `stores/base.py`, `stores/chroma.py`, `vectorizers/base.py`, `vectorizers/sentence_transformer.py`
- Updated: pyproject.toml (removed chromadb, sentence-transformers deps)
- Tests updated to import from common

### search/ package (new)
- `search/src/search/config.py` — pydantic-settings with URI + top_k validators, Literal log_level
- `search/src/search/plugins.py` — registry + resolve_instance from common
- `search/src/search/startup.py` — loads DB via get_dir() (not ctx), stores cleanup path
- `search/src/search/app.py` — FastAPI, /search + /healthz, safe ctx access, cleanup on shutdown
- `search/src/search/__main__.py` — uvicorn entry point
- Tests: test_config.py, test_startup.py, test_search_route.py (19 tests all passing)

### flake.nix
- Added `common` and `search` devShells
- Updated `indexer` shellHook to install common first

## Test Results
- common: 27/27 pass
- indexer: 61/61 pass (blip2 tests skipped — ffmpeg not in env, pre-existing)
- search: 19/19 pass

## Quality Gate
- ruff: all packages pass
- mypy strict: all packages pass
- Second quality review: pending
