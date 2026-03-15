"""FastAPI application — search endpoint, media serving, and health checks."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from search.config import Settings
from search.startup import AppState, load

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 65_536


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Re-use settings pre-loaded by __main__ (single env-read, keeps port /
    # log_level in sync with what uvicorn was told).  Fall back to a fresh
    # Settings() when the server is started externally, e.g.
    # `uvicorn search.app:app`.
    settings: Settings | None = getattr(app.state, "settings", None)
    if settings is None:
        settings = Settings()
    try:
        app.state.ctx = load(settings)
    except Exception:
        logger.error("Failed to load index at startup", exc_info=True)
        raise
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

# Allow browsers to call this server from any origin (e.g. the webapp running
# on a different port).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


class SearchResult(BaseModel):
    """A single result returned by the search endpoint."""

    id: str
    caption: str = ""
    relative_path: str = ""
    extra: dict[str, str] = Field(default_factory=dict)


def _get_ctx() -> AppState:
    """Return the AppState, raising 503 if startup did not complete."""
    ctx: AppState | None = getattr(app.state, "ctx", None)
    if ctx is None:
        raise HTTPException(status_code=503, detail="Server not ready; index not loaded.")
    return ctx


@app.get("/search", response_model=list[SearchResult])
async def search(
    q: str = Query(..., description="Search query string."),
    n: int | None = Query(default=None, description="Number of results (overrides default)."),
) -> list[SearchResult]:
    """Return the top semantic matches for the query string *q*."""
    ctx = _get_ctx()
    if not q.strip():
        raise HTTPException(status_code=422, detail="Query string 'q' must not be empty.")
    results = await asyncio.to_thread(ctx.index_store.search, q, n if n is not None else ctx.top_k)
    return [
        SearchResult(
            id=r.id,
            caption=r.caption,
            relative_path=r.relative_path,
            extra=r.extra,
        )
        for r in results
    ]


@app.get("/media/{path:path}")
async def media(path: str) -> StreamingResponse:
    """Stream a media file from the configured media root by its relative path."""
    ctx = _get_ctx()

    # Prevent path traversal: reject '..', absolute prefixes, and percent-encoded variants.
    if (
        ".." in Path(path).parts
        or path.startswith("/")
        or "%2e" in path.lower()
        or "%2f" in path.lower()
    ):
        raise HTTPException(status_code=400, detail="Invalid path.")

    def _serve() -> StreamingResponse:
        with ctx.media_src.getmedia(path) as mf:
            local_path = mf.local_path
            if not local_path.is_file():
                raise HTTPException(status_code=404, detail="Media file not found.")
            mime_type, _ = mimetypes.guess_type(str(local_path))
            content_type = mime_type or "application/octet-stream"
            # Read the file fully inside the context so the rclone temp dir
            # still exists when we stream the bytes.
            data = local_path.read_bytes()
        return StreamingResponse(iter([data]), media_type=content_type)

    return await asyncio.to_thread(_serve)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe — always returns 200 when the process is alive."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    """Readiness probe — returns 503 until the index is loaded."""
    _get_ctx()
    return {"status": "ready"}


if __name__ == "__main__":
    settings = Settings()
    # Store on app.state so lifespan reuses this exact instance instead of
    # constructing a second Settings().  Pass `app` directly (not the import
    # string) so the state is preserved across the uvicorn startup boundary.
    app.state.settings = settings
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
