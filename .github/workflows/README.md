# CI Workflows

Two workflows protect the `main` branch. Both must pass before a PR can
merge (enforced via GitHub's merge queue — see setup instructions below).

---

## Workflows

### `quality-gate.yml` — lint, type-check, and unit tests

Triggers: `pull_request → main`, `merge_group → main`, `push → main`

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

Triggers: `merge_group → main`, `workflow_dispatch`

Runs the two-phase incremental index test in `runner-scripts/e2e-test/run.sh`:

1. **Phase 1** — index `batch1/` (2 sample images), start services, assert
   search returns results.
2. **Phase 2** — incrementally index `batch2/` (1 new synthetic image),
   restart services, assert all 3 files are searchable and the new path
   appears in results.

The test exercises the full stack: indexer (BLIP-2 + sentence-transformer),
search API (FastAPI), and webapp (Vite dev server).

**Runtime:** first run ~30–60 min (BLIP-2 ~4 GB + sentence-transformer
~100 MB download). Subsequent runs ~5–15 min (model weights cached in
GitHub Actions cache keyed by `pyproject.toml` hash).

**Timeout:** 60 minutes.

---

## Required secrets

| Secret | Where to set | Description |
|---|---|---|
| `CACHIX_AUTH_TOKEN` | Settings → Secrets → Actions | Write token for the `hudukaata` Cachix binary cache. Speeds up nix builds by reusing pre-built derivations. |

---

## GitHub settings to enable

All settings are under **Settings → Branches → Add rule → Branch name: `main`**.

### 1. Require a pull request before merging

```
[x] Require a pull request before merging
    [ ] Require approvals  (optional — set to 1 for review enforcement)
```

### 2. Require merge queue

```
[x] Require merge queue
    Method: Squash and merge  (or your preference)
    [x] Only allow merge queue to merge to matching branch
    Build concurrency: 1  (or higher if you want parallel queue entries)
```

Inside the merge queue settings, add required status checks:

```
Status checks that must pass:
  - all-green        ← from quality-gate.yml
  - e2e              ← from integration-test.yml
```

### 3. Additional recommended settings

```
[x] Do not allow bypassing the above settings
[ ] Allow auto-merge  ← leave OFF (merge queue replaces this)
```

---

## How the merge queue works

1. Developer opens a PR; `quality-gate` runs on every push (fast feedback).
2. When the PR is approved and ready, developer clicks **"Merge when ready"**
   (or maintainer clicks **"Add to merge queue"**).
3. GitHub creates a temporary merge-queue branch, runs both
   `quality-gate` (via `merge_group` trigger) and `integration-test`
   (via `merge_group` trigger) against the combined state of the queue.
4. If both pass → the commit is merged into `main` automatically.
5. If either fails → the PR is ejected from the queue; `main` is untouched.

This means the integration test runs **exactly once per merge attempt**,
not on every commit push to the PR branch.

---

## Dependency map (which jobs run when)

| Files changed | Jobs triggered |
|---|---|
| `common/**` or `flake.nix` | build-common, build-indexer, build-search |
| `indexer/**` | build-indexer |
| `search/**` | build-search |
| `webapp/**` | build-webapp |
| `runner-scripts/**` | *(unit jobs skipped; e2e catches these)* |
| anything (on merge queue) | all-green + e2e |
