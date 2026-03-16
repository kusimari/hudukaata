# PR Review Prompt

## Purpose

Used for **whole-diff PR reviews** after implementation is complete and committed.
Differs from `review-prompt.md` (incremental, per-hunk) in scope: asks structural
questions about the whole change, not just per-hunk quality.

## Baseline standard

Follow [Google Engineering Practices — What to Look for in a Code Review](https://github.com/google/eng-practices/blob/master/review/reviewer/looking-for.md).
At PR level pay special attention to: design, complexity, over-engineering, and
test strategy across the whole change.

## Project context

**hudukaata** — a monorepo that indexes media files for semantic search and serves
results to a browser SPA. Packages: `common` (shared Python), `indexer` (Python),
`search` (FastAPI, Python), `webapp` (React + TypeScript).

Read `.kdevkit/project.md` for quality gate thresholds and tech stack details.

### Quality tooling

| Package | Formatter / linter | Type checker |
|---|---|---|
| `common`, `indexer`, `search` | `ruff` | `mypy --strict` |
| `webapp` | (ESLint if configured) | `tsc --noEmit` (strict) |

### Per-package constraints

| Package | Additional constraints |
|---|---|
| `common` | Abstract base classes and interfaces only — no concrete implementations. |
| `indexer` | Each pipeline stage must be a callable `list[T] → list[U]` with a `batched: bool` attribute. No real models, GPU, or rclone in tests — stubs only. OOM must not corrupt the store. |
| `search` | FastAPI routers only; no business logic in route handlers. |
| `webapp` | All API calls through the typed service layer; no raw `fetch` in components. |

Apply only the row(s) matching the package(s) touched by this PR.

---

## Severity definitions

**High** — would cause a bug, data loss, resource exhaustion, CI failure, or a type
error reachable in production. Fix before merging.

**Medium** — degrades maintainability, test coverage, or readability in a meaningful
way. Should be addressed but won't block merge.

**Low** — style, naming, minor clarity. Optional to fix.

---

## Review criteria

### 1. Plan conformance
- Does the implementation match the approved plan recorded in the `plan:` commit?
- Are any plan items missing or silently changed?
- If the implementation deviates, is the deviation an improvement or a regression?

### 2. Structural simplicity
- Are there unnecessary files, layers, or abstractions?
- Does each new module have a single, clear responsibility?
- Are there classes or functions used only once that could be inlined?
- Are there modules that should be merged?

### 3. Over-engineering
- Abstractions designed for hypothetical future requirements?
- Configuration or extension points (protocols, registries, feature flags) with
  only one implementation?
- Three similar lines that were unnecessarily abstracted into a helper?
- Future-proofing that adds complexity without present value?

### 4. Public API surface
- Is the public API minimal and stable?
- Internals properly private (`_` prefix in Python, unexported in TypeScript)?
- Are callers forced to know implementation details they shouldn't need?

### 5. Data flow coherence
- Is the end-to-end data flow legible without reading every function body?
- Can you trace a single item from source to sink in under five minutes?
- Are there surprising side-effects or hidden state mutations?

### 6. Resource safety (whole-diff view)
- Any unbounded collections or caches without size limits across the whole change?
- Objects (file handles, connections, large buffers) retained longer than needed?
- On error: is cleanup guaranteed, or is there partially-processed state that
  could corrupt downstream stores?

### 7. Performance
- Redundant passes over data (two loops where one would do)?
- Batching opportunities missed?
- Unnecessary copies of large data structures?

### 8. Test strategy
- Tests at the right level: unit for pure logic, integration for orchestration.
- Tests assert on contracts (inputs/outputs), not internals (private state,
  call counts).
- The suite covers: happy path, at least one error path, at least one edge case
  (empty input, single item).
- Stubs / mocks faithful enough to catch real bugs.

### 9. Correctness and edge cases
*(Recheck at PR level — same as `review-prompt.md` criteria 1–3.)*
- Empty input to every entry point?
- Tail / partial flush handled?
- All exit paths (normal and exception) correct?
- Per-item error isolation?

### 10. Type safety and dependency hygiene
*(Recheck at PR level — same as `review-prompt.md` criteria 4 and 9.)*
- All new code typed; no new untyped `any` / `Any` without comment.
- No unused imports; no new dependencies without manifest update.

---

## Output format

Return a flat list of findings. For each:

```
[Severity: High | Medium | Low]
File: <path>
Line(s): <range or "general">
Code: <the relevant snippet, ≤ 3 lines>
Issue: <one sentence>
Suggestion: <concrete fix — show code if helpful>
```

After the full list, output the score block:

```
---
High findings:   N  (× 10 pts = N pts)
Medium findings: N  (× 3 pts  = N pts)
Low findings:    N  (× 1 pt   = N pts)
Total penalty:   N
QUALITY SCORE:   N/100
VERDICT: PASS | FAIL
```

Threshold is `quality_threshold` from `.kdevkit/project.md` (default 70).
`PASS` if score ≥ threshold, `FAIL` otherwise.

If there are no findings:

```
No findings.

---
High findings:   0
Medium findings: 0
Low findings:    0
Total penalty:   0
QUALITY SCORE:   100/100
VERDICT: PASS
```
