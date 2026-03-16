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
    review-prompt.md            # incremental code-review prompt
    pr-review-prompt.md         # whole-diff PR review prompt
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

The full loop is:

```
Plan approved
  ↓
[i]  plan: commit (empty — records the approved plan summary)
  ↓
Dev loop (iterate until green):
  write code → quality gate → fix → test gate → fix
  ↓
[ii] dev: commit (all implementation files)
  ↓
PR review gate (full diff → pr-review-prompt sub-agent)
  ↓
[iii] review: commit (empty — records findings)
  ↓
Fix loop: address each finding → quality gate → test gate
  ↓
[iv] fixes: commit (all fix files)
  ↓
git push -u origin <branch>
  ↓
Ask human to open PR and paste the URL
  ↓
WebFetch diff → pr-review-prompt sub-agent → present findings
  ↓
Human reviews. On approval: note branch ready for merge, update feature file.
On changes: fix → quality → test → fixes: commit → push → repeat.
```

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

### Step i — Plan commit

Immediately after the plan is approved, before writing any code:

```bash
git commit --allow-empty -m "plan: <one-sentence summary of the approved plan>"
```

This anchors the diff baseline so that `git diff $(git merge-base HEAD main)...HEAD`
always covers exactly the implementation, not earlier work.

---

### Step 1 — Quality gate

#### Python packages (common / indexer / search)

1. **Ruff (binary — must be zero violations):** run from the package directory.
   ```bash
   ruff format src/ tests/
   ruff check --fix src/ tests/
   ruff check src/ tests/           # must exit 0 before continuing
   ```

2. **mypy (binary — must be zero errors):**
   ```bash
   python -m mypy src/<package>     # must exit 0 before continuing
   ```

3. **Compute the diff** against the base branch:
   ```bash
   git diff $(git merge-base HEAD main)...HEAD
   ```

4. **Read the quality threshold** from `.kdevkit/project.md` (`quality_threshold` field).
   Default: **70**.

5. **Launch a `general-purpose` sub-Agent** with:
   - The full diff as context
   - The contents of `.kdevkit/review-prompt.md` as the review prompt

   The agent returns a list of findings and a quality score (0–100).

6. **Decision:**
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

2. Compute diff and run the sub-agent review (same as Python step 3–6 above).

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
   - Suite green → proceed to commit gate.
   - Still failing after `max_test_fix_attempts` cycles → **stop**. Do NOT push.
     Report the remaining failures clearly so the human reviewer can decide.

5. If the fix requires non-trivial code changes (more than a one-liner), re-run the
   quality gate (Step 1) once before continuing.

---

### Step ii — Dev commit

After quality and test gates both pass:

```bash
git add <specific files — never git add -A>
git commit -m "dev: <what was implemented>"
```

---

### PR review gate

Run the full-diff review using `pr-review-prompt.md`:

```bash
git diff $(git merge-base HEAD main)...HEAD
```

Launch a `general-purpose` sub-Agent with:
- The full diff as context
- The contents of `.kdevkit/pr-review-prompt.md` as the review prompt

The agent returns findings and a score.

---

### Step iii — Review commit

Record the PR review findings in git history (empty commit):

```bash
git commit --allow-empty -m "review: <one-line summary>

<full findings from the sub-agent, verbatim>"
```

---

### Fix loop

Address each finding from the review:
- Fix → run quality gate (Step 1) → run test gate (Step 2)
- Repeat until all findings are resolved or explicitly deferred

---

### Step iv — Fixes commit

```bash
git add <specific files>
git commit -m "fixes: <how each finding was addressed>"
```

---

### Push gate

Only after all affected packages pass both gates and fixes are committed:

```bash
git push -u origin <feature-branch>
```

---

### Human review gate

After pushing:
1. Ask the human to open a PR and paste the URL.
2. `WebFetch` the diff URL → launch `pr-review-prompt` sub-agent → present findings
   in the conversation.
3. Wait for human response:
   - **Approve** → note "branch `<name>` ready for merge"; update feature file
     status to `ready-for-merge`.
   - **Request changes** → fix → quality → test → new `fixes:` commit → push → repeat.

Do **NOT** merge — leave that for the human reviewer.

---

### Squash merge summary

When the human asks for a squash merge summary, compose it from the structured
commit messages already in the branch — do not re-read the diff.

```bash
git log --format="%h %s" $(git merge-base HEAD main)..HEAD
```

Collect the commits in order:

| Prefix | Used for |
|---|---|
| `plan:` | Goal and architectural decisions |
| `dev:` | Files created/modified and design choices |
| `review:` | Quality score and findings |
| `fixes:` | How each finding was resolved |
| Any other `fix:`/`docs:`/`style:` commits | Include as a one-liner under "Additional fixes" |

Write the summary in this structure:

```
<feature title from plan: subject>

## What changed
<2–4 bullet points drawn from dev: body — files, key design decisions>

## Why
<goal paragraph from plan: body>

## Review findings resolved
<finding resolution lines from fixes: body; omit deferred items or note them>

## Quality gate
<score line from review: subject, e.g. "Score 85/100 PASS">
```

Keep the total under ~40 lines. Omit sections that have no content.

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
