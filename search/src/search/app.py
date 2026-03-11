"""FastAPI application — search endpoint and health check."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from search.config import Settings
from search.startup import AppState, load

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = Settings()
    app.state.ctx = load(settings)
    yield
    # Clean up rclone-downloaded DB directory on shutdown.
    ctx: AppState = app.state.ctx
    ctx.cleanup()


app = FastAPI(
    title="hudukaata search",
    description="Semantic search over the media index.",
    version="0.1.0",
    lifespan=lifespan,
)


class SearchResult(BaseModel):
    """A single result returned by the search endpoint."""

    id: str
    caption: str = ""
    relative_path: str = ""
    extra: dict[str, str] = Field(default_factory=dict)


def _to_result(raw: dict[str, Any]) -> SearchResult:
    known = {"id", "caption", "relative_path"}
    extra = {k: str(v) for k, v in raw.items() if k not in known}
    return SearchResult(
        id=str(raw.get("id", "")),
        caption=str(raw.get("caption", "")),
        relative_path=str(raw.get("relative_path", "")),
        extra=extra,
    )


def _get_ctx() -> AppState:
    """Return the AppState, raising 503 if startup did not complete."""
    ctx: AppState | None = getattr(app.state, "ctx", None)
    if ctx is None:
        raise HTTPException(status_code=503, detail="Server not ready; index not loaded.")
    return ctx


@app.get("/search", response_model=list[SearchResult])
def search(
    q: str = Query(..., description="Search query string."),
    n: int | None = Query(default=None, description="Number of results (overrides default)."),
) -> list[SearchResult]:
    """Return the top semantic matches for the query string *q*."""
    ctx = _get_ctx()
    if not q.strip():
        raise HTTPException(status_code=422, detail="Query string 'q' must not be empty.")
    vector = ctx.vectorizer.vectorize(q)
    raw_results = ctx.vector_store.query(vector, n_results=n if n is not None else ctx.top_k)
    return [_to_result(r) for r in raw_results]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe — returns 200 when the server is ready."""
    return {"status": "ok"}
