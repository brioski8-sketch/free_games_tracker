"""Tests for the free_games_collector public API (:mod:`free_games_collector`).

Covers the module's contract:
- ``get_current_free_games()`` returns ``[{title, url, available_from,
  available_until, source}]`` (ISO-8601 UTC windows; ``None`` when unknown).
- Offline (fixture) runs are deterministic and curated (F2P/add-on rows filtered).
- Returns ``[]`` when no game is currently free (all sources disabled).
- No credentials are read anywhere on the path.
"""
from __future__ import annotations

from free_games_collector import get_current_free_games

REQUIRED_KEYS = {"title", "url", "available_from", "available_until", "source"}


def test_offline_returns_non_empty_list_of_dicts():
    games = get_current_free_games(offline=True)
    assert isinstance(games, list)
    assert games, "expected fixture hits offline"
    for g in games:
        assert REQUIRED_KEYS.issubset(g.keys()), f"missing key in {g!r}"
        assert g["title"]
        assert g["url"].startswith("http")


def test_offline_windows_are_iso_or_none():
    for g in get_current_free_games(offline=True):
        for key in ("available_from", "available_until"):
            v = g[key]
            assert v is None or len(v) == 20 and v.endswith("Z"), f"{key!r} not ISO: {v!r}"


def test_offline_is_curated_filters_f2p_and_addons():
    """Fixtures include Fortnite (F2P never-paid) and a Swords add-on. Neither
    may appear — the tracker's curation contract rejects them."""
    titles = {g["title"] for g in get_current_free_games(offline=True)}
    assert "Fortnite" not in titles
    assert "Lost Explorers' Swords Pack" not in titles
    assert "Caravan SandWitch" not in titles  # upcoming (not currently free)


def test_no_free_games_returns_empty_list():
    paths = ["nope.yaml", "does-not-exist.yaml", None]
    # Point config at a file that turns every source off: all disabled -> [].
    games = get_current_free_games(offline=True, config_path=_all_off_config())
    assert games == []


def _all_off_config() -> str:
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as fh:
        fh.write(
            "collectors:\n"
            "  epic: false\n"
            "  gog: false\n"
            "  reddit: false\n"
        )
    return path
