"""Stephen's desktop tools in Python: barctl (the Polybar controller), barmenu and the rest of the
dotfiles' tools
"""

from __future__ import annotations

__all__ = ["__description__", "__version__"]


def __getattr__(name: str) -> str:
    # Looked up on first use, not at import: importlib.metadata costs about 20 ms, and
    # `barctl render` (polybar's hook, dotfiles record 0003 §A1) imports this package.
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib.metadata import PackageNotFoundError, metadata, version

    try:
        values = {
            "__version__": version("desktop-tools"),
            # pyproject.toml's description, read rather than repeated as a literal.
            "__description__": metadata("desktop-tools")["Summary"],
        }
    except PackageNotFoundError:  # pragma: no cover - a source tree that was never installed
        values = {"__version__": "0+unknown", "__description__": ""}
    globals().update(values)
    return values[name]
