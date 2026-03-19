# Feature: modify-kdevkit

## Status

`ready-for-merge`

## Requirements

Clean up `.kdevkit` so files are minimal, MECE, and reusable:
- `feature-dev.md`, `agent-dev-loop.md`, `review.md` must be generic (zero project-specific content)
- `project.md` is the single source for all project-specific config, commands, and constraints
- `CLAUDE.md` (and equivalents) is minimal constant memory: 3 mandatory rules only

## Design

**Generic files (portable to any project):**
- `outerspace-loop.md` — 3-phase feature workflow (plan → implement → human review)
- `innerspace-loop.md` — Phase 2 loop (setup → code → quality → test → auto-review → human-ready) + git prefix conventions
- `review.md` — incremental and PR review criteria, severity definitions, output format

**Project-specific:**
- `project.md` — structure, stack, package status, dev commands, dependency map, quality settings, per-package review constraints, testing rules

**Constant memory:**
- `CLAUDE.md` — 3 mandatory pointers only (no dependency map; that lives in project.md)

**Deleted:** `agent-dev-instructions.md`, `review-prompt.md`, `pr-review-prompt.md`

## Plan

1. Create this feature log
2. plan: commit
3. Rewrite feature-dev.md
4. Create agent-dev-loop.md
5. Create review.md
6. Expand project.md
7. Simplify CLAUDE.md
8. Delete old files
9. dev: commit + push
