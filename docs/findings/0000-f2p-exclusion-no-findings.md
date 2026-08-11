# No-Findings Note — Free-to-play exclusion check (t_28f43ec1)

> Status: CLOSED — validation passed with **no findings** for this check.
> This is the explicit "validation passed with no findings" artifact required
> by the task acceptance criteria for the F2P exclusion check.

## Scope
Verify that known free-to-play titles are correctly **absent** from the curated
"paid -> free" report (i.e. the tracker does not surface permanently-F2P games).

## What was checked
- Curated report: `reports/validation/run1/free-games-2026-08-09.md` and
  `reports/validation/run1/free_games.json`.
- 10 well-known F2P titles tested (5 required + 5 bonus), case-insensitive over
  the full report markdown and all JSON `title` fields incl. aliases:
  Fortnite, Apex Legends, Warframe, Genshin Impact, League of Legends
  (required); Valorant, Destiny 2, Team Fortress 2, Dota 2, Overwatch 2 (bonus).
- Both curated entries are `is_permanent: false` with non-null
  `original_price` — confirming the tracker only surfaces paid->free
  limited-time conversions, never permanent F2P titles.

## Result
All 10 known F2P games are **absent** (0 false positives). This is correct by
design: these titles are permanently free-to-play (never paid), so they are not
paid->free conversions and must never be surfaced.

## Conclusion
**No issues found** for the free-to-play exclusion check. No PR needed.

Reference: `.worktrees/t_28f43ec1/reports/validation/verify-f2p-rejection.md`.
