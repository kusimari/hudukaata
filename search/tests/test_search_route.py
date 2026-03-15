"""Tests for the /search, /healthz, /readyz, and /media endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from common.media import FileMediaSource
from fastapi.testclient import TestClient

from search.app import app
from search.startup import AppState
from tests.stubs.index_store import StubIndexStore


def _make_state(results: list[dict[str, Any]] | None = None, top_k: int = 5) -> AppState:
    return AppState(
        index_store=StubIndexStore(results=results),
        top_k=top_k,
        media_src=FileMediaSource(path="/media"),
    )


@pytest.fixture()
def client(stub_state: AppState) -> TestClient:
    """Test client with lifespan bypassed — AppState injected directly."""
    app.state.ctx = stub_state
    return TestClient(app, raise_server_exceptions=True)


class TestHealthz:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_returns_ok_body(self, client: TestClient) -> None:
        resp = client.get("/healthz")
        assert resp.json() == {"status": "ok"}


class TestSearchEndpoint:
    def test_empty_query_returns_422(self, client: TestClient) -> None:
        resp = client.get("/search?q=")
        assert resp.status_code == 422

    def test_valid_query_returns_list(self, client: TestClient) -> None:
        resp = client.get("/search?q=sunset")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_results_have_required_fields(self) -> None:
        results = [
            {"id": "photo.jpg", "caption": "a sunset", "relative_path": "photo.jpg"},
        ]
        state = _make_state(results=results)
        app.state.ctx = state
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.get("/search?q=sunset")
        assert resp.status_code == 200
        item = resp.json()[0]
        assert item["id"] == "photo.jpg"
        assert item["caption"] == "a sunset"
        assert item["relative_path"] == "photo.jpg"

    def test_n_parameter_limits_results(self) -> None:
        results = [
            {"id": f"img_{i}.jpg", "caption": f"caption {i}", "relative_path": f"img_{i}.jpg"}
            for i in range(10)
        ]
        state = _make_state(results=results, top_k=10)
        app.state.ctx = state
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.get("/search?q=test&n=2")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_extra_metadata_preserved(self) -> None:
        results = [
            {
                "id": "img.jpg",
                "caption": "a cat",
                "relative_path": "img.jpg",
                "width": "1920",
                "height": "1080",
            }
        ]
        state = _make_state(results=results)
        app.state.ctx = state
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.get("/search?q=cat")
        item = resp.json()[0]
        assert item["extra"]["width"] == "1920"
        assert item["extra"]["height"] == "1080"

    def test_whitespace_only_query_returns_422(self, client: TestClient) -> None:
        resp = client.get("/search?q=   ")
        assert resp.status_code == 422


class TestReadyz:
    def test_returns_200_when_index_loaded(self, client: TestClient) -> None:
        resp = client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}

    def test_returns_503_when_index_not_loaded(self) -> None:
        """Readiness probe must return 503 before load() completes."""
        app.state.ctx = None
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/readyz")
        assert resp.status_code == 503


class TestMediaEndpoint:
    def _client_with_media(self, media_root: Path) -> TestClient:
        state = AppState(
            index_store=StubIndexStore(),
            top_k=5,
            media_src=FileMediaSource(path=str(media_root)),
        )
        app.state.ctx = state
        return TestClient(app, raise_server_exceptions=False)

    def test_encoded_slash_traversal_rejected(self, tmp_path: Path) -> None:
        # %2f-encoded slashes combined with dots can bypass naive dot checks.
        c = self._client_with_media(tmp_path)
        resp = c.get("/media/subdir%2F..%2Fetc%2Fpasswd")
        assert resp.status_code == 400

    def test_percent_encoded_traversal_rejected(self, tmp_path: Path) -> None:
        c = self._client_with_media(tmp_path)
        resp = c.get("/media/%2e%2e/secret")
        assert resp.status_code == 400

    def test_missing_file_returns_404(self, tmp_path: Path) -> None:
        c = self._client_with_media(tmp_path)
        resp = c.get("/media/nonexistent.jpg")
        assert resp.status_code == 404

    def test_existing_file_returns_200(self, tmp_path: Path) -> None:
        (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8\xff")
        c = self._client_with_media(tmp_path)
        resp = c.get("/media/photo.jpg")
        assert resp.status_code == 200
        assert resp.content == b"\xff\xd8\xff"

    def test_correct_content_type_returned(self, tmp_path: Path) -> None:
        (tmp_path / "clip.mp4").write_bytes(b"\x00\x00\x00\x00")
        c = self._client_with_media(tmp_path)
        resp = c.get("/media/clip.mp4")
        assert resp.status_code == 200
        assert "video/mp4" in resp.headers["content-type"]
