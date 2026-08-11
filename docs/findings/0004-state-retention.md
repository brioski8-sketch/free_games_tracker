# Finding PR-0004 — State-retention: no pruning / no TTL on seen & steam_snapshots

> PR-branch-equivalent for validation findings **B1 + B2** (from dedupe/state
> check, parent task t_39287a0c).
> Status: OPEN — non-blocking / hardening note. Not a correctness defect; dedupe
> and state transitions verified correct (29/29 simulation checks PASS).

## Summary
Both state tables are append/upsert-only with no retention policy:
- `seen` rows accumulate for every distinct (game_id, end_date, free_since)
  event ever surfaced — games that stop being free remain forever as an audit
  trail (verified they do NOT leak back into the curated list).
- `steam_snapshots` rows accumulate per appid ever tracked/observed — row count
  is bounded by watchlist + ever-tracked appids, and does not duplicate per run,
  but there is no TTL.

## Reproduction steps
1. Inspect `reports/validation/run1/state.db`:
   - `SELECT COUNT(*) FROM seen;` -> 8.
   - `SELECT COUNT(*) FROM steam_snapshots;` -> 4.
2. Re-run the workflow 3x sequentially off that state
   (`python main.py --config config.yaml ...`):
   - `new=0` every run; curated list identical; seen row count and
     steam_snapshots row count do NOT grow on identical re-runs (idempotent).
   - Confirms dedupe correctness (no duplicates), matching the acceptance goal.
3. Long-term: over many weekly runs with fresh giveaways, `seen` grows
   monotonically and is never pruned; a title that stopped being free remains
   in `seen` forever.

## Expected vs actual behaviour
- **Expected (correctness)**: dedupe works — confirmed. `new=0` on repeats, no
  re-adds, dropped games removed from curated list, Steam paid->free flips
  captured once. All 29/29 state-transition simulation checks pass.
- **Actual (retention)**: `seen` and `steam_snapshots` have no TTL/pruning.
  Rows accumulate as a permanent audit trail. Non-blocking but unbounded growth
  over weekly runs.

## Root cause
`free_games_tracker/state.py` schema and methods (`mark_seen`, `put_steam_snapshot`)
only INSERT ... ON CONFLICT UPSERT. There is no `DELETE`/TTL/pruning path and the
`seen` table intentionally retains history (the keys are the event identity). This
is a deliberate audit-trail design, not a bug in dedupe behaviour.

## Evidence / logs
- State DB: `reports/validation/run1/state.db` — `seen=8`, `steam_snapshots=4`.
- Sequential-run evidence: repeats run2/run3 under
  `.worktrees/t_39287a0c/reports/validation/` (run2, run3, run1_start_state.db):
  `new=0` on each, no row-count growth on identical re-runs.
- Simulation: `.worktrees/t_39287a0c/reports/validation/simulate_state_transitions.py`
  — 29/29 PASS.
- Verification write-up: `.worktrees/t_39287a0c/reports/validation/DEDUPE-STATE-VERIFICATION.md`.

## Suggested remediation (do NOT implement here)
Optional future hardening: (a) prune `seen` rows whose (end_date, free_since) is
old and not currently offered; (b) add a TTL to `steam_snapshots`. Neither is
required for correctness. Out of scope for this task.
