"""Rank — deterministic ordering of passing records (spec §4.4).

Default: weighted score (higher first). Optional overrides via `sort_mode`:
- score   → weighted signals
- newest  → pure free_since desc
- value   → pure original_price desc
"""
from __future__ import annotations

import math
from typing import List

from .model import GameRecord


def _pricelog(p: float) -> float:
    if p <= 0:
        return 0.0
    return max(0.0, math.log10(p))


def score(rec: GameRecord) -> float:
    """Weighted score per spec §4.4."""
    p = float(rec.original_price or 0.0)
    s = 0.0
    if rec.is_permanent:
        s += 200
    s += 60 * _pricelog(p)

    # recency: +40 * clamp(1 - hours_since_free / 168, 0..1)
    hours = _hours_since(rec.free_since)
    if hours is not None:
        s += 40 * max(0.0, min(1.0, 1 - hours / 168.0))

    conf = {"high": 0, "medium": -20, "low": -40}[rec.confidence]
    s += conf

    if rec.gate == "subscription":
        s -= 25
    return round(s, 2)


def _hours_since(iso: str) -> int | None:
    import datetime as _dt
    try:
        ts = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = _dt.datetime.now(_dt.timezone.utc)
        return int((now - ts).total_seconds() // 3600)
    except (ValueError, TypeError):
        return None


def _sort_key(rec: GameRecord, mode: str):
    if mode == "newest":
        return (0, -_ts(rec.free_since), rec.title.lower())
    if mode == "value":
        return (0, -float(rec.original_price or 0.0), rec.title.lower())
    # default score desc; ties: newest first then title
    return (-score(rec), -_ts(rec.free_since), rec.title.lower())


def _ts(iso: str) -> float:
    import datetime as _dt
    try:
        dt = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def rank(records: List[GameRecord], sort_mode: str = "score") -> List[GameRecord]:
    mode = sort_mode if sort_mode in ("score", "newest", "value") else "score"
    return sorted(records, key=lambda r: _sort_key(r, mode))
