"""Search server configuration — loaded from environment variables."""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the search server.

    All fields can be set via environment variables with the ``SEARCH_`` prefix.
    Example::

        SEARCH_STORE=file:///data/mystore SEARCH_PORT=8080 python -m search
    """

    model_config = SettingsConfigDict(env_prefix="SEARCH_")

    store: str
    """Store URI pointing to the directory that contains the ``db/`` index.

    Accepted formats:
    - ``file:///absolute/path``
    - ``rclone:remote-name:///path/on/remote``
    """

    port: int = 8080
    top_k: int = 5
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("store")
    @classmethod
    def store_must_be_valid_uri(cls, v: str) -> str:
        # Validate the URI format early so errors surface at startup, not on
        # first request.
        from common.pointer import StorePointer

        StorePointer.parse(v)  # raises ValueError on invalid URI
        return v

    @field_validator("top_k")
    @classmethod
    def top_k_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"top_k must be >= 1, got {v}")
        return v
