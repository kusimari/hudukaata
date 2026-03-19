"""Pytest configuration for the e2e test suite.

Why capfd.disabled():
  pytest's default --capture=fd mode replaces file descriptor 1 at the OS level
  (via dup2) before each test. This means both print() and subprocess writes to
  stdout are silently captured and only shown on test failure.

  capfd.disabled() temporarily restores fd 1 to the real (pre-capture) stdout for
  the duration of the test. Both Python print() calls and child-process stdout
  (e.g. subprocess.run(["cat", ...])) then go directly to the terminal / CI log,
  whether the test passes or fails.
"""

import pytest


@pytest.fixture(autouse=True)
def show_output(capfd):
    """Disable pytest's fd-level stdout capture so verbose e2e output is always visible."""
    with capfd.disabled():
        yield
