# Agent Development Instructions — hudukaata

## Repo layout

```
hudukaata/
  common/           # Python package — shared utilities (pointer, etc.)
    src/common/
    tests/
  indexer/          # Python package — indexing jobs
    src/indexer/
    tests/
  search/           # Python package — FastAPI search server
    src/search/
    tests/
  webapp/           # TypeScript + React SPA — browser frontend
    src/
    src/tests/
  .github/
    workflows/      # quality-gate.yml (lint + test gate on PRs)
  .kdevkit/
    project.md      # project context + quality gate settings
    agent-dev-instructions.md  # this file
    review-prompt.md            # code-review prompt for the sub-agent
```

## Package dependency map

```
common  ←── indexer
        ←── search
webapp  (depends on the search server's OpenAPI contract only, not its source)
```

**Rule: run the dev loop for every package affected by a change.**

| Package changed | Packages to loop |
|---|---|
| `common`  | `common`, `indexer`, `search` |
| `indexer` | `indexer` |
| `search`  | `search` |
| `webapp`  | `webapp` |
| `flake.nix` | all packages whose devShell changed |

---

## Per-package quick reference

### Setup commands

| Package | Command |
|---|---|
| `common`  | `nix develop .#common  --command bash -c "echo env ready"` |
| `indexer` | `nix develop .#indexer --command bash -c "echo env ready"` |
| `search`  | `nix develop .#search  --command bash -c "echo env ready"` |
| `webapp`  | `nix develop .#webapp  --command bash -c "echo env ready"` |

### Quality commands (run from the package directory)

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

### Test commands (run from the package directory)

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

## Mandatory workflow after every code change

The loop is: **Setup → Code → Quality → Code → Test → Push**.

Run this loop for **each affected package** (see dependency map above).
Quality uses a configurable score threshold — it does not require zero findings.
Tests require zero failures.

---

### Step 0 — Setup environment

Run once at the start of every coding session (or after any `flake.nix` change),
for each affected package:

```bash
nix develop .#<package> --command bash -c "echo env ready"
```

If a tool is missing or a dependency fails to install, fix `flake.nix` or
`pyproject.toml` / `package.json` — do not add runtime guards in application
code or tests.

---

### Step 1 — Quality gate

#### Python packages (common / indexer / search)

1. **Ruff (binary — must be zero violations):** run from the package directory.
   ```bash
   ruff format src/ tests/
   ruff check --fix src/ tests/
   ruff check src/ tests/           # must exit 0 before continuing
   ```

2. **Compute the diff** against the base branch:
   ```bash
   git diff $(git merge-base HEAD main)...HEAD
   ```

3. **Read the quality threshold** from `.kdevkit/project.md` (`quality_threshold` field).
   Default: **70**.

4. **Launch a `general-purpose` sub-Agent** with:
   - The full diff as context
   - The contents of `.kdevkit/review-prompt.md` as the review prompt

   The agent returns a list of findings and a quality score (0–100).

5. **Decision:**
   - Score ≥ threshold → proceed to Step 2.
   - Score < threshold → address the highest-severity findings, then re-run the
     sub-agent **once**. Do not loop indefinitely on quality. If the score is still
     below threshold after one fix pass, proceed anyway and note the score in the
     commit message.

#### webapp

1. **TypeScript (binary — must be zero errors):** run from `webapp/`.
   ```bash
   npm run typecheck
   ```

2. Compute diff and run the sub-agent review (same as Python step 2–5 above).

---

### Step 2 — Test gate

1. Read the retry limit from `.kdevkit/project.md` (`max_test_fix_attempts` field).
   Default: **2**.

2. Run tests for each affected package:

   **Python packages:**
   ```bash
   python -m pytest tests/ -v
   ```

   **webapp:**
   ```bash
   npm test
   ```

3. **Zero failures required.** For each failure, attempt a fix and re-run.
   Count each fix-and-rerun cycle against `max_test_fix_attempts`.

4. **Decision:**
   - Suite green → proceed to push gate.
   - Still failing after `max_test_fix_attempts` cycles → **stop**. Do NOT push.
     Report the remaining failures clearly so the human reviewer can decide.

5. If the fix requires non-trivial code changes (more than a one-liner), re-run the
   quality gate (Step 1) once before pushing.

---

### Push gate

Only after all affected packages pass both gates:
```bash
git push -u origin <feature-branch>
```

Do **NOT** open a PR or merge — leave that for the human reviewer.

---

## Notes on testing

- No real models, no GPU, no rclone in Python tests — use stubs/mocks only.
- Python tests live in `<package>/tests/`.
- TypeScript tests live in `webapp/src/tests/`.
- Every new code path (branch, exception handler, edge case) should have a test.

### Keeping stubs in sync across packages

Each package has its own stub implementations of shared interfaces (e.g.
`VectorStore`, `Vectorizer`). When you add or change an **abstract method** in
`common/`, you **must** update the stub in every package that defines one:

| Interface | Stubs to update |
|---|---|
| `common.stores.base.VectorStore` | `indexer/tests/stubs/vector_store.py`, `search/tests/stubs/vector_store.py` |
| `common.stores.base.Vectorizer` | `indexer/tests/stubs/vectorizer.py`, `search/tests/stubs/vectorizer.py` (if they exist) |

Failing to update all stubs causes `TypeError: Can't instantiate abstract class`
at test collection time in the packages whose stubs are stale — a failure that
only appears in CI because the local dev loop may skip downstream packages.
