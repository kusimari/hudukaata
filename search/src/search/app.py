"""FastAPI application — search endpoint, media serving, and health checks."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from common.index import CaptionItem, FaceItem, IndexResult, IndexStore
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
    face_cluster_ids: list[str] = Field(default_factory=list)
    extra: dict[str, str] = Field(default_factory=dict)


class FaceResult(BaseModel):
    """A single face cluster returned by the faces endpoint."""

    cluster_id: str
    representative_path: str = ""
    count: int = 0
    image_paths: list[str] = Field(default_factory=list)
    score: float = 0.0


def _filter_by_faces(
    results: list[IndexResult[CaptionItem]],
    face_ids_str: str,
    face_store: IndexStore[FaceItem],
) -> list[IndexResult[CaptionItem]]:
    """Return *results* filtered to items whose relative_path appears in the
    given face clusters.  Returns the unfiltered list if *face_store* is None.
    """
    requested_fids = {fid.strip() for fid in face_ids_str.split(",") if fid.strip()}
    candidate_paths: set[str] = set()
    for fid in requested_fids:
        meta = face_store.get_metadata(fid)
        if meta:
            candidate_paths.update(p for p in meta.get("image_paths", "").split(",") if p)
    return [r for r in results if r.relative_path in candidate_paths]


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
    face_ids: str | None = Query(
        default=None,
        description="Comma-separated face cluster IDs to filter results.",
    ),
) -> list[SearchResult]:
    """Return the top semantic matches for the query string *q*.

    Optionally filter results to only images that contain the given face
    cluster IDs (pass *face_ids* as a comma-separated string).
    """
    ctx = _get_ctx()
    if not q.strip():
        raise HTTPException(status_code=422, detail="Query string 'q' must not be empty.")

    top_k = n if n is not None else ctx.top_k
    results = await asyncio.to_thread(ctx.index_store.search, CaptionItem(text=q), top_k)

    # Optional face-cluster filter.
    if face_ids and ctx.face_store is not None:
        results = _filter_by_faces(results, face_ids, ctx.face_store)

    return [
        SearchResult(
            id=r.id,
            caption=r.item.text,
            relative_path=r.relative_path,
            face_cluster_ids=[fid for fid in r.extra.get("face_cluster_ids", "").split(",") if fid],
            extra={k: v for k, v in r.extra.items() if k != "face_cluster_ids"},
        )
        for r in results
    ]


@app.get("/faces", response_model=list[FaceResult])
async def faces(
    n: int | None = Query(default=None, description="Max number of face clusters to return."),
) -> list[FaceResult]:
    """Return face clusters sorted by frequency (most common faces first)."""
    ctx = _get_ctx()
    if ctx.face_store is None:
        raise HTTPException(
            status_code=404,
            detail="Face store not loaded. Start the server with a face-aware indexer key.",
        )
    top_k = n if n is not None else ctx.top_k
    results = await asyncio.to_thread(ctx.face_store.list_all, top_k)
    return [
        FaceResult(
            cluster_id=r.id,
            representative_path=r.relative_path,
            count=int(r.extra.get("count", "0")),
            image_paths=[p for p in r.extra.get("image_paths", "").split(",") if p],
            score=r.score,
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
