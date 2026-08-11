"""r/FreeGameFindings collector — community-curated giveaways across stores.

Reddit's public JSON:

    https://www.reddit.com/r/FreeGameFindings/hot.json?limit=<n>&raw_json=1

We parse post titles + link_flair_text. Posts flagged "previously given" or
"f2p to paid" or "tasks" are excluded by the filter's own rules where possible,
but we keep them in the raw stream and let `filter.py` apply the contract since
title tokens (demo/trial/etc.) and non-free patterns are best decided centrally.

Flairs like "tasks" gate the claim behind a task → treated as a keep action with
a note; the default filter policy still applies (allow_sub_gated flag doesn't
cover task-gating, only subscription — tasks pass unless title looks non-game).

`confidence = medium` (human-curated community feed; r/FGF is the gold standard
for cross-store free-to-keep coverage).

Reddit may rate-limit unauthenticated JSON (HTTP 403); failures degrade to `[]`.

Original-price handling (see task B1): the Reddit payload has no authoritative
per-post MSRP field, so we parse an expected pre-free price from the post's
title/selftext when it is *explicitly framed* as the pre-promotion price
("was $X", "original price $X", "MSRP $X", "X → free", ...). Posts without a
demonstrable prior price keep `original_price = 0.0`, which the filter rejects
as `f2p_never_paid` — matching the offline fixture path and never fabricating a
passing row from metadata that carries no price evidence.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, List, Optional

from ..httpclient import FetchError, fetch_json

API = "https://www.reddit.com/r/FreeGameFindings/hot.json"

# Currency tokens we can resolve to an ISO code from a price mention.
_CURRENCY = {"$": "USD", "US$": "USD", "\u20ac": "EUR", "\u00a3": "GBP"}

# Pre-promotion MSRP marker words — a price is only trusted as the ORIGINAL
# (pre-free) price when it is explicitly framed as such. Without a marker we
# might read a current price, a regional local figure, or an unrelated number
# as the paid MSRP, so we deliberately ignore un-framed prices.
_MSRP_MARKER = (
    r"(?:was|were|original|orig|originally|msrp|regular|rrp|previously|"
    r"used to (?:be|cost)|normal(?:ly)?(?:\s*price)?)"
)
# "marker ... $AMT" (most common: "was $19.99")
_P1 = re.compile(
    r"(?i)" + _MSRP_MARKER
    + r"(?:[^0-9]{0,12}?)(?P<cur>US\$|\$|\u20ac|\u00a3)?\s*(?P<amt>[0-9]+(?:\.[0-9]{1,2})?)"
)
# "$AMT ... marker" ("$4.99 was the price", "€24.99 regular price")
_P2 = re.compile(
    r"(?i)(?P<cur>US\$|\$|\u20ac|\u00a3)?\s*(?P<amt>[0-9]+(?:\.[0-9]{1,2})?)"
    + r"(?:[^0-9]{0,12}?)" + _MSRP_MARKER
)
# "$AMT -> free" / "$AMT → free" / "$AMT to free" giveaway frame.
# Requires a currency token so a bare number is never misread as an MSRP.
_FREE_FRAME = re.compile(
    r"(?i)(?P<cur>US\$|\$|\u20ac|\u00a3)\s*(?P<amt>[0-9]+(?:\.[0-9]{1,2})?)"
    r"\s*(?:-|\u2013|\u2014|->|\u2192|to)\s*free"
)

# Flairs that signal a post is NOT a current paid-free giveaway (inverse signal,
# stale re-hash, or otherwise not a free-to-keep claim we should surface).
# "f2p to paid" = a F2P game became PAID — the opposite of a free giveaway, so
# its current_price is not 0 and it must never be emitted as a free candidate.
_SKIP_FLAIRS = frozenset({"f2p to paid"})


def _parse_original_price(post: Dict[str, Any]) -> Optional[tuple[float, str]]:
    """Parse a demonstrable pre-promotion MSRP from a post's title/selftext.

    Returns ``(price, iso_currency)`` or ``None`` when no explicitly-framed
    paid price is present. ``None`` → caller emits ``original_price = 0.0`` so
    the filter rejects the post as ``f2p_never_paid`` (no fabricated row).
    """
    hay = " ".join(
        p for p in ((post.get("title") or ""), (post.get("selftext") or "")) if p
    )
    if not hay:
        return None
    for pat in (_P1, _P2, _FREE_FRAME):
        m = pat.search(hay)
        if m:
            return float(m.group("amt")), _CURRENCY.get(m.group("cur") or "$", "USD")
    return None


def collect(cfg: Dict[str, Any], payload: Optional[dict] = None) -> List[Dict[str, Any]]:
    """Collect r/FGF giveaway posts into raw candidates.

    ``payload`` (optional) is an already-fetched Reddit ``hot.json`` response so
    the offline/fixture path exercises the SAME parsing logic as live. When
    omitted, the feed is fetched over the network (degrades to ``[]`` on
    rate-limit/HTTP error).
    """
    http = cfg.get("http") or {}
    limit = (cfg.get("reddit") or {}).get("limit", 25)

    if payload is None:
        url = f"{API}?limit={limit}&raw_json=1"
        try:
            payload = fetch_json(url, timeout=http.get("timeout", 20), retries=http.get("retries", 2))
        except FetchError:
            return []

    body: dict = payload or {}  # non-None from here on (fetch path already handled)
    children = body.get("data", {}).get("children") or []
    # Deterministic offline runs: a fixture payload may carry its own
    # `detected_at` (top-level, non-API field) so the aggregator record's
    # free_since (= detected_at via normalize) is stable across runs. Live
    # payloads never carry it, so we fall back to the fetch time — the real
    # detection moment. Without this, every offline run stamps a fresh `now`
    # and the aggregator row is forever "new" (never idempotent).
    now_iso = body.get("detected_at") or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: List[Dict[str, Any]] = []

    for child in children:
        post = child.get("data") or {}
        title = (post.get("title") or "").strip()
        if not title:
            continue
        flair = (post.get("link_flair_text") or "").strip()
        if flair.lower() in _SKIP_FLAIRS:
            # inverse/stale signal — not a current free giveaway; skip so we
            # never emit a wrong current_price=0 candidate for it.
            continue
        permalink = post.get("permalink") or ""
        price_parsed = _parse_original_price(post)
        out.append({
            "store": "aggregator",
            "reddit_post_id": post.get("id"),
            "title": title,  # raw title incl. store/tags; normalizer strips
            "offer_type": None,
            "current_price": 0.0,  # r/FGF posts are free-to-keep by definition
            "original_price": (price_parsed[0] if price_parsed else 0.0),
            "original_price_currency": (price_parsed[1] if price_parsed else "USD"),
            "flair": flair,
            "end_date": None,
            "promotion_window": "from-post",
            "is_permanent": False,
            "store_url": f"https://www.reddit.com{permalink}",
            "offer_url": f"https://www.reddit.com{permalink}",
            "image_url": (post.get("preview", {}).get("images", [{}])[0].get("source", {}).get("url")
                          if post.get("preview") else None),
            "source_feed": "r_fgf_hot",
            "detected_at": now_iso,
            "confidence": "medium",
            "keep_action": True,
        })
    return out
