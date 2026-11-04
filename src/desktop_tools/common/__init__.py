"""What the desktop tools share: XDG paths, the journal helper, theme roles, polybar IPC and
running a command detached (dotfiles record 0003 §A1).

Every module here is standard library only and cheap to import: `barctl render` runs on
every poke of a bar module and imports them before Typer.
"""
