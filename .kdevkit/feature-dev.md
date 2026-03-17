# Feature Development Workflow

Every feature goes through three phases. Never chain phases automatically —
wait for explicit human input at each gate.

---

## Phase 1 — Requirements & Planning  (interactive)

**Goal:** arrive at an approved plan before writing a single line of code.

1. Read `.kdevkit/project.md` to orient on the project structure and constraints.
2. Check `.kdevkit/feature/` for an existing file matching the feature name.
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

---

## Phase 2 — Implementation  (agent-driven)

**Goal:** implement the approved plan, pass all quality and test gates, and push.

1. Follow `.kdevkit/agent-dev-loop.md` exactly.
2. Run the full loop for every affected package (scope rule is in `project.md`).
3. When all packages are green and changes are pushed, update the feature file
   status to `in-review` and ask the human to open a PR.

**Gate:** Do not move to Phase 3 until the push is done and the human has the PR URL.

---

## Phase 3 — Human Review  (human-led)

**Goal:** incorporate human feedback and reach `ready-for-merge`.

- **Minor fixes** (no design changes): stay in Phase 2 — fix, quality gate, test gate,
  `hfix:` commit, push, update the feature file.
- **Significant rework** (design or requirements change): return to Phase 1 — revise
  the feature file and get a new approval.
- **Approved**: set feature file status to `ready-for-merge`. Do NOT merge — leave
  that for the human reviewer.

---

## Feature file discipline

- Update `.kdevkit/feature/<name>.md` after each meaningful unit of work (not in batches).
- The file is the single source of truth for what was decided, why, and what was done.
- Use it to resume interrupted sessions without losing context.
