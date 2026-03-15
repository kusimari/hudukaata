"""Tests for the /search, /healthz, and /readyz endpoints."""

from __future__ import annotations

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
