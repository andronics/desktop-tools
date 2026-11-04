# Architecture Internals

How desktop-tools works inside: for contributors, reviewers and AI assistants. User-facing behaviour belongs on the other pages.

## Overview

<!-- guidance: one paragraph and, ideally, a diagram (mermaid works on GitHub wikis): the main components and what talks to what. -->

## Components

| Module | Responsibility |
|---|---|
| `desktop_tools/__init__.py` | Package version |
| `desktop_tools/config.py` | Settings and their precedence (`_FILE` > env > file > default) |
| `desktop_tools/cli.py` | The `desktop-tools` command (Typer) |

<!-- guidance: add every module as it appears, with one line each. Keep this table current: it is the map an AI assistant reads first. -->

## Data flow

<!-- guidance: follow one request or job from start to finish: where state lives, what's cached, what happens on failure and retry. -->

## Design decisions

Why things are the way they are is recorded in [docs/design/](https://github.com/andronics/desktop-tools/tree/main/docs/design). Rejected ideas and the reasons are in [TODO.md](https://github.com/andronics/desktop-tools/blob/main/TODO.md) under "Decided against".

<!-- guidance: list the decisions that shape the code most, one line each, linking to their design records. -->
