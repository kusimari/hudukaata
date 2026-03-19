"""Entry point for `python -m search`.

Usage::

    python -m search serve blip2-sentok-exif
    python -m search serve blip2-sentok-exif-insightface

The indexer key is passed via the ``serve`` subcommand.  All other settings
(``SEARCH_STORE``, ``SEARCH_MEDIA``, etc.) are loaded from environment variables.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from search.startup import available_indexer_keys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m search",
        description="hudukaata search server",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    keys = available_indexer_keys()
    serve_parser = sub.add_parser("serve", help="Start the search server.")
    serve_parser.add_argument(
        "indexer_key",
        choices=keys,
        metavar="INDEXER_KEY",
        help=f"Which indexer variant to serve. One of: {', '.join(keys)}.",
    )

    args = parser.parse_args()

    if args.command == "serve":
        os.environ["SEARCH_INDEXER_KEY"] = args.indexer_key

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
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
