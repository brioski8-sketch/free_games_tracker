"""Filter — enforce the acceptance contract (§2 of the spec).

A game passes only if ALL of the following hold, backed by *observed* data:

1. Full standalone base game (not F2P-only / demo / trial / beta / prologue /
   showcase / benchmark / DLC / add-on / "Starter Edition").
2. Had a measurable paid price (original_price > 0) before the promotion.
3. Is currently offered at $0 / "free" / "free to keep".
4. Is a *keep* action, not a temporary *play* action (free weekend / trial).
5. Not subscription-gated unless `allow_sub_gated`.

Every failing record gets a machine-readable `reason` code for diagnostics.
Pure and fully unit-testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from .model import GameRecord

# Title token blocklist (case-insensitive) — spec §2 criterion 1.
TITLE_BLOCKLIST = re.compile(
    r"(^|\b)(demo|trial|playtest|beta|prologue|showcase|benchmark|testing|"
    r"friend'?s pass|starter edition)(\b|$)",
    re.IGNORECASE,
)
# offerType values that are NOT full games (spec §2 / research pitfalls 2,4,5)
NON_GAME_OFFERTYPES = {"ADD_ON", "DLC", "EDITION", "BUNDLE", "IN_GAME_ITEM", "DLC_EPIC", "SOUNDTRACK"}

# Reason codes surfaced in logs / diagnostics.
REASON_KEYS = (
    "not_full_game", "demo_trial", "f2p_never_paid", "not_free_currently",
    "temp_access_only", "sub_gated_flagged",
)


@dataclass
class FilterResult:
    decision: bool
    reason: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.decision


def _title_flagged(rec: GameRecord, cfg) -> bool:
    """Demo/trial/beta/prologue/etc. title tokens → not a full game."""
    if TITLE_BLOCKLIST.search(rec.title):
        return True
    # offerType-based check
    offer_type = str((rec.extra or {}).get("offer_type") or "").upper()
    if offer_type == "BUNDLE":
        # Bundles are a legit giveaway type but off-scope unless enable_allow_bundles
        return not cfg.get("allow_bundles", False)
    if offer_type in NON_GAME_OFFERTYPES:
        return True
    return False


def _keep_action(rec: GameRecord, cfg) -> bool:
    """Keep vs play. Play-only (free weekend / trial) is rejected."""
    # Epic weekly giveaways are keep. Steam permanent conversions are keep.
    # Aggregator posts are keep-by-definition unless a play-only marker appears.
    keep = bool((rec.extra or {}).get("keep_action", True))
    # a "free weekend" / trial note in the feed signals temp access
    play_hint = bool((rec.extra or {}).get("play_only")) or (
        (rec.extra or {}).get("promotion_window") == "free-weekend"
    )
    if play_hint:
        return False
    return keep


def passes(rec: GameRecord, cfg) -> FilterResult:
    """Apply the §2 acceptance contract. cfg is a dict-like config."""
    # Criterion 1 — full standalone game.
    if _title_flagged(rec, cfg):
        reason = "demo_trial" if TITLE_BLOCKLIST.search(rec.title) else "not_full_game"
        return FilterResult(False, reason)

    # Criterion 2 — had a paid price before the promo.
    if (rec.original_price or 0.0) <= 0:
        return FilterResult(False, "f2p_never_paid")

    # Optional MSRP floor (drop 99¢ shovelware).
    if (rec.original_price or 0.0) < float(cfg.get("min_original_price", 0)):
        # still "never worth reporting", but code as not_full_game-class skimmable
        return FilterResult(False, "f2p_never_paid")

    # Criterion 3 — currently free.
    if rec.extra is not None and "current_price" in rec.extra:
        current = _to_float(rec.extra.get("current_price"))
        if current != 0:
            return FilterResult(False, "not_free_currently")
    elif not rec.is_permanent:
        # no explicit current price signal and not flagged permanent → no proof of free
        return FilterResult(False, "not_free_currently")

    # Criterion 3 — keep (not temporary play).
    if not _keep_action(rec, cfg):
        return FilterResult(False, "temp_access_only")

    # Criterion 5 — subscription gate policy.
    if rec.gate == "subscription" and not cfg.get("allow_sub_gated", False):
        return FilterResult(False, "sub_gated_flagged")

    return FilterResult(True)


def _to_float(v) -> float:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0


def filter_records(records: List[GameRecord], cfg) -> tuple[List[GameRecord], List[dict]]:
    """Return (passing, diagnostics). Diagnostics: {game_id, title, reason}."""
    passing: List[GameRecord] = []
    diag: List[dict] = []
    for rec in records:
        res = passes(rec, cfg)
        if res.passed:
            passing.append(rec)
        else:
            diag.append({
                "game_id": rec.game_id,
                "title": rec.title,
                "store": rec.store,
                "reason": res.reason or "rejected",
            })
    return passing, diag
