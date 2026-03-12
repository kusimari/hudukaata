# Project: hudukaata

## Purpose
A monorepo containing an indexing job service, a search server, and a browser frontend.
The system indexes media for semantic search and retrieval; the webapp provides the UX.

## Tech Stack
- Python (common, indexer, search) — hatchling, ruff, mypy, pytest, FastAPI
- TypeScript + React (webapp) — Vite, Vitest, @testing-library/react
- Architecture: Monorepo; common is a shared library; indexer, search, and webapp are independent services

## Constraints
Standard best practices for each language. Python: ruff + mypy strict. TypeScript: tsc strict mode.

## Quality Gate Settings

quality_threshold: 70
# Score 0–100; computed as max(0, 100 − penalty) where each High finding
# costs 10 pts, each Medium costs 3, each Low costs 1.
# Tune this value to adjust how strict the quality gate is.

max_test_fix_attempts: 2
# Maximum number of fix-and-rerun cycles for the test gate before stopping.
# When the limit is reached the agent must stop, report the remaining
# failures, and NOT push. The human reviewer decides what to do next.

## Structure
```
hudukaata/
  common/        # shared Python utilities
  indexer/       # indexing jobs (Python)
  search/        # FastAPI search server (Python)
  webapp/        # browser SPA (TypeScript + React)
  .kdevkit/      # dev workflow metadata
```

## Dev Environments

`flake.nix` at the repo root is the single source of truth for all dev
environments. Each sub-package has a named devShell; Python shells install
dependencies via a `shellHook`; the webapp shell runs `npm install`.

### Desktop / laptop (direnv auto-activation)

Each sub-package folder ships an `.envrc` that activates the correct shell
automatically when you `cd` into it.

One-time machine setup:
```bash
nix profile install nixpkgs#direnv nixpkgs#nix-direnv
echo 'eval "$(direnv hook bash)"' >> ~/.bashrc   # or zsh
```

One-time per clone, per package:
```bash
cd indexer && direnv allow
cd search  && direnv allow
cd webapp  && direnv allow
```

### Cloud / CI (explicit setup step)

Do not rely on direnv. Run the setup command for each affected package:
```bash
nix develop .#<package> --command bash -c "echo env ready"
```
Then run quality and test commands wrapped in the same `nix develop .#<package> --command bash -c "..."`.

### Manual activation (fallback for any context)

| Package  | Command                   |
|----------|---------------------------|
| common   | `nix develop .#common`    |
| indexer  | `nix develop .#indexer`   |
| search   | `nix develop .#search`    |
| webapp   | `nix develop .#webapp`    |
