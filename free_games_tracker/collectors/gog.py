"""GOG collector — catalog API.

    https://catalog.gog.com/v1/catalog?limit=<n>&order=desc:trending

NOTE: the `price=free` query param does NOT reliably filter to free products
(verified live: it returns trending products at their current prices). So we
pull a broad slice of the catalog and filter locally for products whose
current price is 0 (`finalMoney.amount == "0"`) and whose base/MSRP price is
> 0 (`baseMoney.amount > 0`).

GOG's permanent "free" collection is dominated by products that are ALWAYS
free (base price also 0) — those carry no "paid became free" signal and are
dropped by the MSRP>0 check. Only genuine paid→free giveaways (e.g. the
48-hour free-to-keep promos during Summer/Winter sales) survive. On a normal
week this adapter returns few/zero records — that is correct, not a bug.

`confidence = medium` (official catalog API, but free-vs-giveaway must be
inferred from the price/base comparison).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List

from ..httpclient import FetchError, fetch_json

API = "https://catalog.gog.com/v1/catalog"


def _money_amount(val: Any) -> float:
    try:
        return round(float(val), 2)
    except (TypeError, ValueError):
        return 0.0


def collect(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    http = cfg.get("http") or {}
    limit = 200  # broad sweep; raise for depth
    url = f"{API}?limit={limit}&order=desc:trending"

    try:
        payload = fetch_json(url, timeout=http.get("timeout", 20), retries=http.get("retries", 2))
    except FetchError:
        return []

    products = payload.get("products") or []
    now_iso = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: List[Dict[str, Any]] = []

    for p in products:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        price = p.get("price") or {}
        final = (price.get("finalMoney") or {}).get("amount")
        base = (price.get("baseMoney") or {}).get("amount")
        currency = (price.get("baseMoney") or {}).get("currency") or "USD"
        prod_id = p.get("id")
        slug = p.get("slug") or str(prod_id)

        current = _money_amount(final)
        original = _money_amount(base)

        # Only a product currently free (final==0) with a paid MSRP (base>0)
        # is a "paid game that became free" candidate.
        if current != 0:
            continue
        if original <= 0:
            continue

        out.append({
            "store": "gog",
            "product_id": prod_id,
            "title": title,
            "offer_type": p.get("productType"),
            "current_price": current,
            "original_price": original,
            "original_price_currency": currency,
            "end_date": None,
            "promotion_window": "unknown",
            "is_permanent": False,
            "store_url": f"https://www.gog.com/en/game/{slug}",
            "offer_url": f"https://www.gog.com/en/game/{slug}",
            "image_url": (p.get("image") or {}).get("url") if isinstance(p.get("image"), dict) else None,
            "source_feed": "gog_catalog_free",
            "detected_at": now_iso,
            "confidence": "medium",
            "keep_action": True,
        })
    return out
