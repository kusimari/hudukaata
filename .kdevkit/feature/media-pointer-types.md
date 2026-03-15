# Feature: media-pointer-types

## Requirements

**Problem:** `MediaPointer.scan()` contains a large `if self.scheme == "file": ... else:`
branch that couples filesystem navigation and rclone navigation into one class. The runner
accepts `MediaPointer` specifically even though it only needs `scan()` + `uri`.

**Success criteria:**
- `MediaSource` ABC exposes `uri` and `scan()` only.
- `FileMediaPointer` implements `MediaSource` for local `file://` sources.
- `RcloneMediaPointer` implements `MediaSource` for `rclone:` sources.
- `GoogleColabMediaPointer` implements `MediaSource` for Google Drive in Colab.
- All three concrete classes have the same flat structure — no multiple inheritance.
- Rclone subprocess logic lives in module-level helper functions.
- `MediaPointer.parse()` retained as a backward-compatible factory.
- Runner depends on `MediaSource`, not `MediaPointer`.
- All existing tests pass; new tests cover every new class and code path.

## Design

See `.kdevkit/plans/eventual-imagining-riddle.md` for full class hierarchy and
implementation details.

## Implementation progress

- [x] Feature file created
- [x] Plan approved
- [ ] `pointer.py` refactored
- [ ] `runner.py` updated
- [ ] `pyproject.toml` updated
- [ ] Tests updated
- [ ] Quality + test gates green
- [ ] Pushed to `claude/media-pointer-navigation-SXQPT`
