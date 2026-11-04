# Frequently Asked Questions

## Why Python, and why not keep the zsh controller?

Stephen moved the desktop tools to Python (dotfiles record 0003). The next modules need D-Bus, HTTP, GraphQL, a
control socket and timers, where zsh is weakest. See [Introduction](Introduction).

## Isn't Python too slow for polybar's hook?

`barctl render` and `push` skip Typer and use the standard library only: about 30 ms, the same as the zsh version.

## How do I add a module?

[Adding a Module](Adding-A-Module).

## Where did `barctl poke` go?

It is `barctl reload <module>` now, which also re-reads `modules.toml`.
