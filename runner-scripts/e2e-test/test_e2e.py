"""End-to-end integration test — two-phase incremental index.

Phase 1: index subdir_a/ (blue_sky.png + green_field.png)
  - verify webapp serves HTML
  - verify search returns only subdir_a results (folder scoping works)

Phase 2: incrementally index subdir_b/ (red_sunset.png, generated at runtime)
  - verify all 3 files are searchable (incremental update applied)
  - verify subdir_b path appears in results
  - verify subdir_a path still present (no data loss)

Run:
    pytest runner-scripts/e2e-test/test_e2e.py -v

Requires: nix with flakes enabled.
"""

import json
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from io import TextIOWrapper
from pathlib import Path
from typing import Generator

import pytest

SCRIPT_DIR = Path(__file__).parent
RUNNERS = SCRIPT_DIR.parent
REPO = RUNNERS.parent
SAMPLES = SCRIPT_DIR / "samples"

SEARCH_PORT = 18080
WEBAPP_PORT = 15173


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_conf(path: Path, media_dir: Path, store_dir: Path, folder: str = "") -> None:
    lines = [
        f"media           = file://{media_dir}",
        f"store           = file://{store_dir}",
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


def wait_for_http(url: str, label: str, proc: subprocess.Popen, timeout: int = 300) -> None:
    for elapsed in range(timeout):
        try:
            urllib.request.urlopen(url, timeout=2)
            print(f"\n{label} ready ({elapsed}s)")
            return
        except Exception:
            pass
        if proc.poll() is not None:
            raise RuntimeError(f"{label} process exited unexpectedly after {elapsed}s")
        print(".", end="", flush=True)
        time.sleep(1)
    raise TimeoutError(f"{label} timed out after {timeout}s")


def search_results(query: str, n: int = 5) -> list[dict]:
    url = f"http://localhost:{WEBAPP_PORT}/api/search?q={query}&n={n}"
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())  # type: ignore[no-any-return]


@contextmanager
def running_services(conf: Path) -> Generator[None, None, None]:
    """Start search API and webapp; stop them on exit."""
    search_log_path = Path("/tmp/hudukaata-search.log")
    webapp_log_path = Path("/tmp/hudukaata-webapp.log")
    log_handles: list[TextIOWrapper] = []
    procs: list[subprocess.Popen] = []

    try:
        search_fh = search_log_path.open("w")
        log_handles.append(search_fh)
        sp = subprocess.Popen(
            [str(RUNNERS / "search.sh"), str(conf)],
            stdout=search_fh,
            stderr=subprocess.STDOUT,
        )
        procs.append(sp)
        try:
            wait_for_http(f"http://localhost:{SEARCH_PORT}/readyz", "search API", sp)
        except Exception:
            print("--- search log ---\n" + search_log_path.read_text())
            raise

        webapp_fh = webapp_log_path.open("w")
        log_handles.append(webapp_fh)
        wp = subprocess.Popen(
            [str(RUNNERS / "webapp.sh"), str(conf)],
            stdout=webapp_fh,
            stderr=subprocess.STDOUT,
        )
        procs.append(wp)
        try:
            wait_for_http(f"http://localhost:{WEBAPP_PORT}", "webapp", wp)
        except Exception:
            print("--- webapp log ---\n" + webapp_log_path.read_text())
            raise

        yield
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        for fh in log_handles:
            fh.close()
        time.sleep(1)  # allow OS to release ports before the next start


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Set up media dirs, generate synthetic image, write both conf files."""
    import shutil

    work = tmp_path_factory.mktemp("hudukaata-e2e")
    media = work / "media"
    store = work / "store"
    (media / "subdir_a").mkdir(parents=True)
    (media / "subdir_b").mkdir(parents=True)
    store.mkdir()

    # subdir_a: two bundled sample images
    shutil.copy(SAMPLES / "blue_sky.png", media / "subdir_a")
    shutil.copy(SAMPLES / "green_field.png", media / "subdir_a")

    # subdir_b: synthetic orange-red image — generated inside the indexer nix
    # shell so PIL is guaranteed to be available; no binary asset committed.
    print("\n==> Generating subdir_b/red_sunset.png via PIL...")
    subprocess.run(
        [
            "nix",
            "develop",
            f"{REPO}#indexer",
            "--command",
            "python3",
            "-c",
            (
                "from PIL import Image; "
                f"Image.new('RGB', (64, 64), (200, 80, 30))"
                f".save('{media}/subdir_b/red_sunset.png')"
            ),
        ],
        check=True,
    )

    conf_a = work / "conf_a.conf"
    conf_b = work / "conf_b.conf"
    write_conf(conf_a, media, store, folder="subdir_a")
    write_conf(conf_b, media, store, folder="subdir_b")

    return {"work": work, "media": media, "store": store, "conf_a": conf_a, "conf_b": conf_b}


@pytest.fixture(scope="module")
def phase1_indexed(env: dict) -> dict:
    """Run the indexer scoped to subdir_a (2 files)."""
    print("\n==> [Phase 1] Indexing subdir_a...")
    subprocess.run([str(RUNNERS / "index.sh"), str(env["conf_a"])], check=True)
    return env


@pytest.fixture(scope="module")
def phase2_indexed(phase1_indexed: dict) -> dict:
    """Incrementally index subdir_b (1 new file) on top of the phase-1 store."""
    print("\n==> [Phase 2] Incrementally indexing subdir_b...")
    subprocess.run([str(RUNNERS / "index.sh"), str(phase1_indexed["conf_b"])], check=True)
    return phase1_indexed


# ---------------------------------------------------------------------------
# Phase 1: only subdir_a is indexed
# ---------------------------------------------------------------------------


def test_phase1_webapp_serves_html(phase1_indexed: dict) -> None:
    """Webapp returns an HTML document after phase-1 index."""
    with running_services(phase1_indexed["conf_a"]):
        html = urllib.request.urlopen(f"http://localhost:{WEBAPP_PORT}").read().decode()
        assert "<html" in html.lower(), f"expected HTML, got: {html[:200]}"


def test_phase1_search_scoped_to_subdir_a(phase1_indexed: dict) -> None:
    """Search returns results from subdir_a only — folder scoping is working."""
    with running_services(phase1_indexed["conf_a"]):
        results = search_results("blue sky")
        assert len(results) >= 1, f"expected >= 1 result, got: {results}"
        paths = [r["relative_path"] for r in results]
        assert all(
            "subdir_a" in p for p in paths
        ), f"phase 1 results should only contain subdir_a paths, got: {paths}"
        assert not any(
            "subdir_b" in p for p in paths
        ), f"subdir_b should not appear before it is indexed, got: {paths}"


# ---------------------------------------------------------------------------
# Phase 2: subdir_b incrementally added; both subdirs must be present
# ---------------------------------------------------------------------------


def test_phase2_webapp_serves_html(phase2_indexed: dict) -> None:
    """Webapp still returns HTML after the incremental update."""
    with running_services(phase2_indexed["conf_b"]):
        html = urllib.request.urlopen(f"http://localhost:{WEBAPP_PORT}").read().decode()
        assert "<html" in html.lower(), f"expected HTML, got: {html[:200]}"


def test_phase2_all_three_files_searchable(phase2_indexed: dict) -> None:
    """After the incremental update, all 3 indexed files are returned by search."""
    with running_services(phase2_indexed["conf_b"]):
        results = search_results("outdoor", n=10)
        assert len(results) >= 3, (
            f"expected >= 3 results (2 from subdir_a + 1 from subdir_b), got: {results}"
        )


def test_phase2_subdir_b_path_present(phase2_indexed: dict) -> None:
    """A result with a subdir_b path confirms the incremental update was applied."""
    with running_services(phase2_indexed["conf_b"]):
        results = search_results("sunset", n=10)
        paths = [r["relative_path"] for r in results]
        assert any(
            "subdir_b" in p for p in paths
        ), f"expected a subdir_b path in results, got: {paths}"


def test_phase2_subdir_a_still_present(phase2_indexed: dict) -> None:
    """subdir_a files are still searchable after indexing subdir_b (no data loss)."""
    with running_services(phase2_indexed["conf_b"]):
        results = search_results("blue sky", n=10)
        paths = [r["relative_path"] for r in results]
        assert any(
            "subdir_a" in p for p in paths
        ), f"subdir_a paths missing after phase 2 — possible data loss: {paths}"
