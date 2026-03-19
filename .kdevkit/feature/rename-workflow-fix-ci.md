# Feature: rename-workflow-fix-ci

## Status

`in-review`

## Requirements

1. Rename `.kdevkit/feature-dev.md` → `outerspace-loop.md` and `.kdevkit/agent-dev-loop.md` → `innerspace-loop.md`
2. Update outerspace-loop to play back the plan summary and sub-agent merge summary before human review (Phase 2.5)
3. Update all references to the old file names across the codebase
4. Fix GitHub CI failures:
   - **indexer**: mypy errors in `insightface.py` — CI has insightface installed (`import-untyped`) but local doesn't (`import-not-found`). Need to handle both.
   - **common**: nix flake lock fetching corrupt nixpkgs tarball — update `flake.lock`

## Design

- **File renames**: `git mv` the files, update references in `CLAUDE.md`, `README.md`, `outerspace-loop.md` (self-refs), `modify-kdevkit.md`
- **Phase 2.5**: new section in outerspace-loop between Phase 2 and Phase 3 that presents plan recap + merge commit summary + diff stats
- **insightface.py**: use `# type: ignore[import-untyped,import-not-found]` to cover both CI and local environments
- **flake.lock**: run `nix flake update` to get a fresh nixpkgs commit that doesn't have the corrupt tarball

## Testing

- ruff format/check clean
- mypy clean for all Python packages
- pytest passing for all Python packages
- Verify references are consistent with grep

## Plan

1. Rename files (done: git mv)
2. Update outerspace-loop.md content (done: Phase 2.5 added, innerspace-loop refs updated)
3. Update CLAUDE.md reference (done)
4. Update README.md, modify-kdevkit.md references
5. Fix insightface.py type: ignore comments
6. Update flake.lock
7. Quality gate + test gate
8. Commit and push
