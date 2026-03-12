# Feature: end-to-end-scaffold

## Requirements

- Users can git clone the repo, fill in one config file, and run each service with a single command
- No dependency installation required beyond Nix
- Three runners: index (build the vector index), search (start the API), webapp (start the browser UI)
- All runner inputs come from a single `hudukaata.conf` config file
- Config file path can be overridden as a script argument
- Scripts work from any directory (no reliance on cwd or git)

## Design

- Shell scripts in `runner-scripts/` — no new Python package
- `hudukaata.conf` is a simple `key = value` file (no sections, `#` comments)
- Each script resolves the repo root relative to its own location (`$(dirname "$0")/..`)
- Scripts wrap the existing package CLIs inside `nix develop .#<package> --command bash -c "..."`
- Nix is installed via Determinate Systems installer (flakes enabled by default)

## Implementation

- [x] `runner-scripts/hudukaata.conf.example` — config template
- [x] `runner-scripts/index.sh` — runs `indexer index` inside nix indexer devShell
- [x] `runner-scripts/search.sh` — runs `python -m search` inside nix search devShell
- [x] `runner-scripts/webapp.sh` — runs `npm run dev` inside nix webapp devShell
- [x] `README.md` — quick start guide with Determinate Nix install instructions
- [x] `.gitignore` updated — `runner-scripts/hudukaata.conf` ignored
- [x] GitHub issues filed for 5 future todos

## Status

Complete. Branch: `claude/e2e-feature-scaffold-15UkE`
