# Code Review

Load per-package constraints from `.kdevkit/project.md` before reviewing.
Read `quality_threshold` from `project.md` to determine PASS / FAIL (default 70).

---

## § Incremental review

Used during the **dev loop quality gate** (per-hunk, after each coding round).

Baseline: [Google Engineering Practices — What to Look for in a Code Review](https://github.com/google/eng-practices/blob/master/review/reviewer/looking-for.md):
design, functionality, complexity, tests, naming, comments, style, documentation.

### Criteria

**1. Correctness and edge cases**
- Does the logic match the stated intent?
- Boundary conditions: empty input, `None` / `undefined`, zero or single-item, very large input.
- Generator / iterator pipelines fully consumed? Tail items after the last full batch handled?
- All exit paths (normal and exception) handled correctly?

**2. Resource safety**
- File handles, temp dirs, and OS resources released on all exit paths including exceptions.
- No unbounded accumulation (lists, caches, buffers) without a size limit.
- Large intermediate objects discarded as soon as they are no longer needed.

**3. Error handling**
- Exceptions caught at the right granularity (per-item, per-batch, or fatal).
- Error messages specific enough to locate the problem (file path, item ID, etc.).
- Cleanup in `finally` / context managers / `try/catch` — not just the happy path.
- Swallowed exceptions logged at WARNING or above, never silently discarded.

**4. Type safety**
- All parameters and return types annotated; no bare generics; no new untyped `any` / `Any`
  without a comment explaining why.
- Strict null checks respected. No non-null assertions without justification.
- No type errors catchable by the project's type checker.

**5. Test coverage**
- Every new code path (branch, exception handler, edge case) has a test.
- Tests assert on meaningful outcomes — not just "no exception raised".
- Stubs / mocks faithful enough to catch real bugs.
- Tests do not import real external resources (network, GPU, cloud storage).

**6. Architecture and package boundaries**
- New logic placed in the correct module; no blurring of package boundaries.
- Public surface minimal; internals properly private.
- No duplication of existing abstractions.
- Change fits the established pattern for this package (see `project.md`).

**7. Security hygiene**
- No hardcoded credentials, tokens, API keys, or machine-specific paths.
- No `shell=True` in subprocess calls; no `eval` or `innerHTML` with untrusted input.
- Sensitive values not logged at INFO or above.

**8. Naming and readability**
- Names self-explanatory at the call site without reading the body.
- Magic numbers replaced with named constants.
- Non-obvious logic has a comment explaining *why*, not *what*.
- No commented-out code — delete or open a task.

**9. Dependency hygiene**
- No unused imports.
- No new third-party dependencies without a manifest update.
- No circular imports / module references.
- Imports from sibling packages use the public surface only.

**10. Over-engineering**
- No abstractions for hypothetical future requirements.
- No extension points with only one implementation.
- Three similar lines of code is better than a premature helper.

---

## § PR review

Used at the **end of the dev loop** for the whole-diff review before pushing.

Baseline: same Google Engineering Practices, with emphasis on design, complexity,
over-engineering, and test strategy across the entire change.

### Criteria

**1. Plan conformance**
- Does the implementation match the approved plan recorded in the `plan:` commit?
- Are any plan items missing or silently changed?
- If the implementation deviates, is it an improvement or a regression?

**2. Structural simplicity**
- Unnecessary files, layers, or abstractions?
- Each new module has a single, clear responsibility?
- Classes or functions used only once that could be inlined?
- Modules that should be merged?

**3. Over-engineering**
- Abstractions for hypothetical future requirements?
- Extension points (protocols, registries, feature flags) with only one implementation?
- Future-proofing that adds complexity without present value?

**4. Public API surface**
- API minimal and stable?
- Internals properly private?
- Callers forced to know implementation details they shouldn't need?

**5. Data flow coherence**
- End-to-end data flow legible without reading every function body?
- Can you trace a single item from source to sink in under five minutes?
- Surprising side-effects or hidden state mutations?

**6. Resource safety (whole-diff view)**
- Unbounded collections or caches without size limits across the whole change?
- Objects retained longer than needed?
- On error: is cleanup guaranteed, or is there partially-processed state that could
  corrupt downstream stores?

**7. Performance**
- Redundant passes over data?
- Batching opportunities missed?
- Unnecessary copies of large data structures?

**8. Test strategy**
- Tests at the right level: unit for pure logic, integration for orchestration.
- Tests assert on contracts (inputs/outputs), not internals (private state, call counts).
- Suite covers: happy path, at least one error path, at least one edge case.
- Stubs / mocks faithful enough to catch real bugs.

**9. Correctness and edge cases**
*(Recheck at PR level — same as Incremental criteria 1–3.)*
- Empty input to every entry point?
- Tail / partial flush handled?
- Per-item error isolation?

**10. Type safety and dependency hygiene**
*(Recheck at PR level — same as Incremental criteria 4 and 9.)*
- All new code typed; no new untyped `any` / `Any` without comment.
- No unused imports; no new dependencies without manifest update.

---

## Severity definitions

**High** — would cause a bug, data loss, resource exhaustion, CI failure, or a type
error reachable in production. Fix before merging.

**Medium** — degrades maintainability, test coverage, or readability in a meaningful
way. Should be addressed but won't block merge.

**Low** — style, naming, minor clarity. Optional to fix.

A violation that would fail the project's linter or type checker is always **High**.

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

`PASS` if score ≥ `quality_threshold` from `project.md`, `FAIL` otherwise.

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
