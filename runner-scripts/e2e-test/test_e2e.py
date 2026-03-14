"""End-to-end test for the hudukaata runner scripts — two-phase incremental index.

Runs the three runner scripts (index.sh, search.sh, webapp.sh) and checks that
the pipeline works end-to-end.  This is not a package unit test; it exercises
the scripts as a user would.

Phase 1: index subdir_a/ only
  - folder scoping works: results are limited to subdir_a
Phase 2: incrementally index subdir_b/ into the same store
  - incremental update is applied: all 3 files appear in search
  - subdir_a data is not lost

Run:
    pytest runner-scripts/e2e-test/test_e2e.py -v

Requires: nix with flakes enabled.
"""

import json
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import httpx
import pytest

SCRIPT_DIR = Path(__file__).parent
RUNNERS = SCRIPT_DIR.parent
REPO = RUNNERS.parent
SAMPLES = SCRIPT_DIR / "samples"

SEARCH_PORT = 18080
WEBAPP_PORT = 15173

# Shared between phases — set up once in setup_module, cleaned up in teardown_module.
_tmpdir: tempfile.TemporaryDirectory | None = None
WORK_DIR: Path = Path()
MEDIA_DIR: Path = Path()
STORE_DIR: Path = Path()


def setup_module() -> None:
    global _tmpdir, WORK_DIR, MEDIA_DIR, STORE_DIR

    _tmpdir = tempfile.TemporaryDirectory(prefix="hudukaata-e2e-")
    WORK_DIR = Path(_tmpdir.name)
    MEDIA_DIR = WORK_DIR / "media"
    STORE_DIR = WORK_DIR / "store"

    (MEDIA_DIR / "subdir_a").mkdir(parents=True)
    (MEDIA_DIR / "subdir_b").mkdir(parents=True)
    STORE_DIR.mkdir()

    # subdir_a: the two sample images bundled with the test
    shutil.copy(SAMPLES / "blue_sky.png",    MEDIA_DIR / "subdir_a")
    shutil.copy(SAMPLES / "green_field.png", MEDIA_DIR / "subdir_a")

    # subdir_b: a synthetic image generated at runtime via PIL inside the
    # indexer nix shell — no binary asset committed to the repo
    print("\n==> Generating subdir_b/red_sunset.png...")
    subprocess.run(
        [
            "nix", "develop", f"{REPO}#indexer", "--command",
            "python3", "-c",
            "from PIL import Image; "
            f"Image.new('RGB', (64,64), (200,80,30))"
            f".save('{MEDIA_DIR}/subdir_b/red_sunset.png')",
        ],
        check=True,
    )


def teardown_module() -> None:
    if _tmpdir is not None:
        _tmpdir.cleanup()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_conf(path: Path, folder: str = "") -> None:
    lines = [
        f"media           = file://{MEDIA_DIR}",
        f"store           = file://{STORE_DIR}",
        "caption_model   = blip2",
        "vectorizer      = sentence-transformer",
        "vector_store    = chroma",
        "log_level       = INFO",
        f"search_port     = {SEARCH_PORT}",
        "search_api_host = http://localhost",
        f"webapp_port     = {WEBAPP_PORT}",
    ]
    if folder:
        lines.append(f"folder          = {folder}")
    path.write_text("\n".join(lines) + "\n")


def wait_until_ready(url: str, label: str, proc: subprocess.Popen, timeout: int = 3600) -> None:
    """Poll url until it responds 200, the process exits, or timeout is reached.

    A large default timeout is intentional: on first run, nix develop sets up
    the venv and downloads model weights before the server even starts.
    """
    print(f"\nWaiting for {label} (up to {timeout}s)...", flush=True)
    for elapsed in range(timeout):
        try:
            httpx.get(url, timeout=5).raise_for_status()
            print(f"{label} ready ({elapsed}s)", flush=True)
            return
        except Exception:
            pass
        if proc.poll() is not None:
            raise RuntimeError(f"{label} exited unexpectedly after {elapsed}s")
        if elapsed > 0 and elapsed % 30 == 0:
            print(f"  still waiting for {label} ({elapsed}s)...", flush=True)
        time.sleep(1)
    raise TimeoutError(f"{label} timed out after {timeout}s")


@contextmanager
def running_services(conf: Path) -> Generator[httpx.Client, None, None]:
    """Start search API and webapp, yield an httpx client, stop both on exit."""
    search_log = Path("/tmp/hudukaata-search.log")
    webapp_log = Path("/tmp/hudukaata-webapp.log")
    procs: list[subprocess.Popen] = []

    try:
        sp = subprocess.Popen(
            [str(RUNNERS / "search.sh"), str(conf)],
            stdout=search_log.open("w"), stderr=subprocess.STDOUT,
        )
        procs.append(sp)
        try:
            wait_until_ready(f"http://localhost:{SEARCH_PORT}/readyz", "search API", sp)
        except Exception:
            print("--- search log ---\n" + search_log.read_text())
            raise

        wp = subprocess.Popen(
            [str(RUNNERS / "webapp.sh"), str(conf)],
            stdout=webapp_log.open("w"), stderr=subprocess.STDOUT,
        )
        procs.append(wp)
        try:
            wait_until_ready(f"http://localhost:{WEBAPP_PORT}", "webapp", wp)
        except Exception:
            print("--- webapp log ---\n" + webapp_log.read_text())
            raise

        with httpx.Client() as client:
            yield client

    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        time.sleep(1)  # allow ports to be released before the next start


# ---------------------------------------------------------------------------
# Phase 1: run index.sh scoped to subdir_a; verify search is scoped correctly
# ---------------------------------------------------------------------------


def test_phase1_subdir_a() -> None:
    conf = WORK_DIR / "phase1.conf"
    write_conf(conf, folder="subdir_a")

    print("\n==> [Phase 1] Running index.sh for subdir_a...")
    subprocess.run([str(RUNNERS / "index.sh"), str(conf)], check=True)

    with running_services(conf) as client:
        # webapp serves HTML
        resp = client.get(f"http://localhost:{WEBAPP_PORT}/")
        assert resp.status_code == 200
        assert "<html" in resp.text.lower()

        # search returns results — all from subdir_a (folder scoping is working)
        resp = client.get(f"http://localhost:{WEBAPP_PORT}/api/search?q=blue+sky&n=5")
        resp.raise_for_status()
        results: list[dict] = resp.json()
        paths = [r["relative_path"] for r in results]
        assert len(results) >= 1, f"expected >= 1 result, got: {results}"
        assert all("subdir_a" in p for p in paths), f"unexpected paths in phase 1: {paths}"
        assert not any("subdir_b" in p for p in paths), f"subdir_b appeared before it was indexed: {paths}"


# ---------------------------------------------------------------------------
# Phase 2: run index.sh scoped to subdir_b (incremental); verify both subdirs
# ---------------------------------------------------------------------------


def test_phase2_subdir_b_incremental() -> None:
    conf = WORK_DIR / "phase2.conf"
    write_conf(conf, folder="subdir_b")

    print("\n==> [Phase 2] Running index.sh for subdir_b (incremental)...")
    subprocess.run([str(RUNNERS / "index.sh"), str(conf)], check=True)

    with running_services(conf) as client:
        # webapp still serves HTML
        resp = client.get(f"http://localhost:{WEBAPP_PORT}/")
        assert resp.status_code == 200
        assert "<html" in resp.text.lower()

        # all 3 files (2 from subdir_a + 1 from subdir_b) are searchable
        resp = client.get(f"http://localhost:{WEBAPP_PORT}/api/search?q=outdoor&n=10")
        resp.raise_for_status()
        results = resp.json()
        paths = [r["relative_path"] for r in results]
        assert len(results) >= 3, f"expected >= 3 results after incremental update, got: {results}"

        # subdir_b path is present — confirms the incremental update was applied
        assert any("subdir_b" in p for p in paths), f"subdir_b missing from results: {paths}"

        # subdir_a path still present — no data was lost
        assert any("subdir_a" in p for p in paths), f"subdir_a lost after phase 2: {paths}"
