# kdevkit Agent Workflow

This document outlines a structured agent workflow for software development, emphasizing project context, feature planning, git discipline, and session management.

## Core Workflow (5 Steps)

**Step 1** establishes project context by reading `.kdevkit/project.md`. If absent, the agent asks for a project description and creates the file.

**Step 1.6** loads dev-loop instructions from `.kdevkit/agent-dev-instructions.md` if available, applying quality and test gates to implementation work.

**Step 1.5** persists standing rules to agent-specific config files (e.g., `CLAUDE.md` for Claude Code) to survive across sessions.

**Step 2** determines the feature being worked on, either from arguments or user input, then loads or creates `.kdevkit/feature/<name>.md` through a structured four-interview process:
- Requirements (problem, user interaction, success criteria)
- Design (technical approach, architecture)
- Testing (validation strategy, test scenarios)
- Implementation (task breakdown, risk mitigation)

**Step 3** applies git conventions: branches as `<type>/<description>`, commits following Conventional Commits format, scope limited to the project, and PR discipline requiring passing builds before opening.

**Step 4** maintains session behavior: updating feature files after each unit of work, gating phases (stopping between them unless YOLO mode is active), presenting assumption plans when ambiguous, and offering to update project metadata upon completion.

**Step 5** confirms readiness with a compact summary before awaiting instruction.

## Key Principles

- **Phase gating:** Never chain phases automatically without explicit user instruction
- **Assumption plans:** Present brief plans for ambiguous inputs; wait for approval
- **YOLO mode:** Keyword "yolo" drops gates and plans; "yolo off" restores normal behavior
- **Commit discipline:** Every commit leaves the repo in a working state; no commented code or secrets
- **Feature file updates:** Record progress continuously, not in batches
