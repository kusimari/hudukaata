# Feature: colab-run

**Status:** approved

**Issue:** https://github.com/kusimari/hudukaata/issues/17

## Problem

hudukaata only supports Nix devShell environments (local/CI). Google Colaboratory cannot use Nix. Users who want to index their Google Drive photos or search their media index from Colab have no supported path.

## Approach

Add two Jupyter notebooks to `runner-scripts/notebooks/`:
- `indexer.ipynb` — installs packages from Git, mounts Google Drive, runs the indexer by calling the indexer class directly (not the CLI)
- `search.ipynb` — installs packages from Git, mounts Google Drive, loads the index directly via `search.startup.load()` (no FastAPI), displays faces and enables text + face-ID search

No changes to any existing package source code. No automated tests (manual Colab validation per issue spec).

## Key reuse

- `common.media.GdriveMediaSource` — handles `gdrive:///` URIs, mounts Drive
- `indexer.indexers.blip2_sentok_exif_insightface_chroma.Blip2SentTokExifInsightfaceChromaIndexer` — called directly
- `indexer.indexers.blip2_sentok_exif_chroma.Blip2SentTokExifChromaIndexer` — called directly
- `indexer.runner.IndexingRunner` — orchestrates scan + pipeline + store commit
- `search.startup.load()` — loads index stores from a Settings object; used directly in search notebook
- `search.config.Settings` — constructed programmatically in the notebook

## Task list

1. Create `runner-scripts/notebooks/` directory
2. Write `indexer.ipynb`
3. Write `search.ipynb`
4. Commit and push to `claude/add-colab-run-feature-KFPa5`
