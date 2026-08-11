# Workflow Specification: Detecting Paid Games That Became Free

**Spec ID**: t_1d0cf1f2
**Author**: specifier profile
**Date**: 2026-08-09
**Status**: Ready for implementation
**Upstream input**: `research_brief.md` / `research_brief.json` (from researcher task t_773b30fe)

This document is a complete, self-contained implementation spec. An implementer can build the workflow from this file alone without re-running research. All source endpoints, acceptance logic, data-model fields, pipeline stages, and deployment options are specified below.

---

## 1. Goal

Detect PC games that were **normally-priced (paid)** and **became available for free** (permanently free-to-keep giveaways and permanent paid→free conversions), and report them to the user with enough metadata to act on (claim link, original price, window).

The system does NOT report:
- Always free-to-play (F2P) games
- Games merely on a free-weekend / free-trial / timed access
- Demos, betas, playtests, prologues, showcases, benchmarks
- DLC, add-ons, "Starter Edition" packs, in-game content, bundles (unless explicitly opted in)
- Subscription-lending (Game Pass / Prime lending) unless the subscription-gated giveaway is intentionally in scope

---

## 2. Acceptance Criteria for a Game (the filter contract)

A game **passes** only if ALL of the following hold **at the moment of evaluation** and are backed by an observed (not assumed) data signal:

1. **Is a full, standalone game.**
   - Product type is a base game (`BASE_GAME` on Epic; type `game` on Steam; standalone product on GOG/itch).
   - NOT: F2P-only, demo, trial, beta, playtest, prologue, showcase, benchmark, DLC, add-on, in-game item, or "Starter Edition".
   - Title token blocklist (case-insensitive): `demo`, `trial`, `playtest`, `beta`, `prologue`, `showcase`, `benchmark`, `testing`, `friend's pass`, `starter edition`.
   - `offerType` must be `BASE_GAME` (exclude `ADD_ON`, `DLC`, `BUNDLE` unless a feature flag enables bundles).

2. **Had a measurable paid price (MSRP > 0) before the promotion.**
   - Evidence: a prior snapshot or an aggregator claim showing `original_price > 0` (local currency) immediately before the free event.
   - Native F2P titles (never had `price > 0`) FAIL this check. This is the single most important discriminator.
   - For Steam paid→free conversions, require a persisted `is_free: False → True` flip (see §5.3). A single `is_free=True` snapshot is INSUFFICIENT to prove prior paid status.

3. **Is currently offered at $0 / "free" / "free to keep".**
   - Current price signal is exactly `0` (or an explicit "Free" / "Add to Library for Free" / "Free to Keep" state).
   - The current offer must be a **keep** action, not a temporary **play** action:
     - "Add to Library" / "Add to Account" / "Claim" = keep.
     - "Play now" / "Free Weekend" with a defined start/end = temporary access → FAIL.

**Decision flow (pseudocode):**

```
def passes(game):
    if not game.is_full_game:            return False   # criterion 1 (+ tokens, offerType)
    if not game.prior_paid_price > 0:     return False   # criterion 2 (MSRP>0 evidence)
    if game.current_price != 0:            return False   # criterion 3 (free right now)
    if not game.is_keep_action:            return False   # criterion 3 (keep vs play)
    if game.is_sub_gated and not cfg.allow_sub_gated: return False  # Prime etc. policy flag
    return True
```

Optional policy flags (defaults shown):
- `allow_bundles = false` — include `BUNDLE` giveaways (e.g. Tomb Raider I–III) if true.
- `allow_sub_gated = false` — include subscription-gated giveaways (e.g. Prime Gaming claims) if true.
- `min_original_price = 0` — lower bound on original price to filter out 99¢ shovelware if desired.

---

## 3. Data Model (canonical record)

One JSON object per game event. Field names are final; an implementer should use these verbatim in code, JSON schema, and DB schema.

| Field | Type | Required | Description / Example |
|---|---|---|---|
| `game_id` | string | yes | Stable dedupe key: `<store>|<title-normalized>` (or store-internal app/product id, e.g. `epic|<offerId>`, `steam|<appid>`, `gog|<productId>`). |
| `title` | string | yes | Display title, e.g. "We Were Here Together". |
| `store` | enum | yes | One of: `steam`, `epic`, `gog`, `prime`, `itch`, `aggregator`. |
| `store_url` | string | yes | Claim/storefront URL, e.g. `https://store.epicgames.com/en-US/p/<slug>`. |
| `offer_url` | string | yes | Direct claim/offer link (giveaway page or store price page). |
| `original_price` | number | yes (USD preferred; store that stores local)` | Pre-promotion MSRP, > 0. e.g. 17.99. |
| `original_price_currency` | string | yes | ISO code, e.g. `USD`. |
| `free_since` | string (ISO-8601) | yes | UTC timestamp of observed free detection, e.g. `2026-08-06T15:00:00Z`. |
| `promotion_window` | string | yes | Human descriptor: `480h` window, `48h` limited, or `permanent`. |
| `end_date` | string (ISO-8601) | no | End of claim window. Absent/`null` = permanent (paid→free conversion). e.g. `2026-08-13T15:00:00Z`. |
| `is_permanent` | bool | yes | `true` if permanent conversion; `false` if limited claim window. Derivable: `end_date` null ↔ permanent. |
| `image_url` | string | no | Box/capsule art URL (for rich notifications / reports). |
| `gate` | enum | no | `none` or `subscription` (e.g. Prime requires active Prime). Absent = none. |
| `source_feed` | string | yes | Which collector produced it, e.g. `epic_freeGamesPromotions`, `r_fgf`, `steam_appdetails_flip`. |
| `detected_at` | string (ISO-8601) | yes | Wall-clock time the collector stored the record. |
| `confidence` | enum | yes | `high` (official API), `medium` (aggregator/manual), `low` (heuristic/partial). |

**Dedupe key rule:** `game_id` must be stable across runs. When the same title appears via multiple feeds (e.g. Epic API + r/FGF), dedupe to ONE record, preferring the highest-confidence `source_feed` and resolving `end_date` to the most conservative (latest) value.

---

## 4. Pipeline Stages

The workflow is a linear pipeline with **collect → normalize → filter → rank → output**. Each stage is idempotent and re-runnable on the same snapshot without double-counting (see §4.6).

```
            ┌────────────┐
 incoming ─▶│  1. COLLECT │──▶ raw candidates
            └────────────┘            │
                                      ▼
            ┌──────────────┐
            │ 2. NORMALIZE │──▶ canonical records
            │   + DEDUPE   │
            └──────────────┘            │
                                      ▼
            ┌────────────┐
            │ 3. FILTER   │──▶ passing games (per §2)
            └────────────┘            │
                                      ▼
            ┌────────────┐
            │ 4. RANK     │──▶ ordered list (per §4.4)
            └────────────┘            │
                                      ▼
            ┌─────────────┐
            │ 5. OUTPUT   │──▶ markdown report / email / chat
            │ + NOTIFY    │
            └─────────────┘
```

### 4.1 Collect — source adapters

Collect candidates from the following adapters. **Implement these in priority order** — items marked `[v1]` give the most value-per-effort; the rest are enhancements.

| # | Adapter | Feed / endpoint (from research brief) | Free signal | Cadence | Version |
|---|---|---|---|---|---|
| 1 | **Epic** | `https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US` | `promotionalOffers` / `upcomingPromotionalOffers` blocks with `discountPercentage == 0` | Weekly, deterministic (Thu 15:00 UTC) | **v1** |
| 2 | **r/FreeGameFindings** | `https://www.reddit.com/r/FreeGameFindings/hot.json` (public JSON) | Human-curated giveaway posts; flairs "given / previously given / f2p to paid / tasks" | Continuous | **v1** |
| 3 | **Steam paid→free flip** | `https://store.steampowered.com/api/appdetails?appids=<appid>&cc=us` — persist `is_free` + `price_overview` per appid | `is_free` False→True flip on an appid with a prior `price_overview.final > 0` | Poll existing watchlist + subscribe to steamdb/upcoming/free | **v1** |
| 4 | **gg.deals freebies** | `https://gg.deals/news/freebies/` (+ `/news/free-gog-games/`) | Curated free-to-keep lists with expiry | Continuous | v2 |
| 5 | **GOG** | `https://catalog.gog.com/v1/catalog?price=free` + giveaway news | price `0`; cross-check against giveaway announcements (free bucket is mostly always-free → won't pass criterion 2) | Sporadic | v2 |
| 6 | **SteamDB** | `https://steamdb.info/upcoming/free/` (browser-driven; anti-bot behind JS | Free-to-keep + free-weekend with expiry | Continuous | v2 |
| 7 | **freeToKeep.gg** | `https://freetokeep.gg/` | Server-fetched aggregated free-to-keep across stores | Near-real-time | v3 |
| 8 | **Prime Gaming / Luna** | `https://luna.amazon.com/claims/home` (auth-gated) | "Claim" cards; requires active Prime | Monthly, weekly batches | v3 (opt-in, policy flag `allow_sub_gated`) |
| 9 | **itch.io** | `https://itch.io/games/on-sale` (poll + diff price) | price drops to 0 via 100% sale; needs price history diff | Continuous | v3 (lowest value) |

**Collector contract:** each adapter outputs a flat list of raw candidate objects with at least: store, title, current price, offer/claim metadata, URLs, detected_at.

### 4.2 Normalize + dedupe

- Map raw fields → canonical `game_id`, `title` (trimmed, case-collapsed for matching but kept in display form), `store` enum, prices in a **single base currency** (recommend USD; a configurable FX rate table or store-provided price). Store original and current price in base currency plus the original currency code.
- Normalize store names to the enum; strip title whitespace/punctuation; drop trailing " - Free to Keep" suffix.
- **Dedupe** on `game_id`. Merge records from multiple feeds:
  - Keep highest `confidence`.
  - `end_date` → resolve to the **latest** (most permissive) observed end date.
  - `original_price` → prefer the larger, earliest-observed paid price (avoid a stale free price leaking in).
  - `source_feed` → concatenate feeds that confirmed it.
- Idempotency: the output of this stage for a given input snapshot is deterministic.

### 4.3 Filter — apply §2 acceptance criteria

Run `passes(game)` from §2 on every normalized record. Output only passing games. Records failing a criterion may be logged for diagnostics (criterion they failed) but are excluded from the report. Log reason codes: `not_full_game`, `demo/trial`, `f2p_never_paid`, `not_free_currently`, `temp_access_only`, `sub_gated_flagged`.

### 4.4 Rank / order

Present games in a deterministic order. Default ranking (score = sum of weighted signals, higher first):

| Weight | Signal |
|---|---|
| +200 | Permanent conversion (`is_permanent == true`) — highest value, no expiry pressure |
| +60  | `original_price` scaled log: `60 * log10(original_price)` (rewards more valuable titles) |
| +40  | Newest first: `+40 * (1 - hours_since_free_since / 168)` clamped to [0,40] — recent is valuable |
| -40  | Confidence penalty: `high`=0, `medium`=-20, `low`=-40 |
| -25  | Requires subscription gate (`gate == 'subscription'`) |

Sort descending by score. Ties broken by `free_since` (newest first), then `title` alphabetically.

Optional user override: `--sort newest` (pure `free_since` desc) or `--sort value` (pure `original_price` desc) to replace the default weighted score.

### 4.5 Output + notify

Produce a **markdown report** (primary deliverable) then optionally push notifications. Default: emit markdown report to stdout/file; if a notifier is configured, send the digest.

Markdown report template:

```markdown
# Free game alert — <date>

<N> normally-paid games are now free.

## This week (limited-time claims)
| Game | Store | Was | Free until | Claim |
|---|---|---|---|---|
| We Were Here Together | Epic | $17.99 | 2026-08-13 | [link](offer_url) |

## Permanent paid→free conversions
| Game | Store | Was | Free since | Link |
|---|---|---|---|---|
| GRIT | Steam | — | 2026-05-01 | [link](offer_url) |

_Generated by <pipeline>. Sources: <source feeds>._
```

Notification adapters (configurable, at least one):
- **Chat message** (Telegram/Discord/Slack): the markdown table rendered as a platform-friendly message (reuse existing gateway if present).
- **Email**: render markdown to HTML/text and send via an SMTP/`resend` provider.
- **Plain file / webhook**: write markdown to `reports/free-games-<date>.md` and/or POST JSON to a webhook.

The JSON records that passed the filter may optionally be emitted as `free_games.json` next to the markdown for downstream consumption.

### 4.6 Idempotency / no-double-report

- The pipeline stores **seen `game_id` + `end_date` + `free_since`** in a small state file/DB (`state.db`). Only games that are NEW since the last run, or whose `end_date` changed, are included in "new/updated" section of a report.
- Re-runs on the same snapshot must produce identical output (pure functions per stage aside from network fetch).
- A currently-free game already reported last run appears in a "still free" rollup, not as a new alert, unless a field changed.

---

## 5. Architecture

### 5.1 ASCII architecture diagram

```
                        ┌───────────────────────────────────────────────┐
                        │                    SOURCES                    │
                        │  Epic freeGamesPromotions API (official JSON)   │
                        │  Steam appdetails API  ·  GOG catalog API       │
                        │  r/FreeGameFindings JSON · gg.deals · SteamDB   │
                        │  freeToKeep.gg · Prime/Luna (opt-in, auth)      │
                        └───────────────┬───────────────────────────────┘
                                        │ HTTP / JSON (no-auth where possible)
                                        ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │                    COLLECTORS  (one adapter per source)         │
        │   epic_adapter.py  steam_flip.py  reddit_adapter.py  gog.py ... │
        └───────────────────────────────┬─────────────────────────────────┘
                                        │ raw candidate objects
                                        ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │                     NORMALIZE + DEDUPE  (normalize.py)          │
        │   map→canonical fields · single currency · merge dupes          │
        └───────────────────────────────┬─────────────────────────────────┘
                                        │ canonical records
                                        ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │                       FILTER  (filter.py — §2 criteria)         │
        │   full-game? · MSRP>0 evidence? · currently $0? · keep? · gate? │
        └───────────────────────────────┬─────────────────────────────────┘
                                        │ passing games
                                        ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │                  RANK + STATE  (rank.py · state.db)             │
        │   weighted score · dedupe vs seen · compute new/updated          │
        └───────────────────────────────┬─────────────────────────────────┘
                                        │ ordered list
                                        ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │              OUTPUT + NOTIFY  (notify.py · report.py)           │
        │   markdown report  ·  Telegram/Discord/Slack  ·  email  · file   │
        └───────────────────────────────┬─────────────────────────────────┘
                                        ▼
                           reports/free-games-<date>.md  (+ free_games.json)
```

### 5.2 Component responsibilities

| Component | Responsibility | Notes |
|---|---|---|
| Source endpoints | Provide raw data | Only Epic appdetails, catalog API, aggregator JSON are no-auth. |
| Collectors | One script per source; fetch + normalize to raw candidates | Keep read-only; run in parallel. |
| `normalize.py` | Field mapping, currency, dedupe | Deterministic pure transform. |
| `filter.py` | Apply §2 acceptance criteria | Pure, testable; unit-test each border case (§6). |
| `rank.py` + `state.db` | Score/order; track seen games for idempotency | SQLite or JSON state file is fine. |
| `report.py` / `notify.py` | Render markdown; dispatch to adapters | At least one notifier required for a useful alert. |
| `config.yaml` | API keys, currency, policy flags (§2), notifier targets, sort mode | No secrets committed. |

### 5.3 Explicit note on Steam paid→free detection

The only honest way to detect a Steam paid→free conversion is **change tracking**:
- Persist per-appid `is_free`, `price_overview.final`, and timestamp in `state.db`.
- On each run, for each watched appid: if prior snapshot had `is_free == False` and `price_overview.final > 0`, and current snapshot has `is_free == True` (or `price_overview` absent) → emit a **permanent conversion** candidate (`is_permanent=true`, original price = prior `final`).
- `is_free=true` with **no prior `final > 0` snapshot** is assumed native F2P → filtered out by criterion 2.
- Seed the watchlist from: SteamDB `/upcoming/free/` (browser), Steam Community "Free To Keep" group, and any appids already in `state.db`.

---

## 6. Testing / Acceptance for the Implementer

The spec is only "done" when these pass:

1. **Unit tests** for `filter.py` covering every pitfall from the research brief:
   - native F2P `is_free=true`, no price history → rejected
   - paid→free with prior price >0 → accepted (conversion)
   - demo/trial/beta/prologue/benchmark title tokens → rejected
   - `ADD_ON` / `DLC` / `BUNDLE` offerType → rejected (unless `allow_bundles`)
   - free-weekend/trial (temp access) → rejected
   - current price = 0 (free) → accepted
   - current price > 0 → rejected
   - Prime/luna `gate=subscription` with `allow_sub_gated=false` → rejected
2. **Collector smoke tests**: each v1 adapter fetches live and returns ≥1 record. Epic API is the oracle; assert the API contract fields (`promotionalOffers.discountPercentage==0`) parse.
3. **Dedupe test**: feed the same title via Epic API + r/FGF → exactly one output record, highest confidence kept, `end_date` = latest.
4. **Idempotency test**: run twice on identical snapshot → identical report, second run emits no duplicate "new" alerts.
5. **End-to-end run**: execute the full pipeline once and confirm it produces `reports/free-games-<date>.md` with the expected structure and ≥1 passing game (Epic weekly giveaway expected in practice).

---

## 7. Scheduling / Automation Options

Pick one deployment target. All three invoke the same `main.py` entrypoint.

### A. GitHub Actions cron (recommended for portability)
```yaml
# .github/workflows/free-games.yml
on:
  schedule:
    - cron: "15 15 * * 4"    # Thu 15:05 UTC, just after Epic weekly (Thu 15:00 UTC)
    - cron: "30 9 * * *"     # daily morning digest for Steam/GOG/aggregator changes
  workflow_dispatch: {}      # manual trigger

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r requirements.txt
      - run: python main.py --config config.yaml   # emits markdown + json
      # optional: push report as artifact / post to a webhook
      - uses: actions/upload-artifact@v4
        with: { path: reports/ }
```
- Pros: no infra to babysit, git history of reports, cron handled by GitHub. Cons: needs a repo; scheduler availability is fine for a daily/weekly cadence.

### B. Local cron (simple, self-hosted)
```cron
# Every Thursday 15:05 UTC + daily morning digest; log to file
15 15 * * 4   /usr/bin/python3 /path/to/main.py --config config.yaml >> /var/log/free-games.log 2>&1
30 9 * * *    /usr/bin/python3 /path/to/main.py --config config.yaml --digest-only >> /var/log/free-games.log 2>&1
```
- This Hermes host is WSL; the cron runs on the WSL instance (user has existing `/etc/cron.d` or `crontab -e`). Pros: no external dep. Cons: machine must be on; state survives in `state.db` on disk.

### C. Serverless (cron-triggered function)
- AWS Lambda / Cloud Functions / Cloudflare Workers with a cron trigger, or Hermes' own `cronjob` tool for agent-driven runs.
- Store `state.db` in object storage (S3/GCS) or a small DB since serverless instances are ephemeral.
- Pros: no always-on server, run anywhere. Cons: more setup (IAM, state persistence), outbound network to store APIs.

---

## 8. Configuration Sample (`config.yaml`)

```yaml
currency_base: USD
allow_bundles: false
allow_sub_gated: false
min_original_price: 0
sort_mode: score        # score | newest | value
collectors:
  epic: true
  steam_flip: true
  reddit: true
  ggdeals: false
  gog: false
  steamdb: false
  freetokeep: false
  prime: false
  itch: false
epic:
  locale: en-US
  country: US
steam:
  cc: us
  watched_appids: []     # seed list; steam_db_seed: true to auto-watch SteamDB upcoming
notify:
  chat: {}               # e.g. telegram {token, chat_id} via existing gateway
  email: null
  output_dir: reports/
state_db: state.db
```

## 9. Out of Scope (explicitly not implemented in v1)

- Auth-gated sources (Prime/Luna scraping with real credentials) — out of scope; use aggregators or opt in later.
- itch.io price-history crawling — lowest value; deferred.
- Bundle/DLC giveaways in the default report (flag `allow_bundles` exists).
- Mobile/Android-only giveaways.
- Region-specific eligibility enforcement beyond sampling `country=`/`cc=` (tag region, don't hard-block).

---

## 10. Deliverable Files (that an implementer should produce)

- `free_games_tracker/` python package: `main.py`, `collectors/*.py`, `normalize.py`, `filter.py`, `rank.py`, `report.py`, `notify.py`, `config.yaml`, `requirements.txt`
- `tests/` unit + smoke tests (see §6)
- `reports/` output directory
- `README.md` describing the three scheduling options (§7) and config
- CI file for GitHub Actions schedule (§7A) if hosted on GitHub
