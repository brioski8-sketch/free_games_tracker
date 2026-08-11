"""Steam collector — paid→free conversion change-tracking.

There is no single "became free today" API on Steam, so we *change-track* the
public `appdetails` API (fetched one appid per request — the API rejects
comma-separated appids with HTTP 400):

    https://store.steampowered.com/api/appdetails?appids=<appid>&cc=us&l=en

For each watched appid we persist `is_free` + `price_overview.final` across runs
in `state.db` (the `steam_snapshots` table). When a prior snapshot had:

    is_free == False  AND  price_overview.final > 0

and the CURRENT snapshot has:

    is_free == True   (or price_overview absent)

we emit a **permanent paid→free conversion** (original_price = the prior `final`).

A title that is free but has NO prior paid snapshot is treated as native F2P and
is NOT emitted here (the filter would reject it anyway — we skip the wasted work).

`confidence = high` (official store API).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List

from ..httpclient import FetchError, fetch_json

API = "https://store.steampowered.com/api/appdetails"

# Curated seed of appids worth change-tracking — extensible via `steam.watched_appids`
# in config. Includes historically-paid titles that went F2P plus nav anchors used
# by the rejection tests. Treat as a starting point, not the whole watchlist.
DEFAULT_WATCHLIST = [
    340580,   # change-track to observe paid→free status
    513710,
    1158310,  # free-to-keep / conversion candidate
    1238840,
    1174180,
]


def collect(cfg: Dict[str, Any], state) -> List[Dict[str, Any]]:
    """Return candidate conversions by comparing prior vs current appdetails.

    state must be a StateStore with get_steam_snapshot / put_steam_snapshot.
    """
    steam_cfg = cfg.get("steam") or {}
    cc = steam_cfg.get("cc", "us")
    watched = list(steam_cfg.get("watched_appids") or DEFAULT_WATCHLIST)
    # always include anything already tracked so we keep flipping endpoints fresh
    tracked = state.all_steam_appids()
    watched = list(dict.fromkeys(watched + tracked))
    if not watched:
        return []

    http = cfg.get("http") or {}
    out: List[Dict[str, Any]] = []
    now_iso = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for appid in watched:
        url = f"{API}?appids={appid}&cc={cc}&l=en"
        try:
            payload = fetch_json(url, timeout=http.get("timeout", 20), retries=http.get("retries", 2))
        except FetchError:
            continue  # degrade gracefully; snapshot persistence is best-effort

        data = (payload or {}).get(str(appid)) or {}
        if not isinstance(data, dict) or not data.get("success"):
            continue
        info = data.get("data") or {}
        name = (info.get("name") or f"steam/{appid}").strip()
        is_free = bool(info.get("is_free", False))
        price_ov = info.get("price_overview") or {}
        final_cents = price_ov.get("final")
        final = round(float(final_cents) / 100.0, 2) if final_cents is not None else None
        currency = price_ov.get("currency") or "USD"

        prior = state.get_steam_snapshot(appid)
        state.put_steam_snapshot(appid, is_free, final, currency, now_iso)

        if prior and prior.get("is_free") is False and is_free and (prior.get("final") or 0) > 0:
            out.append({
                "store": "steam",
                "appid": appid,
                "title": name,
                "offer_type": info.get("type"),
                "current_price": 0.0,
                "current_currency": currency,
                "original_price": round(float(prior.get("final") or 0), 2),
                "original_price_currency": prior.get("currency") or currency,
                "is_free_now": True,
                "end_date": None,            # permanent conversion
                "promotion_window": "permanent",
                "is_permanent": True,
                "store_url": f"https://store.steampowered.com/app/{appid}",
                "offer_url": f"https://store.steampowered.com/app/{appid}",
                "image_url": None,
                "source_feed": "steam_appdetails_flip",
                "detected_at": now_iso,
                "confidence": "high",
                "keep_action": True,
            })
    return out
