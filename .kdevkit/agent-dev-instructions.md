# Agent Development Instructions — hudukaata

## Repo layout

```
hudukaata/
  indexer/          # Python package (hatchling, ruff, mypy, pytest)
    src/indexer/    # source code
    tests/          # pytest test suite
  .github/
    workflows/      # quality-gate.yml (lint + test gate on PRs)
  .kdevkit/
    project.md      # project context + quality gate settings
    agent-dev-instructions.md  # this file
    review-prompt.md            # code-review prompt for the sub-agent
```

## Local commands

Run all commands from `indexer/` after `pip install -e ".[dev]"` (first time only).

```bash
# Lint
ruff check src/ tests/

# Format check (CI-safe, no modifications)
ruff format --check src/ tests/

# Auto-format (local development)
ruff format src/ tests/

# Type check
mypy src/indexer

# Tests (use python -m pytest to ensure the correct interpreter)
python -m pytest tests/ -v

# Full local quality gate (equivalent to CI)
ruff check src/ tests/ && ruff format --check src/ tests/ && mypy src/indexer && python -m pytest tests/ -v
```

## Mandatory workflow after every code change

The loop is: **Code → Quality → Code → Test → Push**.

Quality uses a configurable score threshold — it does not require zero findings.
Tests require zero failures.

---

### Step 1 — Quality gate

1. **Ruff (binary — must be zero violations):**
   ```bash
   ruff format src/ tests/          # auto-format first
   ruff check --fix src/ tests/     # auto-fix what ruff can
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

---

### Step 2 — Test gate

1. Run tests:
   ```bash
   cd indexer && python -m pytest tests/ -v
   ```

2. **Zero failures required.** Fix all failures; re-run until the suite is fully green.

3. If the fix requires non-trivial code changes (more than a one-liner), re-run the
   quality gate (Step 1) once before pushing.

---

### Push gate

Only after both gates pass:
```bash
git push -u origin <feature-branch>
```

Do **NOT** open a PR or merge — leave that for the human reviewer.

---

## Notes on testing

- No real models, no GPU, no rclone in tests — use stubs/mocks only.
- Tests live in `indexer/tests/`.
- Every new code path (branch, exception handler, edge case) should have a test.
