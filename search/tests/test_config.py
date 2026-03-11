"""Tests for Settings config."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from search.config import Settings


class TestSettings:
    def test_defaults(self) -> None:
        s = Settings(store="file:///data/store")
        assert s.store == "file:///data/store"
        assert s.port == 8080
        assert s.top_k == 5
        assert s.log_level == "INFO"

    def test_custom_values(self) -> None:
        s = Settings(store="file:///custom", port=9090, top_k=10, log_level="DEBUG")
        assert s.port == 9090
        assert s.top_k == 10
        assert s.log_level == "DEBUG"

    def test_missing_store_raises(self) -> None:
        with pytest.raises(ValidationError):
            Settings()

    def test_invalid_store_uri_raises(self) -> None:
        with pytest.raises(ValidationError):
            Settings(store="http://not-valid")

    def test_invalid_log_level_raises(self) -> None:
        with pytest.raises(ValidationError):
            Settings(store="file:///x", log_level="VERBOSE")

    def test_top_k_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            Settings(store="file:///x", top_k=0)
