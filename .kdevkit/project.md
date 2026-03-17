# Project: hudukaata

## Purpose

A monorepo that indexes media (images, video, audio) for semantic search and streams results
to a browser SPA. All four packages are implemented and passing their quality gates.

## Tech Stack

- Python (common, indexer, search) — hatchling, ruff, mypy, pytest, FastAPI
- TypeScript + React (webapp) — Vite, Vitest, @testing-library/react
- Architecture: Monorepo; common is a shared library; indexer, search, and webapp are independent services

## Structure

```
hudukaata/
  common/        # shared Python utilities
  indexer/       # indexing jobs (Python)
  search/        # FastAPI search server (Python)
  webapp/        # browser SPA (TypeScript + React)
  .kdevkit/      # dev workflow metadata
```

## Package Status

| Package | Tests | Ruff | Mypy | Notes |
|---------|-------|------|------|-------|
| common  | 30/30 | ✓ | ✓ | Shared pointer, meta, stores, vectorizers |
| indexer | 71/75 | ✓ | ✓ | 4 ffmpeg/GPU tests require nix devShell |
| search  | 21/21 | ✓ | ✓ | FastAPI server; media streaming + CORS |
| webapp  | 28/28 | n/a | ✓ | Vite + React SPA; talks to search server |

---

## Package Dependency Map

```
common  ←── indexer
        ←── search
webapp  (depends on the search server's OpenAPI contract only, not its source)
```

**Scope rule:** run the dev loop for every package affected by a change.

| Package changed | Packages to loop |
|---|---|
| `common`    | `common`, `indexer`, `search` |
| `indexer`   | `indexer` |
| `search`    | `search` |
| `webapp`    | `webapp` |
| `flake.nix` | all packages whose devShell changed |

---

## Dev Environments

`flake.nix` at the repo root is the single source of truth for all dev environments.

### Cloud / CI (explicit setup — preferred for agent use)

Run the setup command for each affected package, then wrap all subsequent commands
in the same `nix develop .#<package> --command bash -c "..."`:

```bash
nix develop .#<package> --command bash -c "echo env ready"
```

### Desktop / laptop (direnv auto-activation)

One-time machine setup:
```bash
nix profile install nixpkgs#direnv nixpkgs#nix-direnv
echo 'eval "$(direnv hook bash)"' >> ~/.bashrc   # or zsh
```

One-time per clone, per package:
```bash
cd common  && direnv allow
cd indexer && direnv allow
cd search  && direnv allow
cd webapp  && direnv allow
```

---

## Per-Package Dev Loop Commands

### Setup

| Package | Command |
|---|---|
| `common`  | `nix develop .#common  --command bash -c "echo env ready"` |
| `indexer` | `nix develop .#indexer --command bash -c "echo env ready"` |
| `search`  | `nix develop .#search  --command bash -c "echo env ready"` |
| `webapp`  | `nix develop .#webapp  --command bash -c "echo env ready"` |

### Quality (run from the package directory)

**Python packages (common / indexer / search):**
```bash
ruff format src/ tests/          # auto-format
ruff check --fix src/ tests/     # auto-fix what ruff can
ruff check src/ tests/           # must exit 0
python -m mypy src/<package>     # must exit 0
```

**webapp:**
```bash
npm run typecheck                 # tsc --noEmit — must exit 0
```

### Tests (run from the package directory)

**Python packages:**
```bash
python -m pytest tests/ -v
```

**webapp:**
```bash
npm test                          # vitest run — zero failures required
```

### Build (webapp only)

```bash
npm run build                     # tsc --noEmit && vite build → dist/
```

---

## Quality Gate Settings

```
quality_threshold: 70
# Score 0–100; computed as max(0, 100 − penalty) where each High finding
# costs 10 pts, each Medium costs 3, each Low costs 1.
# Tune this value to adjust how strict the quality gate is.

max_test_fix_attempts: 2
# Maximum number of fix-and-rerun cycles for the test gate before stopping.
# When the limit is reached the agent must stop, report the remaining
# failures, and NOT push. The human reviewer decides what to do next.
```

---

## Per-Package Review Constraints

Apply only the row(s) matching the package(s) being changed. Used alongside
`.kdevkit/review.md` criteria.

| Package | Additional constraints |
|---|---|
| `common` | Abstract base classes and interfaces only — no concrete implementations. |
| `indexer` | Each pipeline stage must be a callable `list[T] → list[U]` with a `batched: bool` attribute. No real models, GPU, or rclone in tests — stubs only. OOM must not corrupt the store. |
| `search` | FastAPI routers only; no business logic in route handlers. |
| `webapp` | All API calls through the typed service layer; no raw `fetch` in components. |

---

## Testing Rules

- No real models, no GPU, no rclone in Python tests — use stubs/mocks only.
- Python tests live in `<package>/tests/`.
- TypeScript tests live in `webapp/src/tests/`.
- Every new code path (branch, exception handler, edge case) must have a test.

### Keeping stubs in sync across packages

Each package has its own stub implementations of shared interfaces. When an
**abstract method** is added or changed in `common/`, update every affected stub:

| Interface | Stubs to update |
|---|---|
| `common.stores.base.VectorStore` | `indexer/tests/stubs/vector_store.py`, `search/tests/stubs/vector_store.py` |
| `common.stores.base.Vectorizer` | `indexer/tests/stubs/vectorizer.py`, `search/tests/stubs/vectorizer.py` |

Stale stubs cause `TypeError: Can't instantiate abstract class` at test collection
time — a failure that only appears in CI when downstream packages are not looped locally.
