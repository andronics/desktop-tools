# 0006: The crew strip shows favourites and live coordinators only

<!-- Add a line for this record to the index in docs/design/README.md (CI checks). -->

Status: Approved
Date: 2026-11-12
Authors: Stephen Cox (ask, 2026-11-12, relayed by the brain coordinator); written up by the desktop coordinator

## Context

The crew strip, `crew cycle` and the scroll show every coordinator the registry lists, running or not. Stephen
wants only his favourites plus the ones with a live session. The brain's registry (`meta brain
coordinators --json`) gains a boolean `favourite` per coordinator (his: brain, arbiter, desktop); a row
without the field means false. That brain change is in flight, so crew must behave sensibly before and
after it lands.

## Decision

1. `Coordinator.favourite` is read from the registry entry (`favourite: true`); absent or anything else is
   False. `Coordinator.favourite_told` records that the registry carried the key at all.
2. **Shown** means: favourite, or its `<name>-coordinator` tmux session (or a former name's) is live, or its
   window exists. The same set drives the bar strip, `crew cycle next|prev` (and so the scroll, which
   calls it) in `strip.visible`. Favourites always show, running or not. `menu_order` still orders them.
3. Cycling and scroll skip hidden coordinators: a stopped non-favourite never appears. Cycling already
   skipped stopped ones, so what changes for it is only the starting point (a remembered "last" that is
   hidden starts from the first shown).
4. **Fallback.** If no coordinator in the registry copy carries `favourite` (an older kept copy, or the brain
   change not merged), every coordinator is shown, as today. Once any entry carries the key, the rule in 2 applies.
5. **Everything else still reaches everyone.** The full menu (`crew menu`, middle-click), `crew list`,
   `crew names` and the launch, stop and restart verbs use the whole registry, shown or not: starting a hidden
   coordinator from the full menu is how it becomes shown.
6. **Edge cases.** A hidden coordinator that starts appears on the next strip refresh (the hooks and
   `crew bar` refresh on each state change; the registry copy itself is read, not re-fetched, by the hot paths).
   A non-favourite that stops disappears at the next refresh. The shown (summoned) coordinator is never
   hidden while its window is shown, even if its session has gone. `stop --all` is unaffected: it counts
   what is running, not what is shown.

No new setting and no change to the registry's shape beyond the one optional key.

## Alternatives considered

- A crew-side favourites setting: rejected, the brain's registry is the one list (record 0019 of the brain).
- Hiding stopped ones from the full menu too: rejected, it would leave no way to start a hidden coordinator.
- Treating a missing key as "no favourites": would empty the strip until the brain change lands.

## Consequences

Strip cells appear and vanish as coordinators start and stop. The fallback means no flag day. The wiki's crew
page notes the rule. Rollback: revert the PR; the extra registry key is ignored by older crew.

## Open questions

- Should a favourite that is stopped look dimmer than today's `unavailable` tier? Recommendation: no, it already
  is the dim tier.
- Should a running non-favourite sort after the favourites rather than by `menu_order`? Recommendation: no,
  keep one order.

## Change log

| Date | Change |
|---|---|
| 2026-11-12 | Proposed by the desktop coordinator |
| 2026-11-12 | Approved: Stephen's ask 2026-11-12 via the brain coordinator; standing rule ❓ 2026-11-12 Desktop Tools Design Records Are Approved Until Notified |
