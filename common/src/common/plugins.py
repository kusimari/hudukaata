"""Generic plugin resolver — shared between indexer and search."""

from __future__ import annotations

import importlib
from typing import Any


def resolve_instance(
    name: str,
    registry: dict[str, type[Any]],
    kind: str,
    expected_type: type[Any],
) -> Any:
    """Return an instance for *name*, looked up in *registry* or via dotted import.

    The resolved class must be a subclass of *expected_type*; otherwise a
    ``ValueError`` is raised.  This prevents index_meta.json from being used to
    instantiate arbitrary classes.

    Args:
        name: Short registry key (e.g. ``"chroma"``) or dotted import path
            (e.g. ``"mypackage.stores.MyStore"``).
        registry: Mapping of short names to concrete types.
        kind: Human-readable label used in error messages (e.g. ``"vector-store"``).
        expected_type: ABC or base class that the resolved class must implement.

    Returns:
        An instance of the resolved class.  Callers should annotate the return
        explicitly: ``vs: VectorStore = resolve_instance(...)``.

    Raises:
        ValueError: if *name* cannot be resolved or the resolved class does not
            implement *expected_type*.
    """
    if name in registry:
        cls: type[Any] = registry[name]
    else:
        try:
            module_path, class_name = name.rsplit(".", 1)
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
        except Exception as exc:
            raise ValueError(f"Cannot load {kind} {name!r}: {exc}") from exc

    if not (isinstance(cls, type) and issubclass(cls, expected_type)):
        raise ValueError(
            f"{kind} {name!r} must be a subclass of {expected_type.__name__}, got {cls!r}"
        )
    return cls()
