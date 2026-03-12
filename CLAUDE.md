# hudukaata

- **Understand the project:** Read `.kdevkit/project.md`.
- **Working on a feature:** Follow `.kdevkit/feature-dev.md`.
- **Making any code change:** Follow `.kdevkit/agent-dev-instructions.md`. This is mandatory.

## Scope rule for the dev loop

When any package is changed, run the full dev loop (setup → quality → test → push)
for **that package and every package that depends on it**.

The dependency map lives in `.kdevkit/agent-dev-instructions.md`. Short version:
- Change `common` → loop `common`, `indexer`, `search`
- Change `indexer` → loop `indexer`
- Change `search` → loop `search`
- Change `webapp` → loop `webapp`
- Change `flake.nix` → loop every package whose devShell was modified
