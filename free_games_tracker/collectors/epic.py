"""Epic Games Store collector.

Reads the unofficial-but-public `freeGamesPromotions` JSON (no auth):

    https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?\
        locale=en-US&country=US&allowCountries=US

Emits a candidate for each element that carries a **giveaway** promotional offer
(`discountPercentage == 0`) that's currently active OR upcoming, where the product
is a `BASE_GAME`. Native F2P titles have no `promotionalOffers` block, so they are
naturally excluded here (and re-checked by the filter anyway).

Deterministic weekly cadence (Thursday ~15:00 UTC).
`confidence = high` (official store API).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List

from ..httpclient import FetchError, fetch_json

API = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions"


def _fmt_price(cents: Any) -> float:
    try:
        return round(int(cents or 0) / 100.0, 2)
    except (TypeError, ValueError):
        return 0.0


def _grab_image(element: Dict[str, Any]) -> str | None:
    images = element.get("keyImages") or []
    # prefer the capsule or cover art
    for kind in ("DieselGameBoxTall", "DieselGameBox", "OfferImageWide", "VaultOpened"):
        for img in images:
            if img.get("type") == kind:
                return img.get("url")
    if images:
        return images[0].get("url")
    return None


def _promo_blocks(element: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return list of dicts: {bucket, offer} for discountPercentage==0 promos."""
    proms = element.get("promotions") or {}
    out: List[Dict[str, Any]] = []
    for bucket, key in (("current", "promotionalOffers"), ("upcoming", "upcomingPromotionalOffers")):
        for group in proms.get(key) or []:
            for offer in group.get("promotionalOffers") or []:
                ds = (offer.get("discountSetting") or {})
                if ds.get("discountPercentage") == 0:
                    out.append({"bucket": bucket, "offer": offer})
    return out


def collect(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    locale = (cfg.get("epic") or {}).get("locale", "en-US")
    country = (cfg.get("epic") or {}).get("country", "US")
    http = cfg.get("http") or {}
    url = f"{API}?locale={locale}&country={country}&allowCountries={country}"

    try:
        payload = fetch_json(
            url,
            timeout=http.get("timeout", 20),
            retries=http.get("retries", 2),
        )
    except FetchError:
        # A transient failure of one collector shouldn't sink the whole pipeline.
        return []

    elements = (payload.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements")) or []
    now_iso = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: List[Dict[str, Any]] = []

    for element in elements:
        title = (element.get("title") or "").strip()
        if not title:
            continue
        for block in _promo_blocks(element):
            offer = block["offer"]
            start_raw = (offer.get("startDate") or "")
            end_raw = (offer.get("endDate") or "")
            # Normalize both window bounds to aware UTC before _window_label()
            # subtracts them. Epic emits ISO-8601 UTC, but the naive start (its
            # offset stripped) would raise TypeError against the aware end;
            # treating a naive bound as UTC and converting any offset to UTC
            # keeps both on the same tzinfo so the 7-day window renders as "168h".
            start = _to_aware_utc(start_raw)
            end = _to_aware_utc(end_raw)
            price = element.get("price", {}).get("totalPrice", {}) or {}
            original_cents = price.get("originalPrice") or 0
            currency = price.get("currencyCode") or "USD"
            slug = element.get("productSlug")
            offer_id = element.get("id") or f"missing-{title.lower()}"
            if not slug:
                slug = title.lower().replace(" ", "-")
            store_url = f"https://store.epicgames.com/{locale}/{slug}" if slug else ""
            # URL-encode isn't critical here; slugs are already URL-safe.
            offer_url = f"https://store.epicgames.com/{locale}/free-games" if not slug else store_url

            out.append({
                "store": "epic",
                "title": title,
                "offer_id": offer_id,
                "product_slug": element.get("productSlug"),
                "offer_type": element.get("offerType"),
                "current_price": _fmt_price(price.get("discountPrice")),
                "original_price": _fmt_price(original_cents),
                "original_price_currency": currency,
                "start_date": start_raw,
                "end_date": end_raw,
                "promotion_window": _window_label(start, end),
                "store_url": store_url,
                "offer_url": offer_url,
                "image_url": _grab_image(element),
                "source_feed": f"epic_freeGamesPromotions:{block['bucket']}",
                "detected_at": now_iso,
                "confidence": "high",
                "keep_action": True,  # Epic weekly giveaways are keep-to-library
            })
    return out


def _to_aware_utc(value: str) -> str:
    """Parse an ISO timestamp and return it normalized to aware UTC.

    Handles naive values (missing tz offset) by treating them as UTC, and
    converts any explicit offset/timezone to UTC. Returns an ISO string that
    carries the +00:00 offset so bounds share a tzinfo. Empty / unparseable
    input is passed through unchanged (the caller handles it gracefully).
    """
    if not value:
        return value
    try:
        dt = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc).isoformat()


def _window_label(start_date: str, end_date: str) -> str:
    # Normalize both bounds to aware UTC before subtracting so the function is
    # robust to naive starts, aware ends, mixed forms, or any explicit offset.
    # (A naive bound is treated as UTC; an aware offset is converted to UTC.)
    try:
        s = _dt.datetime.fromisoformat(_to_aware_utc(start_date).replace("Z", "+00:00"))
        e = _dt.datetime.fromisoformat(_to_aware_utc(end_date).replace("Z", "+00:00"))
        hours = int((e - s).total_seconds() // 3600)
        return f"{hours}h"
    except (ValueError, TypeError):
        return "unknown"
