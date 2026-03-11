"""Tests for Settings config."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from search.config import Settings


class TestSettings:
    def test_defaults(self, monkeypatch) -> None:
        monkeypatch.setenv("SEARCH_STORE", "file:///data/store")
        s = Settings()
        assert s.store == "file:///data/store"
        assert s.port == 8080
        assert s.top_k == 5
        assert s.log_level == "INFO"

    def test_custom_values(self, monkeypatch) -> None:
        monkeypatch.setenv("SEARCH_STORE", "file:///custom")
        monkeypatch.setenv("SEARCH_PORT", "9090")
        monkeypatch.setenv("SEARCH_TOP_K", "10")
        monkeypatch.setenv("SEARCH_LOG_LEVEL", "DEBUG")
        s = Settings()
        assert s.port == 9090
        assert s.top_k == 10
        assert s.log_level == "DEBUG"

    def test_missing_store_raises(self, monkeypatch) -> None:
        # Ensure SEARCH_STORE is not set
        monkeypatch.delenv("SEARCH_STORE", raising=False)
        with pytest.raises(ValidationError):
            Settings()

    def test_invalid_store_uri_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("SEARCH_STORE", "http://not-valid")
        with pytest.raises(ValidationError):
            Settings()

    def test_invalid_log_level_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("SEARCH_STORE", "file:///x")
        monkeypatch.setenv("SEARCH_LOG_LEVEL", "VERBOSE")
        with pytest.raises(ValidationError):
            Settings()

    def test_top_k_zero_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("SEARCH_STORE", "file:///x")
        monkeypatch.setenv("SEARCH_TOP_K", "0")
        with pytest.raises(ValidationError):
            Settings()
