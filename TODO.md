# TODO

Short-lived working list. Bugs and features with discussion belong in GitHub issues; this file is for what
the team (and its AI assistants) should know at a glance.

## Open

- [ ] Write docs/design/0001-initial-design.md (docs/ai/prompts.md, prompt 1)
- [ ] Replace every `<!-- guidance -->` comment in docs/wiki/ (a Release PR is blocked until then)

## Decided against (don't re-propose without reading this first)

<!-- One line each: the idea, why not, and a link to the issue, PR or design record. For example:
- Helm chart: kustomize base + Flux overlays cover our clusters; a chart doubles the maintenance (design 0003).
-->
- barmenu rows from a command's JSON (`rows_from`): labels and glyphs would move into zsh, and every open pays a zsh start-up; providers are Python (design 0001).
- Every scheme as its own row in the theme menu: overflows the 8-line window and duplicates `theme pick` without its previews (design 0001).
- A timed idle-lock pause run by a background `sleep`: nothing can show its end or cancel it; a transient systemd timer does (design 0001).
