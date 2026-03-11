# Project: hudukaata

## Purpose
A Python monorepo containing an indexing job service and a search server. The system indexes data for fast searching and retrieval.

## Tech Stack
- Language: Python
- Architecture: Monorepo (indexer + search server as separate services/packages)

## Constraints
No specific constraints specified; standard Python best practices apply.

## Quality Gate Settings

quality_threshold: 70
# Score 0–100; computed as max(0, 100 − penalty) where each High finding
# costs 10 pts, each Medium costs 3, each Low costs 1.
# Tune this value to adjust how strict the quality gate is.

max_test_fix_attempts: 2
# Maximum number of fix-and-rerun cycles for the test gate before stopping.
# When the limit is reached the agent must stop, report the remaining
# failures, and NOT push. The human reviewer decides what to do next.

## Structure (target)
```
hudukaata/
  indexer/       # indexing job(s)
  search/        # search server
  .kdevkit/      # dev workflow metadata
```

## Dev Environments

`flake.nix` at the repo root is the single source of truth for all dev
environments. Each sub-package has a named devShell that provides system tools
(ffmpeg, rclone) and auto-installs Python dependencies via a `shellHook`.

### Desktop / laptop (direnv auto-activation)

Each sub-package folder ships an `.envrc` that activates the correct shell
automatically when you `cd` into it.

One-time machine setup:
```bash
nix profile install nixpkgs#direnv nixpkgs#nix-direnv
echo 'eval "$(direnv hook bash)"' >> ~/.bashrc   # or zsh
```

One-time per clone, per package:
```bash
cd indexer && direnv allow
```

After that, `cd indexer` loads the indexer environment; `cd search` (future)
loads the search environment. No manual invocation needed.

### Cloud / CI (explicit setup step)

Do not rely on direnv. Run the setup command as the first explicit step:
```bash
nix develop .#indexer --command bash -c "echo env ready"
```
Then run quality, lint, and test commands as subsequent steps, each wrapped in
`nix develop .#indexer --command bash -c "..."`.

### Manual activation (fallback for any context)

| Package   | Command                  |
|-----------|--------------------------|
| indexer   | `nix develop .#indexer`  |
