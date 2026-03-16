"""Click CLI entry point for the indexer.

The ``index`` command accepts a single JSON config file.  The ``indexer``
field in the JSON selects which indexer class to use; the rest of the fields
are passed to the indexer-specific config dataclass.

Example config (blip2_sentok_exif_chroma):

.. code-block:: json

    {
        "indexer": "blip2_sentok_exif_chroma",
        "media_uri": "file:///media",
        "store_uri": "file:///store",
        "folder": null,
        "initial_batch_size": 1,
        "max_batch_size": 32,
        "adaptive_batch": true,
        "checkpoint_interval": 0,
        "load_in_8bit": false,
        "log_level": "INFO"
    }
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
from common.base import StorePointer
from common.index import IndexStore
from common.media import MediaSource

from indexer.batch import AdaptiveBatchController
from indexer.indexers.blip2_sentok_exif_chroma import Blip2SentTokExifChromaIndexer
from indexer.models.base import CaptionModel
from indexer.pipeline import AdaptiveBatchRunner
from indexer.runner import IndexingRunner

# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Blip2SentTokExifChromaConfig:
    """Configuration for the caption-based indexer."""

    media_uri: str = ""
    store_uri: str = ""
    folder: str | None = None
    initial_batch_size: int = 1
    max_batch_size: int = 32
    adaptive_batch: bool = True
    checkpoint_interval: int = 0
    load_in_8bit: bool = False
    log_level: str = "INFO"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Blip2SentTokExifChromaConfig:
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


# ---------------------------------------------------------------------------
# Registry: indexer key → (config class, builder function)
# ---------------------------------------------------------------------------


def _build_blip2(config: Blip2SentTokExifChromaConfig) -> None:
    """Build and run the Blip2SentTokExifChromaIndexer pipeline."""
    logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO))

    from indexer.models.blip2 import Blip2CaptionModel
    from indexer.stores.chroma_caption import ChromaCaptionIndexStore

    caption_model: CaptionModel = Blip2CaptionModel(load_in_8bit=config.load_in_8bit)
    idx_store: IndexStore = ChromaCaptionIndexStore()

    indexer = Blip2SentTokExifChromaIndexer(
        caption_model=caption_model,
        index_store=idx_store,
    )
    ctrl = AdaptiveBatchController(
        initial_size=config.initial_batch_size,
        max_size=config.max_batch_size,
        adaptive=config.adaptive_batch,
    )
    runner = IndexingRunner(
        pipeline_runner=AdaptiveBatchRunner(ctrl),
        checkpoint_interval=config.checkpoint_interval,
    )
    runner.run(
        pipeline=indexer.pipeline(),
        media=MediaSource.from_uri(config.media_uri),
        store=StorePointer.parse(config.store_uri),
        index_store=idx_store,
        index_store_name="blip2_sentok_exif_chroma",
        folder=config.folder,
    )


_RegistryEntry = tuple[type[Any], Callable[[Any], None]]

_REGISTRY: dict[str, _RegistryEntry] = {
    "blip2_sentok_exif_chroma": (Blip2SentTokExifChromaConfig, _build_blip2),
}

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def main() -> None:
    """hudukaata indexer — index media files into a vector database."""


@main.command()
@click.argument("config_file", type=click.Path(exists=True, path_type=Path))
def index(config_file: Path) -> None:
    """Index media files using the configuration in CONFIG_FILE (JSON)."""
    raw: dict[str, Any] = json.loads(config_file.read_text())
    indexer_key = raw.get("indexer", "")
    if indexer_key not in _REGISTRY:
        raise click.BadParameter(
            f"Unknown indexer {indexer_key!r}. Available: {', '.join(sorted(_REGISTRY))}",
            param_hint="indexer",
        )
    cfg_cls, build_fn = _REGISTRY[indexer_key]
    config = cfg_cls.from_dict({k: v for k, v in raw.items() if k != "indexer"})
    build_fn(config)


# ---------------------------------------------------------------------------
# Legacy flags entry point (kept for backwards compatibility with old scripts)
# ---------------------------------------------------------------------------


@main.command(name="index-legacy", hidden=True)
@click.option("--media", required=True)
@click.option("--store", required=True)
@click.option("--caption-model", "caption_model_name", default="blip2")
@click.option(
    "--index-store",
    "index_store_name",
    default="indexer.stores.chroma_caption.ChromaCaptionIndexStore",
)
@click.option("--folder", default=None)
@click.option("--checkpoint-interval", default=0)
@click.option("--initial-batch-size", default=1)
@click.option("--max-batch-size", default=32)
@click.option("--adaptive-batch/--no-adaptive-batch", default=True)
@click.option("--load-in-8bit/--no-load-in-8bit", default=False)
@click.option("--log-level", default="INFO")
def index_legacy(
    media: str,
    store: str,
    caption_model_name: str,
    index_store_name: str,
    folder: str | None,
    checkpoint_interval: int,
    initial_batch_size: int,
    max_batch_size: int,
    adaptive_batch: bool,
    load_in_8bit: bool,
    log_level: str,
) -> None:
    """Legacy flags-based indexing (deprecated — use ``index CONFIG_FILE``)."""
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    from indexer.models.blip2 import Blip2CaptionModel
    from indexer.runner import run
    from indexer.stores.chroma_caption import ChromaCaptionIndexStore

    caption_model: CaptionModel = Blip2CaptionModel(load_in_8bit=load_in_8bit)
    idx_store: IndexStore = ChromaCaptionIndexStore()

    run(
        MediaSource.from_uri(media),
        StorePointer.parse(store),
        caption_model,
        idx_store,
        index_store_name=index_store_name,
        folder=folder,
        checkpoint_interval=checkpoint_interval,
        initial_batch_size=initial_batch_size,
        max_batch_size=max_batch_size,
        adaptive_batch=adaptive_batch,
    )


if __name__ == "__main__":
    main()
