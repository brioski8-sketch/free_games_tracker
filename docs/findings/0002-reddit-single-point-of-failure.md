# Finding PR-0002 — Reddit r/FGF source is a single-point-of-failure

> PR-branch-equivalent for validation finding **A2**.
> Status: OPEN — a real robustness/coverage defect.
> Severity: Non-blocking for correctness of produced output (pipeline degrades
> safely), blocking for the goal of cross-store coverage.

## Summary
The Reddit `r/FreeGameFindings` collector is the only cross-store / non-Epic /
non-curated safety net, but it silently returns `[]` on rate-limit (HTTP 403)
with no fallback aggregator enabled. When it 403s, the tracker degrades to
Epic-only. This is exactly what happened during the validation run.

## Reproduction steps
1. `cat config.yaml` -> `collectors.reddit: true`, and `ggdeals`, `steamdb`,
   `freetokeep`, `gog`, `itch`, `prime` are all `false`.
2. Observe that `free_games_tracker/collectors/reddit.py` `collect()` wraps
   `fetch_json` in a bare `except FetchError: return []`.
   `httpclient.py` `fetch_json()` raises `FetchError` for any HTTP 4xx
   (`if code is not None and 400 <= code < 500: raise FetchError`), and retries
   are skipped for 4xx. So one 403 swallows the whole source.
3. Run live: `python main.py --config config.yaml --digest-only
   --output-dir /tmp/fg`.
4. Confirm the r/FGF feed is unreachable (rate-limited) during the window.

## Expected vs actual behaviour
- **Expected**: a rate-limited community feed degrades gracefully **and** the
  tracker still has other working sources (it does — Epic), so a healthy
  r/FGF would have contributed Steam/GOG/itch giveaways.
- **Actual**: r/FGF contributed **zero** records. With 4/4 alternative
  aggregators disabled and the Steam watchlist covering only 4 appids, the
  entire run is Epic-only (curated = 2 Epic games). Any non-Epic paid->free
  giveaway is invisible while Reddit 403s.

## Root cause
Two compounding issues: (a) `reddit.py` has no backoff / caching-proxy and
treats a single 403 as a hard `[]`; (b) `config.yaml` keeps every fallback
aggregator (`ggdeals`, `steamdb`, `freetokeep`) disabled, so there is no second
cross-store source to absorb the failure. Reddit is a single point of failure
for Steam/GOG/itch coverage.

## Evidence / logs
- Run log: `reports/validation/run1/run.log` — r/FGF produced no rows;
  parent run metadata recorded `collectors.reddit = degarded_to_empty_http403`.
- Curated output is Epic-only: `reports/validation/run1/free_games.json` (both
  entries `source_feed: epic_freeGamesPromotions:current`).
- Root-cause analysis: `.worktrees/t_de9fad83/paid_to_free_verification.md`
  ("Reddit r/FGF rate-limit is a real single-point-of-failure").

## Suggested remediation (do NOT implement here)
Add a caching proxy / exponential backoff for the Reddit JSON endpoint, and/or
enable at least one secondary aggregator (`ggdeals`, `steamdb`, `freetokeep`)
so r/FGF is not the sole non-Epic source. Consider surfacing a warning line in
the report when a configured source degrades to `[]` (currently silent). Out of
scope for this task.
