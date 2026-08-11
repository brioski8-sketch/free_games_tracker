# Finding PR-0003 — Limited-window Steam giveaways cannot be caught

> PR-branch-equivalent for validation finding **A3**.
> Status: OPEN — a real coverage gap (time-boxed false negative).
> Severity: Non-blocking for correctness of what IS reported; blocking for
> "catch N known paid->free games" when those games are limited-window Steam
> claims rather than permanent conversions.

## Summary
The Steam collector only detects **permanent** paid->free conversions for
**watchlisted** appids (a persisted `is_free False->True` flip with a prior
`final > 0`). It cannot detect a **temporary free-to-keep window** on Steam.
Validatee: Moonlighter (appid 606150) was free-to-keep Aug 5-9, 2026 but was
not surfaced, because it is not on the watchlist and the architecture never
snapshots a title while it is temporarily free.

## Reproduction steps
1. `cat config.yaml` -> `watched_appids: [340580, 1158310, 1238840, 1174180]`.
2. Note Moonlighter appid `606150` is not watchlisted.
3. Steam live `appdetails` for `606150` at report time (2026-08-09 23:58 UTC):
   `is_free=False`, `final=1999` — the free-to-keep window (Aug 5-9, ended
   ~10:00 PT Aug 9) had already closed the day the report ran.
4. Run the pipeline; curated output contains only the 2 Epic weekly giveaways.

## Expected vs actual behaviour
- **Expected**: a Steam title that was free-to-keep during the report window is
  surfaced as paid->free (free-to-keep is a keep action, in scope).
- **Actual**: never surfaced. The tracker has no change-tracking of a title
  *while* it is temporarily free; it only flips on a permanent conversion for a
  pre-seeded appid. A limited-window Steam giveaway that closes before the
  nightly/weekly run is a structural blind spot.

## Root cause
`steam.py collect()` requires `prior.is_free is False` AND `prior.final > 0`
before emitting, and that prior snapshot must exist (watchlisted). For a
temporary free window there is no permanent flip to observe; even if the title
were watchlisted, its `is_free` returns to `False` once the window closes, so a
run that lands after the window sees no flip. Detection requires either a
same-day Reddit/aggregator hit (disabled / rate-limited — see PR-0002) or
snapshotting price changes inside the window.

## Evidence / logs
- Live Steam evidence (verified by parent task t_de9fad83): appid 606150
  `is_free=False`, `final=1999` at report time — window closed same day.
- Curated report does not include Moonlighter:
  `reports/validation/run1/free-games-2026-08-09.md` / `free_games.json`.
- Full analysis: `.worktrees/t_de9fad83/paid_to_free_verification.md`
  ("Moonlighter-specific: even with a healthy Steam collector ... window ended
  the day the report ran").

## Suggested remediation (do NOT implement here)
For limited-window Steam giveaways, consume a same-day change feed (SteamDB /
freeToKeep / a healthy r/FGF or aggregator) and/or snapshot price during the
window. Without a source that is fresh within the claim window, temporary
Steam giveaways are architecturally uncatchable. Out of scope for this task.
