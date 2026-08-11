"""Sample canonical records used by tests and the demo/offline path.

These exercise every filter border case from the spec §6 so tests and readers
can see expected behaviour without a live network call.
"""
from __future__ import annotations

from typing import Dict, List

from .model import GameRecord


def _rec(**kw) -> GameRecord:
    title = kw.pop("title", "Sample Game")
    store = kw.pop("store", "epic")
    return GameRecord(
        game_id=kw.pop("game_id", f"{store}|{title.lower().replace(' ', '-')}"),
        title=title,
        store=store,
        store_url=kw.pop("store_url", f"https://store.example/{title.lower().replace(' ', '-')}"),
        offer_url=kw.pop("offer_url", f"https://store.example/{title.lower().replace(' ', '-')}"),
        original_price=kw.pop("original_price", 19.99),
        original_price_currency=kw.pop("original_price_currency", "USD"),
        free_since=kw.pop("free_since", "2026-08-06T15:00:00Z"),
        promotion_window=kw.pop("promotion_window", "168h"),
        end_date=kw.pop("end_date", "2026-08-13T15:00:00Z"),
        is_permanent=kw.pop("is_permanent", False),
        image_url=kw.pop("image_url", None),
        gate=kw.pop("gate", "none"),
        source_feed=kw.pop("source_feed", "src_test"),
        detected_at=kw.pop("detected_at", "2026-08-06T15:00:00Z"),
        confidence=kw.pop("confidence", "high"),
        extra=kw.pop("extra", {}),
    )


def sample_epic_giveaway() -> GameRecord:
    """Passes: paid base game currently free-to-keep (e.g. Epic weekly)."""
    return _rec(
        game_id="epic|we-were-here-together",
        title="We Were Here Together",
        store="epic",
        original_price=17.99,
        end_date="2026-08-13T15:00:00Z",
        promotion_window="168h",
        source_feed="epic_freeGamesPromotions:current",
        extra={"offer_type": "BASE_GAME", "current_price": 0, "keep_action": True},
    )


def sample_f2p_native() -> GameRecord:
    """Rejected: native free-to-play (never paid)."""
    return _rec(
        game_id="steam|fortnite",
        title="Fortnite",
        store="steam",
        original_price=0.0,
        is_permanent=True,
        end_date=None,
        source_feed="steam_appdetails_flip",
        extra={"offer_type": "game", "current_price": 0, "keep_action": True},
    )


def sample_paid_to_free_steam() -> GameRecord:
    """Passes: permanent paid→free conversion with prior MSRP."""
    return _rec(
        game_id="steam|340580",
        title="Armed with Wings: Rearmed",
        store="steam",
        original_price=9.99,
        is_permanent=True,
        end_date=None,
        promotion_window="permanent",
        source_feed="steam_appdetails_flip",
        extra={"offer_type": "game", "current_price": 0, "keep_action": True},
    )


def sample_demo() -> GameRecord:
    """Rejected: demo title token + not a full game."""
    return _rec(
        game_id="steam|ac-demo",
        title="Assassin's Creed Demo",
        store="steam",
        original_price=0.0,
        extra={"offer_type": "demo", "current_price": 0, "keep_action": True},
    )


def sample_free_weekend() -> GameRecord:
    """Rejected: temp free weekend (play, not keep)."""
    return _rec(
        game_id="steam|some-multiplayer",
        title="Some Multiplayer",
        store="steam",
        original_price=24.99,
        end_date="2026-08-09T23:59:00Z",
        promotion_window="free-weekend",
        extra={"offer_type": "game", "current_price": 0, "keep_action": False,
               "play_only": True},
    )


def sample_addon() -> GameRecord:
    """Rejected: ADD_ON offerType — not a standalone base game."""
    return _rec(
        game_id="epic|lost-swords-pack",
        title="Lost Explorers' Swords Pack",
        store="epic",
        original_price=3.99,
        extra={"offer_type": "ADD_ON", "current_price": 0, "keep_action": True},
    )


def sample_sub_gated() -> GameRecord:
    """Rejected under default policy: requires a subscription (Prime-like)."""
    return _rec(
        game_id="prime|some-game",
        title="Some Prime Game",
        store="prime",
        original_price=19.99,
        gate="subscription",
        end_date=None,
        source_feed="prime_claims",
        extra={"offer_type": "BASE_GAME", "current_price": 0, "keep_action": True},
    )


def sample_priced_free_epic_upcoming() -> GameRecord:
    """Passes: upcoming weekly giveaway with paid MSRP + current $0."""
    return _rec(
        game_id="epic|caravan-sandwitch",
        title="Caravan SandWitch",
        store="epic",
        original_price=22.99,
        end_date="2026-08-20T15:00:00Z",
        promotion_window="168h",
        source_feed="epic_freeGamesPromotions:upcoming",
        extra={"offer_type": "BASE_GAME", "current_price": 0, "keep_action": True},
    )


ALL: List[GameRecord] = [
    sample_epic_giveaway(),
    sample_f2p_native(),
    sample_paid_to_free_steam(),
    sample_demo(),
    sample_free_weekend(),
    sample_addon(),
    sample_sub_gated(),
    sample_priced_free_epic_upcoming(),
]

# Raw collector-shaped candidates (pre-normalize) for pipeline-level tests.
RAW_CANDIDATES: List[Dict] = [
    {
        "store": "epic", "title": "We Were Here Together", "offer_id": "abc123",
        "offer_type": "BASE_GAME", "current_price": 0, "original_price": 12.99,
        "original_price_currency": "USD", "start_date": "2026-08-06T15:00:00.000Z",
        "end_date": "2026-08-13T15:00:00.000Z", "promotion_window": "168h",
        "store_url": "https://store.epicgames.com/en-US/we-were-here-together",
        "offer_url": "https://store.epicgames.com/en-US/we-were-here-together",
        "source_feed": "epic_freeGamesPromotions:current", "detected_at": "2026-08-06T15:00:00Z",
        "confidence": "high", "keep_action": True,
    },
    {
        "store": "epic", "title": "Fortnite", "offer_id": "fnid", "offer_type": "BASE_GAME",
        "current_price": 0, "original_price": 0, "original_price_currency": "USD",
        "start_date": "2017-01-01T00:00:00Z", "end_date": None, "promotion_window": "permanent",
        "source_feed": "epic_freeGamesPromotions:current", "detected_at": "2026-08-06T15:00:00Z",
        "confidence": "high", "keep_action": True,
    },
]
