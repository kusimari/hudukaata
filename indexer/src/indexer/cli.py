"""Click CLI entry point for the indexer."""

from __future__ import annotations

import importlib
import logging
from typing import Any

import click

from indexer.models.base import CaptionModel
from indexer.models.blip2 import Blip2CaptionModel
from indexer.pointer import MediaPointer, StorePointer
from indexer.runner import run
from indexer.stores.base import VectorStore
from indexer.stores.chroma import ChromaVectorStore
from indexer.vectorizers.base import Vectorizer
from indexer.vectorizers.sentence_transformer import SentenceTransformerVectorizer

_CAPTION_MODELS: dict[str, type[CaptionModel]] = {
    "blip2": Blip2CaptionModel,
}
_VECTORIZERS: dict[str, type[Vectorizer]] = {
    "sentence-transformer": SentenceTransformerVectorizer,
}
_VECTOR_STORES: dict[str, type[VectorStore]] = {
    "chroma": ChromaVectorStore,
}


def _resolve_class(name: str, registry: dict[str, type[Any]], kind: str) -> Any:
    """Resolve a short name from the registry, or import a dotted path."""
    if name in registry:
        return registry[name]()
    # Treat as dotted import path: "my.module.ClassName"
    try:
        module_path, class_name = name.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls()
    except Exception as exc:
        raise click.BadParameter(
            f"Cannot load {kind} {name!r}: {exc}", param_hint=f"--{kind}"
        ) from exc


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

    caption_model = _resolve_class(caption_model_name, _CAPTION_MODELS, "caption-model")
    vectorizer = _resolve_class(vectorizer_name, _VECTORIZERS, "vectorizer")
    vector_store = _resolve_class(vector_store_name, _VECTOR_STORES, "vector-store")

    run(media_ptr, store_ptr, caption_model, vectorizer, vector_store)


if __name__ == "__main__":
    main()
