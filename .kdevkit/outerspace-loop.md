# Feature Development Workflow

Every change (feature, fix, or user-asked change) goes through three phases.
Never chain phases automatically — wait for explicit human input at each gate.

---

## Phase 1 — Requirements & Planning  (interactive)

**Goal:** arrive at an approved plan before writing a single line of code.

1. Read `.kdevkit/project.md` to orient on the project structure and constraints.
2. Check `.kdevkit/feature/` for an existing file matching the feature/change name.
   - If found: load it and resume from where it left off.
   - If not found: create `.kdevkit/feature/<kebab-name>.md` with status `planning`.
3. Conduct four interviews — present one area at a time, wait for the human's answer,
   then move to the next:

   | # | Area | Key questions |
   |---|---|---|
   | 1 | Requirements | What problem does this solve? Who uses it? What does success look like? |
   | 2 | Design | What is the technical approach? What changes, what stays the same? Any architectural decisions? |
   | 3 | Testing | How will we validate correctness? What are the key scenarios (happy path, error paths, edge cases)? |
   | 4 | Implementation | What is the ordered task list? What are the risks or unknowns? |

4. Present a compact plan summary (≤ 20 lines). **Wait for explicit approval.**
5. Update the feature file with the approved plan. Set status to `approved`.

**Gate:** Do not start Phase 2 until the human says the plan is approved.
Exception: if the human says "yolo", skip phase gates until they say "yolo off".

**Follow-up requests (post-planning):** Any subsequent request in the same session
(e.g. "also fix X", "change Y", or inline corrections like the current conversation)
must go through the same four planning stages, but in **yolo mode** — each stage
executes without waiting for human approval between them. Update the feature file
and set status to `approved` before proceeding to Phase 2.

---

## Phase 2 — Implementation  (agent-driven)

**Goal:** implement the approved plan via a sub-agent, pass all quality and test gates,
and push.

1. Spawn a sub-agent with:
   - The feature file path and the approved plan.
   - The instruction: "Follow `.kdevkit/innerspace-loop.md` exactly."
2. The sub-agent creates a work branch, implements, passes all gates, and merges back
   to the feature branch (details in `innerspace-loop.md`). It does **not** push.
3. After the sub-agent returns: run all in-scope package tests on the feature branch.
   - If any test fails: re-spawn the sub-agent with the original ask + failure output.
   - Retry until tests pass (respecting `max_test_fix_attempts` from `project.md`).
4. When all packages are green: push the feature branch with a squash-merge summary
   commit (format from `innerspace-loop.md § Squash merge summary`).
5. Update the feature file status to `in-review`.

**Gate:** Do not move to Phase 3 until the push is done.

---

## Phase 2.5 — Summary Playback  (automatic)

**Goal:** give the human reviewer full context before they start reviewing.

After the Phase 2 push completes, present a structured summary to the human:

1. **Plan recap** — restate the approved plan from Phase 1 (what problem, what approach,
   key decisions). Keep it to ≤ 10 lines.
2. **Implementation summary** — extract from the sub-agent's merge commit message:
   - What was changed (the `Changes:` section)
   - What was tested (the `Testing:` section)
   - Quality score and verdict
3. **Diff stats** — run `git diff --stat <base>..HEAD` and include the output.

Format:

```
### Plan recap
<plan summary from the feature file>

### What was done
<changes and testing from the merge commit>

### Diff stats
<git diff --stat output>
```

This summary is informational — it does not block Phase 3. Proceed directly to
waiting for human review feedback.

---

## Phase 3 — Human Review  (human-led)

**Goal:** incorporate human feedback and reach `ready-for-merge`.

- **Minor fixes** (no design changes): treat as a follow-up request — plan in yolo mode,
  then re-run Phase 2 (sub-agent → test on feature branch → push with `hfix:` summary).
- **Significant rework** (design or requirements change): return to Phase 1 — revise
  the feature file and get a new approval.
- **Approved**: set feature file status to `ready-for-merge`. Do NOT merge — leave
  that for the human reviewer.

---

## Feature file discipline

- Update `.kdevkit/feature/<name>.md` after each meaningful unit of work (not in batches).
- The file is the single source of truth for what was decided, why, and what was done.
- Use it to resume interrupted sessions without losing context.
