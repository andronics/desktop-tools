"""barctl's own sources (dotfiles record 0003 §B6): each follows one event stream and writes its
modules through the same call `push` uses.

A source is a class with `follow` (read the stream until it ends or `stop` is called), `gone`
(its stream ended: its modules go unavailable), the commands it needs (for `doctor`) and the
dynamic menu rows it gives (`menu_rows`). The controller restarts a source whose stream ended.

Adding a source: subclass Source in a module here, list it in SOURCES, and name it as a module's
`source` in modules.toml.
"""

from __future__ import annotations

from desktop_tools.barctl.sources.base import Source
from desktop_tools.barctl.sources.player import PlayerSource
from desktop_tools.barctl.sources.volume import VolumeSource

SOURCES: dict[str, type[Source]] = {"volume": VolumeSource, "player": PlayerSource}

__all__ = ["SOURCES", "PlayerSource", "Source", "VolumeSource"]
