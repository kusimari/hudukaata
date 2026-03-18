# hudukaata

- **Understand the project:** Read `.kdevkit/project.md`.
- **Any change request** (feature, fix, or user-asked change): follow `.kdevkit/feature-dev.md`.
  **Never write code before the feature file exists and the plan has been approved.**
- **Implementation:** Delegate to a sub-agent. Provide it the approved plan and instruct it
  to follow `.kdevkit/agent-dev-loop.md` exactly.
- **After the sub-agent returns:** run all in-scope package tests on the feature branch.
  - If any test fails: re-spawn the sub-agent with the original ask + failure output.
  - Retry until tests pass (respecting `max_test_fix_attempts` from `project.md`).
- **When tests pass:** push the feature branch with a squash-merge summary commit
  (format defined in `agent-dev-loop.md § Squash merge summary`).
