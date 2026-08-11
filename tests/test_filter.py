"""Filter acceptance tests — every border case from the spec §6 / §2.

These are the crown-jewel tests: they pin the exact FREE vs F2P/DEMO/TRIAL/DLC
behaviour the whole workflow exists to get right.
"""
from __future__ import annotations

import free_games_tracker.filter as filt
from free_games_tracker.config import DEFAULTS
from free_games_tracker.sample_data import (
    sample_addon,
    sample_demo,
    sample_epic_giveaway,
    sample_f2p_native,
    sample_free_weekend,
    sample_paid_to_free_steam,
    sample_priced_free_epic_upcoming,
    sample_sub_gated,
)

# A minimal cfg carrying the default policy flags.
CFG = {
    "allow_bundles": False,
    "allow_sub_gated": False,
    "min_original_price": 0,
    "allow_bundles_flag": DEFAULTS.get("allow_bundles"),
}


def test_paid_giveaway_passes():
    assert filt.passes(sample_epic_giveaway(), CFG).passed


def test_f2p_native_rejected_never_paid():
    res = filt.passes(sample_f2p_native(), CFG)
    assert not res.passed
    assert res.reason == "f2p_never_paid"


def test_paid_to_free_steam_passes():
    assert filt.passes(sample_paid_to_free_steam(), CFG).passed


def test_demo_rejected():
    res = filt.passes(sample_demo(), CFG)
    assert not res.passed
    assert res.reason in ("demo_trial", "not_full_game")


def test_free_weekend_rejected_temp_access():
    res = filt.passes(sample_free_weekend(), CFG)
    assert not res.passed
    assert res.reason == "temp_access_only"


def test_addon_rejected():
    res = filt.passes(sample_addon(), CFG)
    assert not res.passed


def test_sub_gated_rejected_by_default():
    res = filt.passes(sample_sub_gated(), CFG)
    assert not res.passed
    assert res.reason == "sub_gated_flagged"


def test_sub_gated_allowed_when_flagged():
    assert filt.passes(sample_sub_gated(), {**CFG, "allow_sub_gated": True}).passed


def test_upcoming_giveaway_passes():
    assert filt.passes(sample_priced_free_epic_upcoming(), CFG).passed


def test_current_price_not_free_rejected():
    rec = sample_epic_giveaway()
    rec.extra = {**rec.extra, "current_price": 19.99}
    res = filt.passes(rec, CFG)
    assert not res.passed
    assert res.reason == "not_free_currently"


def test_bundle_rejected_unless_allowed():
    from free_games_tracker.model import GameRecord
    bundle = GameRecord(
        game_id="epic|bundle-xyz", title="Tomb Raider I-III", store="epic",
        original_price=29.99, end_date="2026-08-13T15:00:00Z", free_since="2026-08-06T15:00:00Z",
        source_feed="epic_freeGamesPromotions:current", detected_at="2026-08-06T15:00:00Z",
        extra={"offer_type": "BUNDLE", "current_price": 0, "keep_action": True},
    )
    assert not filt.passes(bundle, {**CFG, "allow_bundles": False}).passed
    assert filt.passes(bundle, {**CFG, "allow_bundles": True}).passed


def test_title_token_trial_beta_prologue():
    for token in ("demo", "trial", "playtest", "beta", "prologue", "showcase", "benchmark"):
        from free_games_tracker.model import GameRecord
        rec = GameRecord(
            game_id=f"steam|{token}", title=f"Super Game {token}", store="steam",
            original_price=9.99, end_date=None, free_since="2026-08-01T00:00:00Z",
            is_permanent=True, source_feed="s", detected_at="2026-08-01T00:00:00Z",
            extra={"offer_type": "game", "current_price": 0, "keep_action": True},
        )
        assert not filt.passes(rec, CFG).passed, token


def test_filter_records_partitions():
    records = [
        sample_epic_giveaway(),      # pass
        sample_f2p_native(),         # fail f2p
        sample_demo(),               # fail demo
        sample_paid_to_free_steam(),  # pass
    ]
    passing, diag = filt.filter_records(records, CFG)
    assert {r.title for r in passing} == {"We Were Here Together", "Armed with Wings: Rearmed"}
    assert len(diag) == 2
    reasons = {d["title"]: d["reason"] for d in diag}
    assert reasons["Fortnite"] == "f2p_never_paid"
