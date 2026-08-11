# free_games_tracker

Detect **paid PC games that became available for free** (free-to-keep giveaways and
permanent paid→free conversions) and report them with enough metadata to act on
(claim link, original price, claim window).

This project deliberately does **NOT** report:
- Always free-to-play (F2P) games (Fortnite, Apex, LoL, ...)
- Free-weekend / free-trial / timed "Play now" access
- Demos, playtests, betas, prologues, showcase/benchmark builds
- DLC / add-ons / "Starter Edition" packs / in-game content (unless a flag enables bundles)

## What it does

A linear pipeline: **collect → normalize/dedupe → filter → rank → output**.

```
sources ──┐
Epic API  ├─► collectors ─► normalize ─► filter ─► rank ─► markdown report
Steam     │    (adapters)    +dedupe     (acceptance (score)  + free_games.json
r/FGF     ├─► raw candidates ─► canonical  criteria)  ─►      reports/free-games-<date>.md
GOG       ┘                  records     ─► passing
```

- **Collectors** (v1): [Epic](#1-epic) `freeGamesPromotions` API, [Steam](#2-steam) `appdetails` paid→free
  change-tracking, [GOG](#3-gog) catalog API, plus [r/FreeGameFindings](#4-reddit) community feed.
- **Filter** enforces the acceptance contract: full base game, had MSRP > 0 before the promo,
  currently $0 / free-to-keep, keep-not-play action. See `filter.py` for the exact logic.
- **State**: a SQLite `state.db` records previously-seen promotions so a re-run reports only
  **new / changed** items (no duplicate alerts) and persists Steam `is_free` snapshots for
  paid→free flip detection.
- **Output**: a markdown report (primary deliverable) plus a machine-readable `free_games.json`.

## Document trail (research → spec → validation)

This repo is the deliverable of a kanban decomposition chain. Supporting docs:

| Doc | What it is |
|---|---|
| `docs/research_brief.md` / `.json` | Market research: every storefront's free-giveaway signal, update cadence, 11 filtering pitfalls, 11 paid→free examples (Epic/Steam/GOG API-verified) |
| `docs/workflow_spec.md` | Implementation spec: acceptance criteria, 15-field data model, 5-stage pipeline, scheduling options |
| `docs/validation-report.md` | End-to-end validation vs live sources: 2 games captured, 10/10 F2P excluded, dedupe verified, gaps documented |
| `docs/findings/0000..0004-*.md` | Reviewer findings: F2P-exclusion clean, Steam watchlist coverage gap, Reddit SPOF, limited-window giveaways, state retention |

Current live status (as of validation): captures Epic weekly giveaways reliably; Steam paid→free detection is limited to the curated `watched_appids` list; Reddit r/FGF is degraded (HTTP 403 → degrades gracefully). Remediation is tracked on the kanban board (task t_bc280c87).

## Quick start

```bash
pip install -r requirements.txt

# Full pipeline (collect → normalize → filter → rank → report) with live sources
python main.py --config config.yaml

# Offline run from a saved snapshot (no network) — handy for CI/tests
python main.py --config config.yaml --offline

# Show options
python main.py --help
```

The report lands in `reports/free-games-<date>.md` and passing records in
`reports/free_games.json` (both gitignored; see `examples/` for committed sample
output). The report shows two sections:

- **This week (limited-time free-to-keep)** — e.g. Epic's weekly giveaways.
- **Permanent paid→free conversions** — e.g. Steam titles that flipped to F2P.

A committed sample report (from the offline fixture snapshot) is in
`examples/sample-report.md`.

## Environment variables

The core pipeline runs with **no credentials and no environment variables** —
all collectors use public, unauthenticated APIs and the default notification
is a file/stdout write. **Nothing is read from the environment** by the current
code, so there is no API key, Telegram bot token, or secret to set to get
started.

Optional, if you wire up notification delivery yourself:

| Variable | Purpose |
|---|---|
| *(any)* | `notify.py::notify_all(records, config)` is the single insertion point for chat/email/webhook delivery. If you add an adapter that authenticates, read your tokens/settings from the environment there — never hard-code them, and never commit them. `config.yaml`, the `.gitignore` (`.env`), and this README all assume secrets live outside the repo. |

To keep secrets out of the repo, put any real credentials (Telegram bot token,
webhook URL, etc.) in an `.env` file (gitignored) and load them only inside
your `notify_all` adapter.

## Filter logic (the important part)

A game passes only if **all** of the following hold and are backed by *observed* data:

1. **Is a full standalone base game.** Type is `BASE_GAME` / `game`; not a demo, trial,
   playtest, beta, prologue, showcase, benchmark, DLC, add-on, or "Starter Edition".
   Title tokens such as `demo`, `trial`, `playtest`, `beta`, `prologue`, `showcase`,
   `benchmark`, `friend's pass`, `starter edition` are rejected case-insensitively.
2. **Was paid before the promo** (`original_price > 0`). Native F2P titles (never paid) FAIL
   this — this is the single most important discriminator. For Steam, we require a persisted
   `is_free: False → True` flip (a single `is_free=True` snapshot can't distinguish native F2P).
3. **Is currently offered at $0 / "Free"/"Add to Library for Free"**.
4. **Is a *keep* action**, not a temporary *play* action (free weekend / trial rejects).
5. Not subscription-gated **unless** `allow_sub_gated: true`.

Run `pytest` to see the full set of border cases covered by the unit tests.

## Source adapters

### 1. Epic
Unofficial-but-public JSON API (no auth): `freeGamesPromotions`. We read
`searchStore.elements[]` and emit giveaways where a `promotionalOffers` (current) or
`upcomingPromotionalOffers` (upcoming week) block has `discountPercentage == 0` and product
`offerType == BASE_GAME`. Deterministic weekly (Thursday ~15:00 UTC).
`confidence=high` (official store API).

### 2. Steam
No single "became free today" API, so we **track change over time** via the public
`appdetails` API. For each watched appid we persist `is_free` + `price_overview.final` in
`state.db`. When a prior snapshot had `is_free == False` with `final > 0` and the current
snapshot has `is_free == True` (or no price), we emit a **permanent paid→free conversion**
(`original_price` = the prior `final`). A title that has always been free (`is_free=True`
with no prior paid snapshot) is treated as native F2P and rejected.
`confidence=high`.

### 3. GOG
`catalog.gog.com/v1/catalog` — we scan for products whose current price is `0` and which have
a **paid base price** (`price.baseMoney.amount > 0` before discount / listed MSRP). GOG's free
bucket is dominated by permanently-free titles, so most records fail criterion 2 and are
filtered out; only genuine paid→free (or giveaway) items survive. `confidence=medium`.

### 4. r/FreeGameFindings
Community gold standard. `https://www.reddit.com/r/FreeGameFindings/hot.json` — we parse the
post titles/flairs for free-to-keep giveaways across all stores. Human-curated, so
`confidence=medium`; filtered by the same filter contract. Reddit sometimes rate-limits
unauthenticated JSON, so failures degrade gracefully (the adapter logs and returns `[]`).

## Configuration (`config.yaml`)

See `config.yaml` for all options:

| Key | Meaning | Default |
|---|---|---|
| `currency_base` | Base currency for prices | `USD` |
| `allow_bundles` | Include `BUNDLE` giveaways | `false` |
| `allow_sub_gated` | Include subscription-gated giveaways (Prime) | `false` |
| `min_original_price` | Drop 99¢ shovelware below this MSRP | `0` |
| `sort_mode` | `score` \| `newest` \| `value` | `score` |
| `collectors.*` | Enable/disable each source adapter | epic/steam/reddit on, gog off by default |
| `steam.watched_appids` | AppIDs to change-track | curated seed |
| `notify.output_dir` | Where reports go | `reports/` |
| `state_db` | Path to the state database | `state.db` |

## Scheduling / automation

All three options invoke the same `python main.py --config config.yaml` entrypoint.

### A. GitHub Actions (recommended — see `.github/workflows/free-games.yml`)
Runs on a schedule (Thu 15:05 UTC right after Epic's weekly drop + a daily digest) and on
`workflow_dispatch`. It installs deps, runs the pipeline, uploads `reports/` as a build
artifact and commits the markdown report back to the repo so you get a git history of finds.

### B. Local cron (self-hosted, e.g. this WSL box)
```cron
# Every Thursday 15:05 UTC (after Epic weekly) + daily morning digest
15 15 * * 4   /usr/bin/python3 /path/to/main.py --config config.yaml >> /var/log/free-games.log 2>&1
30 9 * * *    /usr/bin/python3 /path/to/main.py --config config.yaml --digest-only >> /var/log/free-games.log 2>&1
```
State survives on disk in `state.db`.

### C. Serverless (cron-triggered function)
Point a cron-triggered function at `main.py`. Because serverless instances are ephemeral,
keep `state.db` (and the reports dir) in object storage (S3/GCS) rather than local disk.

## Notifications

The CLI writes the markdown report and `free_games.json`. For chat/email delivery, extend
`notify.py` (`notify_all(records, config)` is the insertion point) or point a webhook at the
produced JSON. See `main.py --notify` for the hook.

## Testing

```bash
pytest -q
```

- `tests/` covers the **filter** border cases (F2P rejection, demo/trial/beta/prologue tokens,
  ADD_ON/DLC/BUNDLE types, free-weekend temp access, current-price checks, sub-gating),
  **dedupe** (same title via two feeds → one record, highest confidence, latest end-date),
  and **idempotency** (run twice on the same snapshot → identical report, no duplicate
  "new" alerts).
- A `--offline` mode lets tests and CI run the whole pipeline from a saved fixture snapshot
  without network access.

## Project layout

```
main.py                 CLI entrypoint
config.yaml             Configuration (copy to your own; never commit secrets)
requirements.txt        Dependencies
free_games_tracker/
  __init__.py
  model.py              Canonical record dataclass + constants
  config.py             Config loading / validation
  httpclient.py         Thin HTTP helper (timeouts, retries, UA)
  collectors/
    __init__.py
    epic.py             Epic freeGamesPromotions API
    steam.py            Steam appdetails paid→free flip change-tracking
    gog.py              GOG catalog API
    reddit.py           r/FreeGameFindings JSON
  sample_data.py        Fixture snapshot harness + sample records for offline runs/tests
  normalize.py          Field mapping → canonical + dedupe
  filter.py             Acceptance criteria (§ Filter logic)
  rank.py               Weighted scoring / ordering
  report.py             Markdown report renderer
  notify.py             Notification dispatcher (file/stdout + notify hook)
  state.py              SQLite state (seen promotions; Steam snapshots)
  pipeline.py           Orchestrates collect→normalize→filter→rank→state→report
tests/
  test_filter.py        Filter border cases
  test_dedupe.py        Dedupe across feeds
  test_idempotency.py   Re-run no-dup-alert behaviour
  test_pipeline.py      End-to-end offline pipeline + report shape
  fixtures/             Saved API snapshots for offline runs
scripts/
  seed_steam_watchlist.py  Inspect/seed watched Steam appids
.github/workflows/
  free-games.yml        Scheduled GitHub Actions workflow
```

## Notes on correctness

- **Idempotency / no-double-report**: `state.db` stores seen `game_id + end_date + free_since`.
  A re-run on identical data produces an identical report and treats already-seen items as a
  "still free" rollup, not as new alerts (verified by `test_idempotency.py`).
- **Steam paid→free is only honest via change tracking.** A single `is_free=true` snapshot
  cannot distinguish native F2P from a conversion, so the Steam adapter never assumes prior
  paid status without a stored paid snapshot.
- Prices are normalized to USD where the source provides a currency code; other currencies are
  carried through with their original currency code.
```
