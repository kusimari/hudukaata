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

Output visibility note
----------------------
conftest.py installs a capfd.disabled() autouse fixture, which restores fd 1 to
the real stdout for the duration of every test.  Structured verbose output is
written to a per-test log file (e2e-verbose-<phase>.log inside the temp work dir)
and then dumped to stdout via subprocess.run(["cat", ...]) so that it appears as
a single contiguous block in the CI log, whether the test passes or fails.
"""

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import httpx

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

# Per-test verbose log file — set at the start of each test, dumped at the end.
_LOG_FILE: Path = Path()


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
    shutil.copy(SAMPLES / "blue_sky.png", MEDIA_DIR / "subdir_a")
    shutil.copy(SAMPLES / "green_field.png", MEDIA_DIR / "subdir_a")

    # subdir_b: a synthetic image generated at runtime via PIL inside the
    # indexer nix shell — no binary asset committed to the repo
    print("\n==> Generating subdir_b/red_sunset.png...", flush=True)
    subprocess.run(
        [
            "nix",
            "develop",
            f"{REPO}#indexer",
            "--command",
            "python3",
            "-c",
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
# Verbose log helpers
# ---------------------------------------------------------------------------
# All structured output (store state, API responses) is written to _LOG_FILE via
# _emit().  dump_log() reads the file and dumps it to stdout via subprocess.run
# (["cat", ...]).  Because conftest.py installs capfd.disabled(), fd 1 is the
# real stdout throughout the test, so the cat output is always visible in CI.


def _emit(msg: str) -> None:
    """Append msg to the current test's verbose log file."""
    with _LOG_FILE.open("a") as f:
        f.write(msg + "\n")


def dump_log() -> None:
    """Dump the verbose log file to stdout via cat and print its path.

    Using subprocess.run(["cat"]) rather than print() is the user's explicit
    choice: it writes to the inherited fd 1, making the mechanism independent of
    Python's sys.stdout buffering and explicit about what is happening.
    """
    if not _LOG_FILE.exists() or not _LOG_FILE.stat().st_size:
        return
    print(f"\n{'~' * 72}", flush=True)
    print(f"  Verbose log: {_LOG_FILE}", flush=True)
    print(f"{'~' * 72}", flush=True)
    subprocess.run(["cat", str(_LOG_FILE)], check=False)
    print(f"{'~' * 72}\n", flush=True)


# ---------------------------------------------------------------------------
# Structured output helpers  (write to log file, not directly to stdout)
# ---------------------------------------------------------------------------


def _banner(msg: str) -> None:
    """Write a wide visual separator to the verbose log."""
    width = 72
    _emit(f"\n{'=' * width}")
    _emit(f"  {msg}")
    _emit(f"{'=' * width}")


def print_store_state(label: str) -> None:
    """Walk STORE_DIR and log the file tree, sizes, and index_meta.json."""
    _banner(label)
    _emit(f"Store root: {STORE_DIR}\n")

    all_paths = sorted(STORE_DIR.rglob("*"))
    if not any(p.is_file() for p in all_paths):
        _emit("  (store is empty)")
    else:
        for p in all_paths:
            if p.is_file():
                size = p.stat().st_size
                rel = p.relative_to(STORE_DIR)
                _emit(f"  {rel}  ({size:,} bytes)")

    # index_meta.json records what the indexer wrote (store names, timestamp, version)
    meta_path = STORE_DIR / "db" / "index_meta.json"
    if meta_path.exists():
        _emit("\n  index_meta.json:")
        meta = json.loads(meta_path.read_text())
        for k, v in meta.items():
            _emit(f"    {k}: {v}")
    else:
        _emit("\n  index_meta.json: (not yet created)")


def _log_search_response(label: str, resp: httpx.Response) -> None:
    """Log a JSON search/faces response with a labelled banner."""
    _banner(label)
    _emit(f"  URL    : {resp.url}")
    _emit(f"  Status : {resp.status_code}")
    try:
        data = resp.json()
        _emit(f"  Body   :\n{json.dumps(data, indent=4)}")
    except Exception:
        _emit(f"  Body   : {resp.text[:500]}")


# ---------------------------------------------------------------------------
# Config and service helpers
# ---------------------------------------------------------------------------


def write_conf(path: Path, folder: str = "") -> None:
    lines = [
        f"media           = file://{MEDIA_DIR}",
        f"store           = file://{STORE_DIR}",
        "caption_model   = blip2_faces",
        # Load face store in the search server to match the face-aware indexer.
        "indexer_key     = blip2-sentok-exif-insightface",
        "log_level       = INFO",
        f"search_port     = {SEARCH_PORT}",
        "search_api_host = http://localhost",
        f"webapp_port     = {WEBAPP_PORT}",
    ]
    if folder:
        lines.append(f"folder          = {folder}")
    path.write_text("\n".join(lines) + "\n")


def wait_until_ready(
    url: str, label: str, proc: subprocess.Popen, timeout: int = 3600
) -> None:
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
    search_log = WORK_DIR / "search.log"
    webapp_log = WORK_DIR / "webapp.log"
    procs: list[subprocess.Popen] = []

    try:
        sp = subprocess.Popen(
            [str(RUNNERS / "search.sh"), str(conf)],
            stdout=search_log.open("w"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        procs.append(sp)
        try:
            wait_until_ready(f"http://localhost:{SEARCH_PORT}/readyz", "search API", sp)
        except Exception:
            print("--- search log ---\n" + search_log.read_text(), flush=True)
            raise

        wp = subprocess.Popen(
            [str(RUNNERS / "webapp.sh"), str(conf)],
            stdout=webapp_log.open("w"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        procs.append(wp)
        try:
            wait_until_ready(f"http://localhost:{WEBAPP_PORT}", "webapp", wp)
        except Exception:
            print("--- webapp log ---\n" + webapp_log.read_text(), flush=True)
            raise

        # Use a long timeout: the first search query triggers lazy model loading
        # (sentence-transformer) which can take 30+ seconds on a cold venv.
        with httpx.Client(timeout=300.0) as client:
            yield client

    finally:
        for p in procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for p in procs:
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                p.wait()
        time.sleep(1)  # allow ports to be released before the next start


# ---------------------------------------------------------------------------
# Phase 1: run index.sh scoped to subdir_a; verify search is scoped correctly
# ---------------------------------------------------------------------------


def test_phase1_subdir_a() -> None:
    global _LOG_FILE
    _LOG_FILE = WORK_DIR / "e2e-verbose-phase1.log"
    _LOG_FILE.unlink(missing_ok=True)

    conf = WORK_DIR / "phase1.conf"
    write_conf(conf, folder="subdir_a")

    print("\n==> [Phase 1] Running index.sh for subdir_a...", flush=True)
    subprocess.run([str(RUNNERS / "index.sh"), str(conf)], check=True)

    # -----------------------------------------------------------------------
    # Store inspection — confirm caption + face stores were created
    # -----------------------------------------------------------------------
    print_store_state("Phase 1 store state — after indexing subdir_a")

    with running_services(conf) as client:
        # ------------------------------------------------------------------
        # Search API — direct (port SEARCH_PORT)
        # ------------------------------------------------------------------
        resp_direct = client.get(
            f"http://localhost:{SEARCH_PORT}/search?q=blue+sky&n=5"
        )
        resp_direct.raise_for_status()
        _log_search_response(
            f"Phase 1 — GET /search?q=blue+sky&n=5  (search API, port {SEARCH_PORT})",
            resp_direct,
        )

        # ------------------------------------------------------------------
        # Faces API — direct (port SEARCH_PORT)
        # ------------------------------------------------------------------
        resp_faces = client.get(f"http://localhost:{SEARCH_PORT}/faces?n=10")
        _log_search_response(
            f"Phase 1 — GET /faces?n=10  (search API, port {SEARCH_PORT})",
            resp_faces,
        )

        # ------------------------------------------------------------------
        # Webapp HTML (port WEBAPP_PORT)
        # ------------------------------------------------------------------
        _banner(f"Phase 1 — GET /  (webapp, port {WEBAPP_PORT})")
        resp_html = client.get(f"http://localhost:{WEBAPP_PORT}/")
        _emit(f"  Status : {resp_html.status_code}")
        _emit(f"  Body   : {resp_html.text[:300].replace(chr(10), ' ').strip()}...")

        # ------------------------------------------------------------------
        # Search via webapp proxy (port WEBAPP_PORT → search API)
        # ------------------------------------------------------------------
        resp = client.get(f"http://localhost:{WEBAPP_PORT}/api/search?q=blue+sky&n=5")
        resp.raise_for_status()
        _log_search_response(
            f"Phase 1 — GET /api/search?q=blue+sky&n=5  (webapp proxy, port {WEBAPP_PORT})",
            resp,
        )

        # ------------------------------------------------------------------
        # Dump the verbose log before assertions so it is always visible.
        # subprocess.run(["cat"]) writes to the real fd 1 (restored by
        # capfd.disabled() in conftest.py), bypassing pytest's capture.
        # ------------------------------------------------------------------
        dump_log()

        # ------------------------------------------------------------------
        # Assertions
        # ------------------------------------------------------------------
        assert resp_html.status_code == 200
        assert "<html" in resp_html.text.lower()

        results: list[dict] = resp.json()
        paths = [r["relative_path"] for r in results]
        assert len(results) >= 1, f"expected >= 1 result, got: {results}"
        assert all("subdir_a" in p for p in paths), (
            f"unexpected paths in phase 1: {paths}"
        )
        assert not any("subdir_b" in p for p in paths), (
            f"subdir_b appeared before it was indexed: {paths}"
        )


# ---------------------------------------------------------------------------
# Phase 2: run index.sh scoped to subdir_b (incremental); verify both subdirs
# ---------------------------------------------------------------------------


def test_phase2_subdir_b_incremental() -> None:
    global _LOG_FILE
    _LOG_FILE = WORK_DIR / "e2e-verbose-phase2.log"
    _LOG_FILE.unlink(missing_ok=True)

    conf = WORK_DIR / "phase2.conf"
    write_conf(conf, folder="subdir_b")

    print("\n==> [Phase 2] Running index.sh for subdir_b (incremental)...", flush=True)
    subprocess.run([str(RUNNERS / "index.sh"), str(conf)], check=True)

    # -----------------------------------------------------------------------
    # Store inspection — confirm stores were updated (same files, newer data)
    # -----------------------------------------------------------------------
    print_store_state("Phase 2 store state — after incremental index of subdir_b")

    with running_services(conf) as client:
        # ------------------------------------------------------------------
        # Search API — direct, broad query to surface all 3 files
        # ------------------------------------------------------------------
        resp_direct = client.get(
            f"http://localhost:{SEARCH_PORT}/search?q=outdoor&n=10"
        )
        resp_direct.raise_for_status()
        _log_search_response(
            f"Phase 2 — GET /search?q=outdoor&n=10  (search API, port {SEARCH_PORT})",
            resp_direct,
        )

        # ------------------------------------------------------------------
        # Faces API — should now reflect images from both subdirs
        # ------------------------------------------------------------------
        resp_faces = client.get(f"http://localhost:{SEARCH_PORT}/faces?n=10")
        _log_search_response(
            f"Phase 2 — GET /faces?n=10  (search API, port {SEARCH_PORT})",
            resp_faces,
        )

        # ------------------------------------------------------------------
        # Webapp HTML
        # ------------------------------------------------------------------
        _banner(f"Phase 2 — GET /  (webapp, port {WEBAPP_PORT})")
        resp_html = client.get(f"http://localhost:{WEBAPP_PORT}/")
        _emit(f"  Status : {resp_html.status_code}")
        _emit(f"  Body   : {resp_html.text[:300].replace(chr(10), ' ').strip()}...")

        # ------------------------------------------------------------------
        # Search via webapp proxy
        # ------------------------------------------------------------------
        resp = client.get(f"http://localhost:{WEBAPP_PORT}/api/search?q=outdoor&n=10")
        resp.raise_for_status()
        _log_search_response(
            f"Phase 2 — GET /api/search?q=outdoor&n=10  (webapp proxy, port {WEBAPP_PORT})",
            resp,
        )

        # ------------------------------------------------------------------
        # Dump the verbose log before assertions.
        # ------------------------------------------------------------------
        dump_log()

        # ------------------------------------------------------------------
        # Assertions
        # ------------------------------------------------------------------
        assert resp_html.status_code == 200
        assert "<html" in resp_html.text.lower()

        results = resp.json()
        paths = [r["relative_path"] for r in results]
        assert len(results) >= 3, (
            f"expected >= 3 results after incremental update, got: {results}"
        )

        # subdir_b path is present — confirms the incremental update was applied
        assert any("subdir_b" in p for p in paths), (
            f"subdir_b missing from results: {paths}"
        )

        # subdir_a path still present — no data was lost
        assert any("subdir_a" in p for p in paths), (
            f"subdir_a lost after phase 2: {paths}"
        )
