"""Click CLI entry point for the indexer."""

from __future__ import annotations

import logging
from typing import Any

import click
from common.plugins import resolve_instance
from common.pointer import StorePointer
from common.registry import VECTOR_STORES, VECTORIZERS
from common.stores.base import VectorStore
from common.vectorizers.base import Vectorizer

from indexer.models.base import CaptionModel
from indexer.models.blip2 import Blip2CaptionModel
from indexer.pointer import MediaPointer
from indexer.runner import run

_CAPTION_MODELS: dict[str, type[Any]] = {
    "blip2": Blip2CaptionModel,
}


@click.group()
def main() -> None:
    """hudukaata indexer — index media files into a vector database."""


@main.command()
@click.option(
    "--media", required=True, help="Media directory pointer (file:// or rclone:remote:///path)."
)
@click.option(
    "--store", required=True, help="Store directory pointer (file:// or rclone:remote:///path)."
)
@click.option(
    "--caption-model",
    "caption_model_name",
    default="blip2",
    show_default=True,
    help="Captioner class to use (short name or dotted import path).",
)
@click.option(
    "--vectorizer",
    "vectorizer_name",
    default="sentence-transformer",
    show_default=True,
    help="Vectorizer class to use.",
)
@click.option(
    "--vector-store",
    "vector_store_name",
    default="chroma",
    show_default=True,
    help="Vector store class to use.",
)
@click.option("--log-level", default="INFO", show_default=True, help="Logging level.")
def index(
    media: str,
    store: str,
    caption_model_name: str,
    vectorizer_name: str,
    vector_store_name: str,
    log_level: str,
) -> None:
    """Index media files from MEDIA pointer into STORE."""
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    media_ptr = MediaPointer.parse(media)
    store_ptr = StorePointer.parse(store)

    try:
        caption_model: CaptionModel = resolve_instance(
            caption_model_name, _CAPTION_MODELS, "caption-model", CaptionModel
        )
        vectorizer: Vectorizer = resolve_instance(
            vectorizer_name, VECTORIZERS, "vectorizer", Vectorizer
        )
        vector_store: VectorStore = resolve_instance(
            vector_store_name, VECTOR_STORES, "vector-store", VectorStore
        )
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc

    run(
        media_ptr,
        store_ptr,
        caption_model,
        vectorizer,
        vector_store,
        vectorizer_name=vectorizer_name,
        vector_store_name=vector_store_name,
    )


if __name__ == "__main__":
    main()
