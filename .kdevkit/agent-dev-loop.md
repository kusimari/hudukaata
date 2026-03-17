# Agent Dev Loop

The implementation loop for Phase 2. All project-specific commands, thresholds,
and package dependencies live in `.kdevkit/project.md` — read it first.

---

## The loop

```
setup
 → code
 → quality gate  ◄──────────────────────────────────────────────┐
    fail: fix → re-run quality (max 1 retry, then proceed+note)  │
 → test gate                                                      │
    fail: fix → [non-trivial change? → re-run quality ───────────┘] → re-run test
 → auto-review
    findings: fix → quality → test → re-run auto-review
 → dev: commit
 → PR review
    findings: fix → quality → test → fixes: commit
 → push → human-ready
```

Any stage can loop back to any prior stage. Quality is re-entered any time
non-trivial code is written — including after test fixes and review fixes.
The loop runs once per affected package (see scope rule in `project.md`).

---

## Git commit prefixes

Use these prefixes to build a structured commit history that tells the full story
of the feature from plan through human review:

| Prefix | When | Content |
|---|---|---|
| `plan:` | Before first line of code (empty commit) | One-sentence plan summary |
| `dev:` | After quality + test gates pass | What was implemented |
| `review:` | After auto PR review (empty commit) | Review findings verbatim |
| `fixes:` | After fix loop | How each finding was resolved |
| `hfix:` | After human review changes | What the human asked for |

Rules:
- `plan:` and `review:` are **empty commits** (`--allow-empty`) — they anchor history, not code.
- Never use `git add -A` or `git add .` — stage specific files only.
- Every commit leaves the repo in a working state.

---

## Stage 0 — Setup

Run once per affected package at the start of every session (or after any environment
file change). Use the setup command from `project.md`.

If a tool is missing or a dependency fails: fix the environment config file
(`flake.nix`, `pyproject.toml`, `package.json`) — never add runtime guards in
application code or tests to paper over a broken environment.

---

## Stage 1 — Quality gate

1. Run the formatter and linter from `project.md` for this package. Both must exit 0.
2. Run the type checker from `project.md` for this package. Must exit 0.
3. Compute the diff against the merge base:
   ```bash
   git diff $(git merge-base HEAD main)...HEAD
   ```
4. Launch a sub-agent with the diff + `.kdevkit/review.md` **§ Incremental review** as the prompt.
5. Read `quality_threshold` from `project.md` (default 70).
   - Score ≥ threshold → proceed to Stage 2.
   - Score < threshold → address the highest-severity findings, re-run the sub-agent **once**.
     If still below threshold, proceed and note the score in the commit message.

---

## Stage 2 — Test gate

1. Run tests using the test command from `project.md` for this package.
2. Zero failures required.
3. For each failure: fix and re-run. Count each fix-and-rerun against `max_test_fix_attempts`
   from `project.md` (default 2).
4. If still failing after the limit: **stop**. Do not push. Report the remaining failures
   so the human can decide.
5. If the fix required non-trivial code changes, re-run Stage 1 once before continuing.

---

## Stage 3 — Dev commit

After quality and test gates both pass for this package:

```bash
git add <specific files>
git commit -m "dev: <what was implemented>"
```

---

## Stage 4 — PR review gate

Compute the full diff and launch a sub-agent with `.kdevkit/review.md` **§ PR review**
as the prompt:

```bash
git diff $(git merge-base HEAD main)...HEAD
```

Record findings in an empty commit:

```bash
git commit --allow-empty -m "review: <one-line summary>

<full findings from the sub-agent, verbatim>"
```

---

## Stage 5 — Fix loop

Address each finding from the PR review:
1. Fix → Stage 1 (quality) → Stage 2 (test).
2. Repeat until all findings are resolved or explicitly deferred.
3. Commit:
   ```bash
   git add <specific files>
   git commit -m "fixes: <how each finding was addressed>"
   ```

---

## Stage 6 — Push

Only after all affected packages pass all gates and fixes are committed:

```bash
git push -u origin <feature-branch>
```

---

## Stage 7 — Human review gate

1. Ask the human to open a PR and paste the URL.
2. `WebFetch` the diff URL → launch sub-agent with PR review prompt → present findings.
3. Wait for human response:
   - **Approve** → update feature file status to `ready-for-merge`. Do NOT merge.
   - **Request changes** → fix → Stage 1 → Stage 2 → `hfix:` commit → push → repeat.

---

## Squash merge summary

When the human asks for a squash merge summary, read the structured commit log —
do not re-read the diff:

```bash
git log --format="%h %s%n%b" $(git merge-base HEAD main)..HEAD
```

Build the summary from commit prefixes:

```
<one-line summary from plan: subject>

<Feature summary: what problem this solves and why — from plan: body>

Changes:
- <one bullet per important file or design decision — from dev: body>

Testing:
- <test strategy and what was validated — from test gate and dev: body>
- Quality score: <N>/100 PASS  (or note score + reason if below threshold)
```

Keep it under ~40 lines. Omit empty sections.
