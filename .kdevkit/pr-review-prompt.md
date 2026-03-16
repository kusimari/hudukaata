# PR Review Prompt

## Purpose

This prompt is used for **whole-diff PR reviews** — after the implementation is
complete and committed. It differs from `review-prompt.md` (which is run
incrementally during development) in scope: it asks structural questions about
the whole change, not just per-hunk quality.

## Project context

You are reviewing a pull request to **hudukaata** — a Python/TypeScript monorepo
that indexes media files (images, video, audio) for semantic search and serves
results to a browser SPA.

Key constraints:
- Runs on **resource-constrained hardware** (limited RAM, consumer GPU or CPU-only).
- The **indexer** processes files through a functional pipeline of stages. Each stage
  is `list[T] → list[T]` with a `batched: bool` attribute.
- **No real models, GPU, or rclone in tests** — stubs only.
- Quality gate: `ruff` + `mypy --strict`. Type errors or ruff violations are High.
- Packages: `common` (shared), `indexer`, `search`, `webapp`.

---

## Severity definitions

**High** — would cause a bug, data loss, resource exhaustion, CI failure, or type
error in production. Fix before merging.

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
- Does each new module have a single clear responsibility?
- Are there classes or functions used only once that could be inlined?
- Are there modules that should be merged?

### 3. Over-engineering
- Are there abstractions designed for hypothetical future requirements?
- Is there configuration for cases that don't exist yet?
- Are there three or fewer similar lines that were unnecessarily abstracted?
- Are there extension points (base classes, protocols, registries) with only one
  implementation?

### 4. Public API surface
- Is the public API minimal and stable?
- Are internals properly private (`_` prefix or module-private)?
- Are callers forced to know implementation details they shouldn't need to?

### 5. Memory safety
- Are there unbounded collections or caches without size limits?
- Are objects retained longer than necessary (e.g. large tensors, open file handles)?
- On OOM: is recovery clean, or is there partially-processed state that could
  corrupt downstream stores?
- Are large intermediate objects (image buffers, tensor batches) discarded promptly?

### 6. Performance
- Are there redundant passes over data (e.g. two `for` loops where one would do)?
- Are batching opportunities missed (e.g. calling a model once per item when
  `batch_size` items could be processed together)?
- Are there unnecessary copies of large data structures?

### 7. Data flow coherence
- Is the end-to-end data flow legible without reading every function body?
- Can you trace a single item from source to sink in under 5 minutes?
- Are there surprising side-effects that violate the functional pipeline contract?

### 8. Test strategy
- Are tests at the right level (unit for pure logic, integration for orchestration)?
- Do tests assert on contracts (inputs/outputs) rather than internals (call counts,
  private state)?
- Does the test suite cover the new happy path, at least one error path, and at
  least one edge case (empty input, single item, OOM)?
- Are stub implementations faithful enough to catch real bugs, or do they hide them?

### 9. Correctness and edge cases
(Same as `review-prompt.md` criteria 1–4 — recheck at PR level.)
- Empty input to every stage?
- Partial batch flush (tail items after the last full batch)?
- Context managers closed on all exit paths?
- Per-item error isolation (one bad file doesn't kill the whole batch)?

### 10. Type annotations and import hygiene
(Same as `review-prompt.md` criteria 5 and 10 — recheck at PR level.)
- All new code annotated; no new `Any` without comment.
- No unused imports; no new dependencies without `pyproject.toml` update.

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
