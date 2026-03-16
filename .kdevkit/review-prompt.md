# Code Review Prompt

## Project context

You are reviewing a change to **hudukaata** — a Python/TypeScript monorepo that
indexes media files (images, video, audio) for semantic search and serves results
to a browser SPA.

Key constraints the reviewer must keep in mind:
- Runs on **resource-constrained hardware** (limited RAM, consumer GPU or CPU-only).
  Memory leaks, unbounded buffers, and unnecessary object retention are High findings.
- The **indexer** processes files through a functional pipeline of stages. Each stage
  is `list[T] → list[U]` with a `batched: bool` attribute. Violating this contract
  (wrong signature, missing attribute, mutable shared state between calls) is a High
  finding.
- **No real models, GPU, or rclone in tests** — stubs only. Tests that import real
  model weights or make network calls are High findings.
- Quality gate: `ruff` + `mypy --strict`. Type errors or ruff violations that would
  fail CI are High findings.
- Packages: `common` (shared), `indexer`, `search`, `webapp`. Changes that break
  the `common` public API without updating all downstream stubs are High findings.

---

## Severity definitions

**High** — would cause a bug, data loss, resource exhaustion, CI failure, or type
error in production. Fix before merging.

**Medium** — degrades maintainability, test coverage, or readability in a meaningful
way. Should be addressed but won't block merge.

**Low** — style, naming, minor clarity. Optional to fix.

---

## Review criteria

### 1. Correctness and edge cases
- Does the logic match the stated intent?
- Are boundary conditions handled: empty list input, `None` fields, zero batch size,
  single-item batch, very large batch?
- Generator pipelines: is the final generator consumed? Are partial flushes handled
  (tail items after the last full batch)?
- Context managers: are resources released on every exit path (normal and exception)?

### 2. Memory and resource safety
- Are file handles, temp dirs, and GPU tensors released promptly?
- Does any stage accumulate an unbounded list or cache without a size limit?
- On OOM: does the code recover gracefully, or does it leave partially-processed
  state that could corrupt downstream stores?
- Are large intermediate objects (image buffers, tensor batches) discarded as soon
  as they are no longer needed?

### 3. Pipeline semantics (indexer changes only)
- Does each new or modified stage have a `batched: bool` attribute set?
- Is the stage signature `list[T] → list[T]` (same-length output for map stages)?
  If length can change (items dropped), is that documented and tested?
- Does the stage drop individual failures rather than failing the whole batch, unless
  the failure is unrecoverable?
- Is `close_stage` (or equivalent cleanup) guaranteed to run even if an upstream
  stage raises?

### 4. Error handling
- Are exceptions caught at the right granularity (per-item vs per-batch vs fatal)?
- Are error messages specific enough to locate the problem file / batch?
- Is cleanup (temp files, open handles, DB transactions) guaranteed in `finally` or
  context managers?
- Are swallowed exceptions logged at `WARNING` or above, not silently ignored?

### 5. Type annotations (mypy strict)
- All parameters and return types annotated.
- `T | None` used instead of bare `Optional[T]` (Python 3.10+).
- Generics explicit: `list[str]` not `list`, `dict[str, str]` not `dict`.
- No `Any` introduced unless unavoidable and commented.
- Callable types annotated: `Callable[[list[BatchItem]], list[BatchItem]]`.

### 6. Test coverage
- Every new code path (branch, exception handler, OOM fallback, empty input) has a test.
- Tests assert meaningful outcomes: correct output contents, correct number of items
  emitted, correct calls on stubs — not just "no exception raised".
- OOM paths tested by injecting a `MemoryError` or `RuntimeError("out of memory")`.
- Stubs are minimal and do not hide real behaviour (e.g. a stub vectorizer that
  returns wrong-length output should be caught, not silently accepted).

### 7. Architecture adherence
- Does the change follow the established pattern for its package?
  - Indexer: functional stages, `BatchItem` as the data carrier, adaptive controller
    for batch sizing.
  - Common: abstract base classes only; no concrete implementations.
  - Search: FastAPI routers; no business logic in route handlers.
- Is new logic placed in the right module, or does it blur package boundaries?
- Does the change introduce a new abstraction that duplicates an existing one?

### 8. Security hygiene
- No hardcoded credentials, tokens, API keys, or paths referencing specific machines.
- No `shell=True` in subprocess calls.
- No sensitive values (file paths with usernames, EXIF GPS data) logged at INFO or above.

### 9. Naming and readability
- Names are self-explanatory at the call site without needing to read the body.
- Magic numbers replaced with named constants.
- Non-obvious logic has a one-line comment explaining *why*, not *what*.
- No commented-out code blocks — delete or open a task.

### 10. Import and dependency hygiene
- No unused imports.
- No new third-party dependencies added without a corresponding update to
  `pyproject.toml` / `package.json`.
- Circular imports not introduced.
- Imports from sibling packages use the correct public surface (`common.stores`,
  not internal modules).

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
