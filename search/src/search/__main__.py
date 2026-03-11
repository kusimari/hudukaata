"""Entry point: python -m search"""

from __future__ import annotations

import logging

import uvicorn

from search.config import Settings

if __name__ == "__main__":
    settings = Settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    uvicorn.run(
        "search.app:app",
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
