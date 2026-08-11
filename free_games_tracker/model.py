"""Canonical record model and shared constants.

Field names are the spec's final vocabulary and must be used verbatim in the
JSON records, the dedupe key, and the report renderer.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, List

# Stores and confidence levels (spec §3).
STORES = ("steam", "epic", "gog", "prime", "itch", "aggregator")
CONFIDENCE = ("high", "medium", "low")
GATES = ("none", "subscription")


@dataclass
class GameRecord:
    """One game/free-event record (spec §3 data model).

    All fields except the optional ones are required by the filter/report.
    """

    game_id: str
    title: str
    store: str
    store_url: str = ""
    offer_url: str = ""
    original_price: float = 0.0
    original_price_currency: str = "USD"
    free_since: str = ""            # ISO-8601 UTC
    promotion_window: str = ""      # e.g. "168h", "48h", "permanent"
    end_date: Optional[str] = None  # ISO-8601 UTC; None == permanent
    is_permanent: bool = False
    image_url: Optional[str] = None
    gate: str = "none"              # "none" | "subscription"
    source_feed: str = ""           # e.g. "epic_freeGamesPromotions"
    detected_at: str = ""           # ISO-8601 UTC
    confidence: str = "low"
    # Internal flags not part of the canonical report surface.
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("extra", None)
        return d


def make_id(store: str, key: str) -> str:
    """Stable dedupe key: `<store>|<key>`.

    key should be the store-internal product id (epic offerId/appid) or a
    normalized title slug. Lower-cased and whitespace-collapsed.
    """
    norm = " ".join(str(key).strip().lower().split())
    return f"{store}|{norm}"
