# Code Review Prompt

## Baseline standard

Follow [Google Engineering Practices — What to Look for in a Code Review](https://github.com/google/eng-practices/blob/master/review/reviewer/looking-for.md):
design, functionality, complexity, tests, naming, comments, style, documentation.

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

A violation that would fail either tool is a **High** finding.

### Per-package constraints

| Package | Additional constraints |
|---|---|
| `common` | Abstract base classes and interfaces only — no concrete implementations. |
| `indexer` | Each pipeline stage must be a callable `list[T] → list[U]` with a `batched: bool` attribute. No real models, GPU, or rclone in tests — stubs only. OOM must not corrupt the store. |
| `search` | FastAPI routers only; no business logic in route handlers. |
| `webapp` | All API calls through the typed service layer; no raw `fetch` in components. |

Apply only the row(s) matching the package(s) being changed.

---

## Severity definitions

**High** — would cause a bug, data loss, resource exhaustion, CI failure, or a type
error reachable in production. Fix before merging.

**Medium** — degrades maintainability, test coverage, or readability in a meaningful
way. Should be addressed but won't block merge.

**Low** — style, naming, minor clarity. Optional to fix.

---

## Review criteria

### 1. Correctness and edge cases
- Does the logic match the stated intent?
- Boundary conditions: empty collection input, `None` / `undefined` fields, zero or
  single-item input, very large input.
- Are generator / iterator pipelines fully consumed? Are tail items after the last
  full batch handled?
- Are all exit paths (normal and exception) handled correctly?

### 2. Resource safety
- File handles, temporary directories, and any OS resources released on all exit
  paths, including exceptions.
- No unbounded accumulation (growing lists, caches, buffers) without a size limit.
- Large intermediate objects discarded as soon as they are no longer needed.

### 3. Error handling
- Exceptions caught at the right granularity (per-item, per-batch, or fatal).
- Error messages specific enough to locate the problem (file path, item ID, etc.).
- Cleanup in `finally` / context managers / `try/catch` — not just the happy path.
- Swallowed exceptions logged at `WARNING` or above, never silently discarded.

### 4. Type safety
- **Python:** all parameters and return types annotated; `X | None` preferred over
  `Optional[X]`; no bare `list` / `dict` generics; no new `Any` without a comment.
- **TypeScript:** no `any` without a comment; no non-null assertions (`!`) without
  justification; strict null checks respected.
- No type errors that would be caught by the project's type checker.

### 5. Test coverage
- Every new code path (branch, exception handler, edge case) has a test.
- Tests assert on meaningful outcomes — not just "no exception raised".
- Stubs / mocks faithful enough to catch real bugs (wrong output shape, wrong
  type, wrong call signature should not be silently accepted).
- Tests do not import real external resources (models, network, GPU, cloud storage).

### 6. Architecture and package boundaries
- New logic placed in the correct module; no blurring of package boundaries.
- Public surface minimal; internals properly private (`_` prefix in Python,
  unexported in TypeScript).
- New abstractions do not duplicate existing ones.
- The change fits the established pattern for its package (see per-package
  constraints table above).

### 7. Security hygiene
- No hardcoded credentials, tokens, API keys, or machine-specific paths.
- No `shell=True` in subprocess calls (Python); no `eval` or `innerHTML` with
  untrusted input (TypeScript).
- Sensitive values (user paths, GPS coordinates, PII) not logged at INFO or above.

### 8. Naming and readability
- Names self-explanatory at the call site without reading the body.
- Magic numbers replaced with named constants.
- Non-obvious logic has a comment explaining *why*, not *what*.
- No commented-out code blocks — delete or open a task.

### 9. Dependency hygiene
- No unused imports.
- No new third-party dependencies without a corresponding `pyproject.toml` /
  `package.json` update.
- No circular imports (Python); no circular module references (TypeScript).
- Imports from sibling packages use the public surface, not internal modules.

### 10. Over-engineering
- No abstractions for hypothetical future requirements.
- No extension points (base classes, registries, feature flags) with only one
  implementation.
- Three similar lines of code is better than a premature helper.

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
