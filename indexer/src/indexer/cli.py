"""Click CLI entry point for the indexer."""

from __future__ import annotations

import logging
from typing import Any

import click
from common.base import StorePointer, resolve_instance
from common.index import IndexStore
from common.media import MediaSource

from indexer.models.base import CaptionModel
from indexer.models.blip2 import Blip2CaptionModel
from indexer.pointer import MediaPointer
from indexer.runner import run
from indexer.stores.chroma_caption import ChromaCaptionIndexStore

_CAPTION_MODELS: dict[str, type[Any]] = {
    "blip2": Blip2CaptionModel,
}

_INDEX_STORES: dict[str, type[Any]] = {
    "chroma-caption": ChromaCaptionIndexStore,
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
    "--index-store",
    "index_store_name",
    default="indexer.stores.chroma_caption.ChromaCaptionIndexStore",
    show_default=True,
    help="IndexStore class to use (short name or dotted import path).",
)
@click.option(
    "--folder",
    default=None,
    help="Subfolder within the media source to process (enables incremental batching).",
)
@click.option(
    "--checkpoint-interval",
    default=100,
    show_default=True,
    help="Write a checkpoint to the store every N files processed (0 to disable).",
)
@click.option("--log-level", default="INFO", show_default=True, help="Logging level.")
def index(
    media: str,
    store: str,
    caption_model_name: str,
    index_store_name: str,
    folder: str | None,
    checkpoint_interval: int,
    log_level: str,
) -> None:
    """Index media files from MEDIA pointer into STORE."""
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    media_src: MediaSource = MediaPointer.parse(media)
    store_ptr = StorePointer.parse(store)

    try:
        caption_model: CaptionModel = resolve_instance(
            caption_model_name, _CAPTION_MODELS, "caption-model", CaptionModel
        )
        idx_store: IndexStore = resolve_instance(
            index_store_name, _INDEX_STORES, "index-store", IndexStore
        )
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc

    run(
        media_src,
        store_ptr,
        caption_model,
        idx_store,
        index_store_name=index_store_name,
        folder=folder,
        checkpoint_interval=checkpoint_interval,
    )


if __name__ == "__main__":
    main()
