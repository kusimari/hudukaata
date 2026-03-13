# hudukaata end-to-end test

`test_e2e.py` is a pytest integration test that exercises the full pipeline
in two phases: an initial index of one subfolder, followed by an incremental
update from a different subfolder.

## What it tests

```
Phase 1 — index subdir_a/ (blue_sky.png + green_field.png)
      |
      v
  indexer  --folder subdir_a
      |  writes ChromaDB store (2 documents)
      v
  search API  (port 18080)
  webapp      (port 15173)
      |
  assertions
    1. GET /                       -> response body contains <html
    2. GET /api/search?q=blue+sky  -> >= 1 result, all paths contain "subdir_a"
                                      (folder scoping: subdir_b is not present yet)

Phase 2 — incrementally index subdir_b/ (red_sunset.png, generated at runtime)
      |
      v
  indexer  --folder subdir_b  (loads existing DB, adds 1 new file)
      |  updated ChromaDB store (3 documents total)
      v
  search API  (restarted)
  webapp      (restarted)
      |
  assertions
    3. GET /                         -> response body contains <html
    4. GET /api/search?q=outdoor     -> >= 3 results (both subdirs indexed)
    5. GET /api/search?q=sunset      -> at least one path contains "subdir_b"
                                        (confirms incremental update was applied)
    6. GET /api/search?q=blue+sky    -> at least one path contains "subdir_a"
                                        (confirms no data loss)
```

Using two different subfolders (not just two batches of the same folder) gives
confidence that the folder-scoping feature correctly limits what the indexer
processes, and that the incremental update mechanism accumulates results across
independent runs.

## Running locally

```
pytest runner-scripts/e2e-test/test_e2e.py -v
```

Run this from the `e2e` nix shell:

```
nix develop .#e2e
pytest runner-scripts/e2e-test/test_e2e.py -v
```

Requires: `nix` with flakes enabled.  Models are cached after the first run
(`~/.cache/huggingface`).  `red_sunset.png` is generated at runtime via PIL
inside the indexer nix shell; no binary asset is committed.
