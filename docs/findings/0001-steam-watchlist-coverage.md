# Finding PR-0001 — Steam paid->free coverage gap (tiny curated watchlist)

> PR-branch-equivalent for validation finding **A1**.
> Status: OPEN — this is a real correctness/coverage defect, not a nit.
> Severity: Blocking for the "captures N known paid->free games" acceptance goal.

## Summary
The Steam collector only change-tracks appids that are on the tiny curated
watchlist (`steam.watched_appids`). Any Steam title that converted paid->free
**before it was added to the watchlist** can never be surfaced, because the
tracker's detection mechanism is a *flip* (prior paid snapshot -> now free),
and a title with no prior snapshot is treated as native F2P and skipped.

## Reproduction steps
1. `cd <workflow repo>` (branch `wt/t_9cfda6e5`, tip `7a27547`).
2. `cat config.yaml | grep watched_appids`
   ->  `watched_appids: [340580, 1158310, 1238840, 1174180]`  (4 appids).
3. Confirm the two converted titles are NOT watchlisted and have NO prior
   Steam snapshot in `reports/validation/run1/state.db`:
   - WOBBLY HEIST, appid `4196110` — permanent paid->free (Jul 2026).
   - Grit the Dark World, appid `3810890` — permanent paid->free (Jun-Jul 2026).
4. Run the pipeline live:
   `python main.py --config config.yaml --digest-only --output-dir /tmp/fg`.
   The curated report contains only the 2 Epic weekly giveaways
   (Beacon Pines, We Were Here Together). Neither Steam title appears.
5. Query Steam live to confirm both are genuinely free:
   `python scripts/seed_steam_watchlist.py 4196110 3810890`
   -> both report `is_free=True` and no `price_overview`.

## Expected vs actual behaviour
- **Expected**: a Steam title that permanently converted paid->free appears in
  the curated "now free" report.
- **Actual**: it does not appear. The tracker is effectively Epic-only on this
  run: 2/2 curated entries are Epic; 0 Steam.

## Root cause
`free_games_tracker/collectors/steam.py` `collect()` only flips appids that
already have a prior snapshot with `is_free == False` and `final > 0`. An appid
never snapshotted (not on `DEFAULT_WATCHLIST` / `config.yaml
steam.watched_appids`) and not already in `state.db` is skipped entirely —
regardless of whether it is now free. The permanent conversions of WOBBLY HEIST
and GRIT happened weeks before the validation run, so no "paid" snapshot exists
to flip from.

## Evidence / logs
- Live curated report: `reports/validation/run1/free-games-2026-08-09.md` (2
  entries, both Epic).
- Machine output:     `reports/validation/run1/free_games.json` (2 entries,
  both `source_feed: epic_freeGamesPromotions:current`).
- Run log:            `reports/validation/run1/run.log` -> `[done] normalized=3 passing=2 new=0`.
- State db:           `reports/validation/run1/state.db` -> `steam_snapshots`
  holds exactly 4 appids (340580,1158310,1238840,1174180), all `is_free=0`; the
  two converted appids (4196110, 3810890) are absent -> their flips are
  invisible.
- Full verification write-up (parent task t_de9fad83):
  `.worktrees/t_de9fad83/paid_to_free_verification.md`.

## Suggested remediation (do NOT implement here)
Seed `config.yaml -> steam.watched_appids` with the known converted titles
(`4196110`, `3810890`, ...) once, so a prior paid snapshot exists and future
state changes / reverts are tracked; and/or enable a curated Steam flip feed
(`steamdb` / `freetokeep` in `collectors:`), and/or ingest a historical
"became free" source on first seed. Out of scope for this task — surfaced for
the implementer.
