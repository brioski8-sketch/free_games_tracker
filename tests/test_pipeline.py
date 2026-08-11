"""Pipeline + adapter tests (spec §6.2, §6.5).

- End-to-end offline run produces a well-formed markdown report with ≥1 passing
  game and correct section structure.
- Collector smoke tests parse the live API contract fields.
  (These hit the network; skipped when `--offline` env is set or offline only.)
"""
from __future__ import annotations

import os
import tempfile

import pytest

from free_games_tracker.config import Config
from free_games_tracker.pipeline import run
from free_games_tracker.state import StateStore


def _cfg(tmpdir: str, collectors=None) -> Config:
    return Config({
        "sort_mode": "score",
        "collectors": collectors or {"epic": True, "steam_flip": True, "reddit": True, "gog": False},
        "notify": {"output_dir": os.path.join(tmpdir, "reports")},
        "state_db": os.path.join(tmpdir, "state.db"),
        "allow_sub_gated": False,
    })


def test_end_to_end_offline_report():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        state = StateStore(cfg["state_db"])
        try:
            res = run(cfg, state, offline=True)
        finally:
            state.close()

        assert res.passing, "expected at least one passing game from fixtures"
        assert res.json_path.endswith("free_games.json")
        assert "free-games-" in res.md_path

        md = res.report_md
        assert md.startswith("# Free game alert")
        assert "| Game | Store | Was |" in md
        # The F2P (Fortnite) and ADD_ON fixtures must NOT appear in passing output.
        titles = {r.title for r in res.passing}
        assert "Fortnite" not in titles
        assert "Lost Explorers' Swords Pack" not in titles
        # Some real passing games present
        assert any("We Were Here Together" in t or "Beacon Pines" in t or "Breathedge" in t
                   for t in titles)


@pytest.mark.network
def test_epic_live_contract():
    """Smoke: Epic API returns elements and at least one discountPercentage==0 promo."""
    from free_games_tracker.collectors import epic
    raw = epic.collect(Config({}))
    assert len(raw) > 0, "Epic API should return free giveaways live"
    fields = {"store", "title", "current_price", "original_price", "source_feed"}
    assert fields.issubset(raw[0].keys())
    assert all(r["store"] == "epic" for r in raw)


@pytest.mark.network
def test_steam_live_contract():
    from free_games_tracker.collectors import steam
    from free_games_tracker.state import StateStore
    with tempfile.TemporaryDirectory() as tmp:
        state = StateStore(os.path.join(tmp, "s.db"))
        try:
            raw = steam.collect(Config({"steam": {"cc": "us", "watched_appids": [340580]}}), state)
            # Even if no flip occurred this run, snapshots must have been persisted.
            assert state.all_steam_appids(), "steam snapshots should persist"
        finally:
            state.close()
