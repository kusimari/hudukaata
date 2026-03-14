# CI Workflows

Two workflows exist. Only `quality-gate` is a required check on `main`.
`integration-test` is run manually before significant merges.

---

## Workflows

### `quality-gate.yml` — lint, type-check, and unit tests

Triggers: `pull_request → main`, `push → main`

Runs fast, per-package checks. Jobs are skipped when their package files
haven't changed (via `dorny/paths-filter`):

| Job | Package | What it checks |
|---|---|---|
| `build-common` | `common/` | ruff + mypy + pytest |
| `build-indexer` | `indexer/` (+ common) | ruff + mypy + pytest (ffmpeg via nix) |
| `build-search` | `search/` (+ common) | ruff + mypy + pytest |
| `build-webapp` | `webapp/` | tsc + vitest + vite build |
| `all-green` | — | fan-in: success or skipped for all above |

`all-green` is the single status check to require — individual jobs are
skipped when unaffected, and a skipped job doesn't satisfy a required
check, but `all-green` handles that correctly.

A `comment-on-failure` job posts a summary to the PR when any job fails.

---

### `integration-test.yml` — full end-to-end test

Triggers: `workflow_dispatch` (manual only)

Runs the two-phase incremental index test in `runner-scripts/e2e-test/run.sh`:

1. **Phase 1** — index `batch1/` (2 sample images), start services, assert
   search returns results.
2. **Phase 2** — incrementally index `batch2/` (1 new synthetic image),
   restart services, assert all 3 files are searchable and the new path
   appears in results.

Run this manually via **Actions → integration-test → Run workflow** before
merging significant changes (new indexer model, search ranking changes, etc.).

**Runtime:** first run ~30–60 min (BLIP-2 ~4 GB + sentence-transformer
~100 MB download). Subsequent runs ~5–15 min (model weights cached in
GitHub Actions cache keyed by `pyproject.toml` hash).

**Future plan:** add a `release` branch that `main` is pushed into via an
auto-merge workflow. Require `e2e` as a status check on `release`. This
gives a full integration gate without slowing down every PR on `main`.

---

## Required secrets

| Secret | Where to set | Description |
|---|---|---|
| `CACHIX_AUTH_TOKEN` | Settings → Secrets → Actions | Write token for the `hudukaata` Cachix binary cache. Speeds up nix builds by reusing pre-built derivations. |

---

## GitHub settings to enable

### Rulesets (Settings → Rules → Rulesets → New branch ruleset)

Target branch: `main`

```
[x] Restrict deletions
[x] Require a pull request before merging
    [ ] Require approvals  (optional — set to 1 for review enforcement)
[x] Require status checks to pass
    Status checks:
      - all-green        ← from quality-gate.yml
[x] Block force pushes
```

`e2e` is intentionally **not** a required check on `main`. It runs manually.

---

## Dependency map (which jobs run when)

| Files changed | Jobs triggered |
|---|---|
| `common/**` or `flake.nix` | build-common, build-indexer, build-search |
| `indexer/**` | build-indexer |
| `search/**` | build-search |
| `webapp/**` | build-webapp |
| `runner-scripts/**` | *(no unit jobs triggered; run e2e manually)* |
