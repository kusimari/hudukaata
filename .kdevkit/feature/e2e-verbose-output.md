# Feature: e2e-verbose-output

## Status

`in-review`

## Goal

Add detailed print output to `runner-scripts/e2e-test/test_e2e.py` so a human can
visually verify the full integration: indexer creates stores, incremental update
updates them, and search/webapp return the expected data.

## Design

- `_banner(msg)` — prints a wide `===` separator so each section stands out.
- `print_store_state(label)` — walks `STORE_DIR`, prints file tree with sizes,
  reads `index_meta.json` (which records `index_store`, `face_store`,
  `indexed_at`, `indexer_version`, `source`) and prints it pretty.
- `write_conf` gains `indexer_key = blip2-sentok-exif-insightface` so the search
  server loads the face store (previously the default `blip2-sentok-exif` was used
  implicitly, silently omitting face results).
- After each `index.sh` run: call `print_store_state`.
- In `running_services`: after readyz, call `/search?q=<term>` and `/faces`
  directly on the search API port and print pretty JSON; print the webapp HTML
  response status + first 300 chars.
- In each test function: print all assertion-relevant responses as pretty JSON
  before (or instead of bare list access).

## Task breakdown

- T1: Add `_banner` and `print_store_state` helpers
- T2: Add `indexer_key` to `write_conf`
- T3: In `test_phase1_subdir_a`: `print_store_state` after index; pretty-print
     all responses; add direct search-API call + `/faces` call with prints
- T4: In `test_phase2_subdir_b_incremental`: same treatment as Phase 1
- T5: Quality gate (ruff only — no mypy for runner scripts)
