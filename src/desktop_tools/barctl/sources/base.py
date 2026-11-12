"""The shape every source shares."""

from __future__ import annotations

from collections.abc import Sequence

from desktop_tools.barctl import state as st
from desktop_tools.barctl.modules import Row
from desktop_tools.barctl.store import Writer
from desktop_tools.common import procs


class Source:
    name = ""
    commands: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()  # commands it works without, less well (doctor warns)

    def __init__(self, modules: Sequence[str], writer: Writer) -> None:
        self.modules = list(modules)
        self.writer = writer
        self.stopping = False
        self._stream: procs.Stream | None = None

    def follow(self) -> None:
        """Read the source's stream and write its modules until the stream ends."""
        raise NotImplementedError

    def stream(self, argv: Sequence[str]) -> procs.Stream:
        self._stream = procs.Stream(argv)
        return self._stream

    def stop(self) -> None:
        self.stopping = True
        if self._stream is not None:
            self._stream.stop()

    def set_all(
        self,
        tier: str,
        *,
        glyph: str | None = None,
        label: str = "",
        target: str | None = None,
    ) -> None:
        for module in self.modules:
            self.writer.set(module, self.name, tier, glyph=glyph, label=label, target=target)

    def gone(self) -> None:
        """The stream ended: every module unavailable, showing its default glyph."""
        self.set_all("unavailable")

    @classmethod
    def menu_rows(cls, module: str, state: st.State | None) -> list[Row]:
        """Rows this source adds to a module's right-click menu, worked out when it opens."""
        return []
