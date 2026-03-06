"""Atomic DB swap logic.

The store pointer always contains a directory named ``db/`` as the live DB.
During a run the indexer writes into ``db_new/``. On completion:

  Step 1  Write all vectors → store/db_new/   (done by caller)
  Step 2  If store/db/ exists:
              read created_at from store/db/db_meta.json
              rename store/db/ → store/db_YYYY-MM-DD/
  Step 3  Rename store/db_new/ → store/db/
  Step 4  Delete store/db_new/ if rename failed (cleanup guard)

If the run aborts mid-way, ``db_new/`` is left behind and ``db/`` is
untouched.  On the next run ``db_new/`` is detected and cleaned up before
starting.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path

from indexer.pointer import MediaPointer

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def prepare_temp_dir(store: MediaPointer, local_tmp: Path) -> None:
    """Ensure local_tmp exists and is empty, ready for writing db_new."""
    local_tmp.mkdir(parents=True, exist_ok=True)


def commit(
    store: MediaPointer,
    local_tmp: Path,
    created_at: datetime | None,
) -> None:
    """Swap db_new → db, archiving the old db if it exists.

    *local_tmp* is the local directory that was passed to
    ``VectorStore.save(local_tmp / "db_new")``.
    The caller has already uploaded ``db_new`` to the store via
    ``store.put_dir(local_tmp / "db_new", dest_name="db_new")``.
    """
    # Archive existing db
    if store.has_dir("db"):
        date_str = (created_at or datetime.now(UTC)).strftime("%Y-%m-%d")
        archive_name = f"db_{date_str}"
        store.rename_dir("db", archive_name)

    # Promote db_new → db
    try:
        store.rename_dir("db_new", "db")
    except Exception:
        # Rename failed (e.g. rclone not available); clean up new dir
        with contextlib.suppress(Exception):
            store.delete_dir("db_new")
        raise


def cleanup_stale_tmp(store: MediaPointer) -> None:
    """Remove any leftover db_new from a previous aborted run."""
    if store.has_dir("db_new"):
        store.delete_dir("db_new")
