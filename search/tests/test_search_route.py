"""Tests for the /search, /faces, /healthz, /readyz, and /media endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from common.index import FaceItem, IndexResult
from common.media import FileMediaSource
from fastapi.testclient import TestClient

from search.app import app
from search.startup import AppState
from tests.stubs.index_store import StubIndexStore


def _make_state(results: list[dict[str, str]] | None = None, top_k: int = 5) -> AppState:
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

    def test_face_ids_filter_restricts_results(self) -> None:
        """face_ids param filters search results to matching images."""
        face_store_mock = MagicMock()
        face_store_mock.get_metadata.return_value = {
            "image_paths": "img1.jpg,img2.jpg",
            "count": "2",
            "representative_path": "img1.jpg",
        }

        results = [
            {"id": "img1.jpg", "caption": "a person", "relative_path": "img1.jpg"},
            {"id": "img3.jpg", "caption": "a dog", "relative_path": "img3.jpg"},
        ]
        state = AppState(
            index_store=StubIndexStore(results=results),
            face_store=face_store_mock,
            top_k=5,
            media_src=FileMediaSource(path="/media"),
        )
        app.state.ctx = state
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.get("/search?q=person&face_ids=cluster-1")
        assert resp.status_code == 200
        items = resp.json()
        # Only img1.jpg is in the face cluster's image_paths
        assert len(items) == 1
        assert items[0]["relative_path"] == "img1.jpg"

    def test_face_ids_ignored_when_no_face_store(self) -> None:
        """face_ids param is silently ignored when face store not loaded."""
        results = [
            {"id": "img1.jpg", "caption": "a person", "relative_path": "img1.jpg"},
        ]
        state = _make_state(results=results)
        app.state.ctx = state
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.get("/search?q=person&face_ids=cluster-1")
        assert resp.status_code == 200
        # Returns all results (filter skipped due to no face_store)
        assert len(resp.json()) == 1


class TestFacesEndpoint:
    def test_returns_404_when_no_face_store(self, client: TestClient) -> None:
        resp = client.get("/faces")
        assert resp.status_code == 404

    def test_returns_face_clusters(self) -> None:
        face_store_mock = MagicMock()
        face_store_mock.list_all.return_value = [
            IndexResult(
                id="cluster-1",
                relative_path="img1.jpg",
                item=FaceItem(embedding=[0.1] * 4, cluster_id="cluster-1"),
                score=1.0,
                extra={"count": "5", "image_paths": "img1.jpg,img2.jpg"},
            )
        ]
        state = AppState(
            index_store=StubIndexStore(),
            face_store=face_store_mock,
            top_k=5,
            media_src=FileMediaSource(path="/media"),
        )
        app.state.ctx = state
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.get("/faces")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["cluster_id"] == "cluster-1"
        assert data[0]["count"] == 5
        assert data[0]["representative_path"] == "img1.jpg"

    def test_n_parameter_limits_face_results(self) -> None:
        face_store_mock = MagicMock()
        face_store_mock.list_all.return_value = []
        state = AppState(
            index_store=StubIndexStore(),
            face_store=face_store_mock,
            top_k=5,
            media_src=FileMediaSource(path="/media"),
        )
        app.state.ctx = state
        c = TestClient(app, raise_server_exceptions=True)
        c.get("/faces?n=2")
        face_store_mock.list_all.assert_called_once_with(2)


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
