"""Dedupe tests — same game via multiple feeds collapses to one record (spec §4.2 / §6.3)."""
from __future__ import annotations

from free_games_tracker.model import GameRecord
from free_games_tracker.normalize import dedupe


def _record(game_id, *, store="epic", title="Game", conf="high", end=None, price=10.0,
            source_feed="feed", free_since="2026-08-01T00:00:00Z"):
    return GameRecord(
        game_id=game_id, title=title, store=store,
        original_price=price, end_date=end, free_since=free_since,
        is_permanent=end is None, source_feed=source_feed,
        detected_at="2026-08-01T00:00:00Z", confidence=conf,
        extra={"offer_type": "BASE_GAME", "current_price": 0, "keep_action": True},
    )


def test_same_title_two_feeds_dedupes_to_one():
    a = _record("epic|we-were-here-together", source_feed="epic_freeGamesPromotions:current", conf="high", end="2026-08-13T15:00:00Z")
    b = _record("epic|we-were-here-together", source_feed="r_fgf_hot", conf="medium", end="2026-08-20T15:00:00Z")
    out = dedupe([a, b])
    assert len(out) == 1
    merged = out[0]
    # highest confidence kept
    assert merged.confidence == "high"
    # end_date -> latest
    assert merged.end_date == "2026-08-20T15:00:00Z"
    # source_feeds concatenated
    assert "epic_freeGamesPromotions:current" in merged.source_feed
    assert "r_fgf_hot" in merged.source_feed


def test_distinct_games_not_merged():
    a = _record("epic|beacon-pines", end="2026-08-13T15:00:00Z")
    b = _record("epic|caravan-sandwitch", end="2026-08-20T15:00:00Z")
    assert len(dedupe([a, b])) == 2


def test_original_price_prefers_larger():
    a = _record("epic|x", price=12.99)
    b = _record("epic|x", price=17.99)
    merged = dedupe([a, b])[0]
    assert merged.original_price == 17.99


def test_permanent_wins_end_none():
    a = _record("steam|340580", store="steam", end=None)
    b = _record("steam|340580", store="steam", end="2026-08-13T15:00:00Z")
    merged = dedupe([a, b])[0]
    assert merged.end_date is None  # permanent conversion (latest/None = no expiry)
