"""crew: the coordinator switchboard, one hidden terminal per Claude Code coordinator, docked
left or right when shown (brain record 0019 §7; it replaces the dotfiles' zsh `coord`).

`cli.main` is the console command. `status` and `bar`, which nine Claude hooks and the bar run
all the time, go through `fast` with the standard library only; every other verb is the Typer
app in `app`.
"""
