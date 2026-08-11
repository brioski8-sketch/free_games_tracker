# Research Brief: PC Game Storefronts That Periodically Offer Normally-Paid Games For Free

**Researcher**: Echo (researcher profile)
**Date**: 2026-08-09
**Scope**: Major PC storefronts where users can *permanently* add normally-paid games for free (free-to-keep giveaways and paid→free conversions). Deliberately excludes always-free-to-play (F2P) games, demos, trials, playtests, DLC, and game-pass/subscription lending unless noted.

---

## Executive Summary

Six storefronts / ecosystems are the primary sources of "paid game becomes free-to-keep" events:

1. **Steam** (Valve) — irregular publisher-initiated free-to-keep giveaways + occasional permanent paid→free conversions.
2. **Epic Games Store** — *the* flagship source: a free game every week, every Thursday, since Dec 2018.
3. **GOG** — small permanent "always free" catalog + sporadic 48-hour limited giveaways during sales/campaigns.
4. **Amazon Prime Gaming / Amazon Luna** — monthly claims for active Prime subscribers (rebranded from gaming.amazon.com to luna.amazon.com).
5. **itch.io** — indie marketplace where creators set 100%-off sales (temporary free) at will; no centralized weekly program.
6. **Community aggregators** (r/FreeGameFindings, gg.deals, SteamDB, freeToKeep.gg, GamerPower) — *the most reliable machine-readable way* to harvest these events across all stores.

**Critical finding for automation**: None of the storefronts' raw "free" filters can distinguish a *temporarily-free-to-keep giveaway* from a *permanently F2P game*, a *demo*, or a *trial*. Programmatic detection therefore requires either (a) tracking a price/`is_free` *change over time*, or (b) consuming community/aggregator feeds that curate giveaways explicitly. This is documented per-store in the Filtering Pitfalls section.

---

## Per-Source Details

### 1. Steam (store.steampowered.com)

- **Nature**: Two distinct events:
  - **Free-to-keep giveaways**: Publisher sets the paid game to 100% off for a limited window (typically a few days to a week); once claimed, it stays in the library forever. These appear on the store page as a standard discounted price of **$0 / "Free"** with a "Limited time offer" note. Typ. go live around **17:00 UTC**.
  - **Permanent paid→free conversions**: Developer permanently flips a paid game to F2P (e.g., *Crusader Kings II* in Oct 2019, *Metro 2033*) — common for old multiplayer games or titles about to be delisted.
- **Official access**:
  - Store search: `https://store.steampowered.com/search/?price=0&os=win` (returns the "free" bucket; currently ~2,656 results, heavily polluted with F2P/demos).
  - Storefront pages: `https://store.steampowered.com/app/<appid>`
  - **`appdetails` API** (no key, public): `https://store.steampowered.com/api/appdetails?appids=<appid>&cc=us&l=en` — returns `data.is_free` (bool) and `data.price_overview` (omitted when free).
  - Steam News search feed: `https://store.steampowered.com/news/search/?term=free+to+keep`
  - **SteamDB** (community, authoritative for prominence): `https://steamdb.info/upcoming/free/` — curated "Free to Keep" / free-weekend tracking with expiry countdowns. *(Note: SteamDB's pricing pages currently sit behind a client-side renderer / anti-bot — not directly scrapeable via plain HTTP; use their public API or the /upcoming/free page via a browser engine.)*
  - Steam Community group "Free To Keep": `https://steamcommunity.com/groups/freetokeep/announcements` — daily-updated announcement listing of current free-to-keep offers.
- **Update cadence**: Irregular. Giveaways are publisher-driven (several per week at peak sale season, sometimes zero for days). Permanent conversions happen sporadically (a handful per month).
- **Free detection signal**: `is_free=true` and/or `price_overview` absent. **BUT this is exactly the trap** — see pitfalls.

### 2. Epic Games Store (store.epicgames.com)

- **Nature**: **One to two free-to-keep games every Thursday ~15:00 UTC**, every week since Dec 2018 (~as of Aug 2026 that is 300+ weekly batches). Title is theirs to keep forever after claiming. Occasionally "Mystery Games" events (daily reveals at year-end). Sometimes extra mobile/Android offers.
- **Official access**:
  - Web page: `https://store.epicgames.com/en-US/free-games` (shows current + upcoming weeks).
  - **Official public JSON API** (verified live this run, no auth):
    `https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US`
    → `data.Catalog.searchStore.elements[]` each with `promotions.promotionalOffers` / `.upcomingPromotionalOffers` containing `startDate`, `endDate`, and `discountSetting.discountPercentage` (=0 for free). Rewarded *without* an account (the claim itself needs login).
  - Storefront GraphQL is used by unofficial mirrors too (e.g., GitHub `woicip/epic-free-games`).
- **Update cadence**: Weekly, deterministic, scheduled (Thursday 15:00 UTC; expiry the following Thursday ~15:00 UTC). Upcoming week usually revealed in advance.
- **Free detection signal**: The `freeGamesPromotions` endpoint's `promotionalOffers` blocks with `discountPercentage=0` = genuine price-0 **giveaway** (base game). This is the *cleanest* programmatic feed of any store. (Screenshot of page shows the giveaway under a distinct "Free Giveaway" header.)

### 3. GOG (gog.com)

- **Nature**: Two buckets:
  - **Always-free collection**: a permanent set of ~12,545 DRM-free products (many small/older titles) — these are *never paid*, so do NOT count as "paid became free."
  - **Limited 48-hour giveaways**: during major sales (Summer/Winter) or campaign promotions (e.g., *Freedom to Buy* Aug 2025 gave away 13 delisted/NSFW titles for 48h; *Nexus: The Jupiter Incident* July 2026 free-to-keep).
- **Official access**:
  - Catalog API (public): `https://catalog.gog.com/v1/catalog?limit=…&price=free` returns products priced 0 (the permanent free bucket; 200 pages / 10,000 shown). Does *not* directly expose time-limited giveaways.
  - Free collection page: `https://www.gog.com/en/partner/free_games` (JS-rendered; heavy client-side templating — scrape with a browser or the catalog API instead of plain HTTP).
  - Giveaways are announced via GOG news / storefront banners and are tracked by gg.deals (`/news/free-gog-games/`).
- **Update cadence**: Permanent bucket is stable; giveaways are sporadic (a few per big sale, 48h windows).
- **Free detection signal**: price=0 in the catalog API. Pitfall: the catalog's free bucket is mostly permanently-free titles, so *given-for-free* events need the giveaway-specific sources (gg.deals / GamerPower / r/gog).

### 4. Amazon Prime Gaming / Amazon Luna (luna.amazon.com)

- **Nature**: For **active Prime subscribers only** (~$15/mo or ~$140/yr in the US). **~12 free PC games/month**, released in weekly batches through the month. Claims are codes/rewards that **expire** (typically end-of-month); redeemed games are kept forever. Also includes in-game bundles, loot, and Luna cloud-streaming titles.
- **Official access**:
  - Claims home (rebranded Aug 2026 from `gaming.amazon.com`): **`https://luna.amazon.com/claims/home`** (auth required). Legacy `https://gaming.amazon.com` redirects there.
  - No stable documented public JSON feed; historically an internal JSON was exposed at `gamesdb.prime.amazon.com/util/getGames` but this is **unofficial and may break** — treat as unreliable. Use the claims page (browser) or aggregators.
- **Update cadence**: Monthly, batched weekly. Deterministic enough to poll weekly.
- **Free detection signal**: "Claim" / reward card on the claims page. Requires auth + active subscription (hard blocker for headless scraping without credentials).

### 5. itch.io (itch.io)

- **Nature**: Indie marketplace; **no centralized weekly giveaway program**. Creators can run 100%-off sales making their normally-paid game temporarily free ("set the rate to 100% if you want your content to be temporarily free" — official creator docs). Some creators run permanent 100% offers or long sales (e.g., a 20-year 100%-off sale on a bundle). Because almost everything user-uploaded, many titles are already free/pay-what-you-want.
- **Official access**:
  - On-sale page: `https://itch.io/games/on-sale`
  - Sales hub: `https://itch.io/sales`
  - Creator pricing/sales docs: `https://itch.io/docs/creators/sales` (documents the 100%-off mechanism).
  - No structured public API for "became free today" — must poll the on-sale page or use aggregators.
- **Update cadence**: Continuous / unpredictable.
- **Free detection signal**: price shown as 0 / "Free" via a 100% sale. **No reliable machine-visible flag distinguishing "always was PWYW/free" from "was paid and now temporarily free"** — this is the hardest store to filter programmatically.

### 6. Community Aggregators (recommended machine-readable layer)

These curate exactly the events you care about, across all stores, with expiry metadata:

- **r/FreeGameFindings** (Reddit, ~430k members) — `https://www.reddit.com/r/FreeGameFindings/` — gold standard human-verified feed; flairs include "previously given", "f2p to paid", "tasks". Accessible via Reddit's public JSON (`…/r/FreeGameFindings/hot.json`) or official API.
- **gg.deals** freebies tracker — `https://gg.deals/news/freebies/` and per-store pages (`/news/free-gog-games/`).
- **SteamDB** — `https://steamdb.info/upcoming/free/` (free-to-keep + free weekends with expiry).
- **freeToKeep.gg** — `https://freetokeep.gg/` — fetches official store feeds server-side (~1 min cache), covers Steam/Epic/GOG/Prime/Stove + bundles. Confirmed live; serves current giveaways across stores.
- **GamerPower** — `https://www.gamerpower.com/giveaways` — current free keys/DLC/loot across stores (Steam/GOG/EGS).
- **freeGameFindings.ca** — text-only mirror of the subreddit's finds.

---

## Filtering Pitfalls (spend the most effort here)

The single most important takeaway: **"free == eventually free-to-keep" is FALSE.** A price of zero or a "Free" badge is a necessary-but-not-sufficient signal. You must additionally exclude / distinguish:

1. **Permanently F2P games (always free)** — e.g., *Fortnite, Apex Legends, League of Legends, Marvel Rivals, Path of Exile, Warframe*. These were never paid; including them pollutes the "paid became free" signal. On Steam, `is_free=true` is TRUE for both native F2P *and* converted games (verified: Apex Legends `is_free=True`, Crusader Kings II `is_free=True`) — **you cannot tell them apart from a single snapshot**. You must either (a) track `is_free`/price **over time** (a paid→free conversion flips `is_free` False→True; native F2P was never False), or (b) use a curated list.
   - On Epic, the `free-games` page visually separates "Free Giveaway" (weekly) from "Top Selling / Most Popular / Most Played Free-to-Play" — but the page ships the giveaway *and* the F2P carousels together on one DOM. The `freeGamesPromotions` JSON's `promotionalOffers` block is the giveaway-only signal; F2P titles have no `promotionalOffers`.

2. **Demos / playtests / betas / prologues / showcase builds** — e.g., *Onimusha: Way of the Sword Demo*, *Detroit: Become Human Demo*, *Far Cry 6 FREE Trial*, *HITMAN WOA Free Demo*, "Lords of the Fallen - Free Friend's Pass". On Epic these share the same page filtering as giveaways (the DOM labels them "Demo" / "Trial" / "PlayTest" / "Friend's Pass"). Filter by: title tokens ("Demo", "Trial", "Playtest", "Beta", "Prologue", "Showcase", "Benchmark", "Testing"), and by product/offer *type* where available (Epic `offerType`; Steam's own type field; itch's item nature). Also cross-check original price of the *base game* (demos are free but the base game is not).

3. **Trials / "Free Weekend" / "Play Free" timed access** — *not* permanent adds. Common on Steam ("Free Weekend") and Epic ("Free Trial" / "Play Free"). A free *weekend* or *trial* reverts to paid; a *free-to-keep* giveaway does not. Distinguish by store metadata (Steam "Free Weekend" has a defined `start`/`end`; `price_overview` during the window shows 0) and by "keep vs play" language in the UI ("Add to Library" = keep; "Play" = temporary access; "Add to Account" on Epic = keep).

4. **Add-ons / DLC mislabeled as games** — e.g., the **GOG Wishlist** thread explicitly asks to "exclude demos when searching for free games" and notes only "DLC" is hideable; a free DLC pack (like Epic's "Lost Explorers' Swords Pack") or "Starter Edition" givable is not a standalone game you want counted. Filter to `BASE_GAME` product types (Epic `offerType=BASE_GAME`; Steam type=game) and drop `ADD_ON`/`dlc`/`Starter`.

5. **Bundles / compilations with games you already own** — Epic `offerType=BUNDLE` (e.g., *Tomb Raider I-III Remastered* giveaway) is a legit giveaway but is a bundle, not a single game; decide whether it's in-scope.

6. **Pay-what-you-want / always-free indie titles** on itch.io — no signal to prove "recently became free." Only determinable via price history tracking (polling `on-sale`).

7. **Region/currency variance** — a title may be free in one country but not another (region-locked promos). Sample with `cc=`/`country=` explicitly and note region.

8. **Already-owned masking** — a store won't show "Free to Keep / price 0" twice to an account that already owns it; don't infer "no longer free" from an authenticated account that has the title. Query unauthenticated or track by entitlement.

9. **Fake/abandoned "free" listings & delisting giveaways** — devs sometimes make a game free right before removing it from the store forever (e.g., *MOUTHOLE* case). These are still real free-to-keep events but may be short-lived; mark them as delisting-edge.

10. **"Giveaway minus account/site requirement"** — Prime Gaming requires an active paid subscription; some giveaways require following/store-account *tasks* (r/FreeGameFindings flairs "tasks"). Decide whether subscription-gated free games are in scope.

---

## Concrete Examples: Paid Games That Became Free (recent)

All examples are *normally paid* titles that became claimable/keepable for free. Confidence: sources cited inline.

| Game | Store | When | Original price | How it became free | Source |
|---|---|---|---|---|---|
| **We Were Here Together** | Epic Games Store | Aug 6–13, 2026 | ~$17.99 | Weekly free-to-keep giveaway | Epic `freeGamesPromotions` API (verified live) |
| **Beacon Pines** | Epic Games Store | Aug 6–13, 2026 | ~$19.99 | Weekly free-to-keep giveaway | Epic `freeGamesPromotions` API (verified live) |
| **Caravan SandWitch** | Epic Games Store | Aug 13–20, 2026 (upcoming) | ~$22.99 | Upcoming weekly giveaway | Epic API; GameRant |
| **Ghostrunner 2** | Epic Games Store | Sep 10–24, 2026 (upcoming) | ~$39.99 | Upcoming weekly giveaway | Epic API |
| **Moonlighter** | Steam | Aug 2026 (limited) | ~$24.99 | 100% free-to-keep to celebrate sequel's 1.0 | GameRant / TheGamer |
| **Breathedge** | Steam | Aug 2026 | ~$24.99 | Free-to-keep giveaway | GameRant |
| **Wobbly Heist, Rise of Eurevia, One Death at a Time, The Colors of Love – Re-Colored** | Steam | July 2026 | (were paid) | Permanent paid→free conversions | Archyde/GameRant summary |
| **GRIT** (2025 action roguelite) | Steam | 2026 | (was paid) | Made permanently $0.00 | GameRant |
| **Pong Temple**, **Vivat Sloboda** | Steam | 2026 | Pong Temple ~$3 | Permanent free conversions (several games/month) | VGTimes |
| **Nexus: The Jupiter Incident** | GOG | Jul 3–6, 2026 | ~$9.99 | 48h free-to-keep during Summer Sale | gg.deals / PC Gamer |
| *(Historic reference)* **Crusader Kings II** | Steam | Oct 2019 | $39.99 base | Perm. paid→free (base game) | Steam appdetails; widely documented |

Notes on the examples:
- Epic weekly giveaways are the most reliable, verifiable, and machine-checkable (confirmed this run via the public API).
- Steam permanent conversions (GRIT, Wobbly Heist, etc.) are the purest "paid→free" examples but are irregular and need change-tracking.
- GOG giveaways are short windows (48h) and require sale-season timing.

---

## Implementation Recommendations

1. **Primary automated feed**: Epic `freeGamesPromotions` API (free, no auth, structured, deterministic weekly). Filter to `promotionalOffers.discountPercentage==0`, `offerType==BASE_GAME`, exclude title tokens for Demo/Trial/etc.
2. **Cross-store coverage**: poll r/FreeGameFindings JSON + gg.deals freebies + SteamDB `/upcoming/free/` + freeToKeep.gg to catch Steam/GOG/Prime/itch giveaways that have no clean store API.
3. **Steam paid→free detection**: persist `appdetails.is_free` + `price_overview` snapshots per appid over time; a `False→True` flip of `is_free` (with no prior price series being F2P) = permanent conversion. Cross-check with SteamDB. This is the only honest way to separate conversion from native F2P.
4. **Exclusion list**: maintain a blocklist of native-F2P anchors (game category "Free to Play" and known titles) + DLC/Starter/Bundle/PE offer types + demo/trial title token regex.
5. **Prime Gaming**: requires auth + active sub; either use browser automation against `luna.amazon.com/claims/home` with user credentials (out of scope here) or rely on aggregators.
6. **itch.io**: only practical via on-sale page polling + price-history (poll and diff price over time); lowest automation value.

---

## Open Questions / Gaps

- **No single official "free-to-keep everywhere" API** exists; any robust tracker must fuse 2–4 sources.
- **Prime Gaming has no stable public JSON feed** — the old `gamesdb.prime.amazon.com` endpoint is unofficial and fragile. Exact current-August games list is behind auth (not fetched; community pages confirm the pattern).
- **SteamDB scraping** is blocked from plain HTTP on some pages (JS/anti-bot); confirm a browser-based fetch if SteamDB becomes the Steam source of truth.
- itch.io's "paid but temporarily free" has **no programmatic differentiator** — needs polling-based history.
- Some giveaways are **subscription/task-gated** (Prime; some r/FGF "tasks") — decide scope before building the filter.

---

## Source Index

- Epic API (verified live): `https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US`
- Epic free-games page: `https://store.epicgames.com/en-US/free-games`
- Steam appdetails API (verified live): `https://store.steampowered.com/api/appdetails?appids=<aid>&cc=us`
- SteamDB free / upcoming-free: `https://steamdb.info/upcoming/free/`
- Steam "Free To Keep" community group: `https://steamcommunity.com/groups/freetokeep/announcements`
- GOG catalog API (verified live): `https://catalog.gog.com/v1/catalog?price=free`
- GOG free collection page: `https://www.gog.com/en/partner/free_games`
- Prime/Luna claims: `https://luna.amazon.com/claims/home`
- itch.io sales + creator docs: `https://itch.io/sales` · `https://itch.io/docs/creators/sales`
- r/FreeGameFindings: `https://www.reddit.com/r/FreeGameFindings/`
- gg.deals freebies: `https://gg.deals/news/freebies/`
- freeToKeep.gg: `https://freetokeep.gg/`
- GamerPower: `https://www.gamerpower.com/giveaways`
- GameRant Epic list (history): `https://gamerant.com/epic-games-store-free-games-list/`
- PC Gamer Epic list (history): `https://www.pcgamer.com/epic-games-store-free-games-list/`
