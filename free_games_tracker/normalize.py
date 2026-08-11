"""Normalize raw collector candidates → canonical GameRecord, then dedupe.

Maps store-specific raw shapes to the spec's single canonical data model (§3),
normalizes store names to the enum, strips title junk, converts prices to the
base currency where a currency code is present, and merges duplicate `game_id`s
from multiple feeds (highest confidence, latest end-date, largest earliest price).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .model import GameRecord, STORES, make_id

# Title suffixes / noise to strip before matching.
_TRAILING_SUFFIX = re.compile(
    r"(\s*[-\u2013\u2014]\s*(free to keep|free|trial|demo|beta|early access))$", re.IGNORECASE
)
_WS = re.compile(r"\s+")
_CONF = {"high": 3, "medium": 2, "low": 1}


def _norm_title(title: str) -> str:
    """Case/whitespace-collapsed title for matching; keeps display form separately."""
    t = title.strip()
    t = _TRAILING_SUFFIX.sub("", t)
    return _WS.sub(" ", t).strip()


def _detect_store(raw: Dict[str, Any]) -> str:
    store = (raw.get("store") or "").strip().lower()
    if store in ("epic", "steam", "gog", "itch", "prime"):
        return store
    if store in ("aggregator", "reddit", "aggregator-reddit"):
        return "aggregator"
    if store in ("epic games", "epic games store"):
        return "epic"
    return "aggregator"  # default the unknown to an aggregator-backed record


def normalize(raw: List[Dict[str, Any]]) -> List[GameRecord]:
    records: List[GameRecord] = []
    for r in raw:
        store = _detect_store(r)
        title = (r.get("title") or "").strip()
        if not title:
            continue

        # Stable dedupe key: prefer store-internal id, else normalized title.
        key = r.get("offer_id") or r.get("appid") or r.get("product_id") or r.get("reddit_post_id")
        if not key:
            key = _norm_title(title).lower().replace(" ", "-")
        game_id = make_id(store, key)

        original_price = _to_float(r.get("original_price"))

        end_date = r.get("end_date") or None
        promo_window = r.get("promotion_window") or _guess_window(end_date)
        # Permanent ONLY when the source explicitly says so (Steam paid→free
        # flips set is_permanent=true + window "permanent"). Absent end_date alone
        # must NOT imply permanence — community posts with unknown windows would
        # otherwise be mislabelled as permanent conversions.
        is_permanent = bool(r.get("is_permanent", False)) or promo_window == "permanent"

        records.append(GameRecord(
            game_id=game_id,
            title=_norm_title(title),
            store=store,
            store_url=r.get("store_url") or "",
            offer_url=r.get("offer_url") or "",
            original_price=original_price,
            original_price_currency=r.get("original_price_currency") or r.get("currency", "USD"),
            free_since=(
                (r.get("start_date") or r.get("free_since") or r.get("detected_at") or "").replace("+00:00", "Z")
            )[:19] + "Z",
            promotion_window=promo_window,
            end_date=end_date,
            is_permanent=is_permanent,
            image_url=r.get("image_url"),
            gate="subscription" if str(r.get("gate", "")).lower() == "subscription" else "none",
            source_feed=r.get("source_feed") or "unknown",
            detected_at=(r.get("detected_at") or ""),
            confidence=(r.get("confidence") if r.get("confidence") in ("high", "medium", "low") else None) or "low",
            extra=r,
        ))
    return records


def _to_float(v: Any) -> float:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0


def _guess_window(end_date: str | None) -> str:
    if not end_date:
        return "permanent"
    return "limited"


def dedupe(records: List[GameRecord]) -> List[GameRecord]:
    """Merge records sharing a `game_id`, keeping the best evidence overall.

    - confidence: best (high > medium > low)
    - end_date: latest (most permissive) observed
    - original_price: prefer the larger, earliest-seen paid price
    - source_feed: concatenate feeds that confirmed it
    """
    merged: Dict[str, GameRecord] = {}

    for rec in records:
        cur = merged.get(rec.game_id)
        if cur is None:
            merged[rec.game_id] = rec
            continue

        # merge into a new record to avoid mutating inputs
        merged[rec.game_id] = _merge(cur, rec)

    ordered = sorted(merged.values(), key=lambda r: (r.store, r.game_id))
    return ordered


def _merge(a: GameRecord, b: GameRecord) -> GameRecord:
    best_conf = b if _CONF.get(b.confidence, 0) > _CONF.get(a.confidence, 0) else a
    other = a if best_conf is b else b

    # end_date → latest
    end = _later(a.end_date, b.end_date)

    # original_price → larger
    orig_price = a.original_price if a.original_price >= b.original_price else b.original_price
    orig_currency = best_conf.original_price_currency if orig_price == best_conf.original_price else other.original_price_currency

    # source_feed → concatenate
    feeds = sorted({f for f in (a.source_feed, b.source_feed) if f})

    return GameRecord(
        game_id=a.game_id,
        title=best_conf.title,
        store=best_conf.store,
        store_url=best_conf.store_url or other.store_url,
        offer_url=best_conf.offer_url or other.offer_url,
        original_price=orig_price,
        original_price_currency=orig_currency,
        free_since=_earlier(a.free_since, b.free_since),
        promotion_window=_window(end),
        end_date=end,
        is_permanent=end is None or (a.is_permanent or b.is_permanent),
        image_url=best_conf.image_url or other.image_url,
        gate=best_conf.gate if best_conf.gate != "none" else other.gate,
        source_feed=",".join(feeds),
        detected_at=best_conf.detected_at,
        confidence=best_conf.confidence,
        extra={**other.extra, **best_conf.extra},
    )


def _later(a: str | None, b: str | None) -> str | None:
    """Most-permissive end date: None (permanent, no expiry) always wins."""
    if a is None or b is None:
        return None
    return a if a >= b else b


def _earlier(a: str, b: str) -> str:
    a = a or b
    b = b or a
    return a if a <= b else b


def _window(end: str | None) -> str:
    return "permanent" if end is None else "limited"
