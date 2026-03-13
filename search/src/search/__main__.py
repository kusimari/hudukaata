"""Entry point for `python -m search`."""

import logging

import uvicorn

from search.app import app
from search.config import Settings

settings = Settings()
app.state.settings = settings
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
uvicorn.run(
    app,
    host="0.0.0.0",
    port=settings.port,
    log_level=settings.log_level.lower(),
)
