"""Tests for weekly_report.py — HTML email rendering + store attribution.

These cover the contract the cron job depends on:
  * store_label() names the store from source OR from the claim URL host,
  * render_email_html() emits a link per game and names the store,
  * render_email_text() is a usable plain-text alternative,
  * the HTML is escaped (no injection from a hostile title),
  * CLI wiring: --email --dry-run prints HTML without needing credentials.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load_weekly_report():
    """Import weekly_report.py by path (it lives at the deployable root)."""
    path = os.path.join(ROOT, "weekly_report.py")
    spec = importlib.util.spec_from_file_location("weekly_report", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


wr = _load_weekly_report()


SAMPLE = [
    {
        "title": "Beacon Pines",
        "url": "https://store.epicgames.com/en-US/beacon-pines",
        "available_from": "2026-08-06T15:00:00Z",
        "available_until": "2026-08-13T15:00:00Z",
        "source": "epic",
    },
    {
        "title": "Legends of Starkadia",
        "url": "https://store.steampowered.com/app/2618160/Legends_of_Starkadia/",
        "available_from": "2026-09-10T16:12:30Z",
        "available_until": None,
        "source": "aggregator",
    },
    {
        "title": "State of Mind",
        "url": "https://www.gog.com/en/game/state_of_mind",
        "available_from": "2026-09-10T16:12:30Z",
        "available_until": None,
        "source": "aggregator",
    },
    {
        "title": "Some itch Game",
        "url": "https://someone.itch.io/some-game",
        "available_from": None,
        "available_until": None,
        "source": "aggregator",
    },
]


# ---------------------------------------------------------------- store_label

def test_store_label_prefers_explicit_source():
    assert wr.store_label(SAMPLE[0]) == "Epic Games"


@pytest.mark.parametrize("game,expected", [
    (SAMPLE[1], "Steam"),
    (SAMPLE[2], "GOG"),
    (SAMPLE[3], "itch.io"),
])
def test_store_label_derives_from_url_host(game, expected):
    assert wr.store_label(game) == expected


def test_store_label_unknown_host_falls_back():
    game = {"title": "X", "url": "https://example.com/x", "source": "aggregator"}
    assert wr.store_label(game) == "Other / giveaway site"


def test_store_label_title_hint_for_community_post():
    """A Reddit-thread claim URL has no store host — fall back to the title hint."""
    game = {
        "title": "Moonlighter is FREE on Steam (limited time)",
        "url": "https://www.reddit.com/r/FreeGameFindings/comments/ab12/x/",
        "source": "aggregator",
    }
    assert wr.store_label(game) == "Steam"


def test_store_label_url_host_beats_title_hint():
    """The URL host is more reliable than a title hint."""
    game = {
        "title": "Some game is free on Steam",
        "url": "https://www.gog.com/en/game/some-game",
        "source": "aggregator",
    }
    assert wr.store_label(game) == "GOG"


def test_store_label_handles_missing_url():
    assert wr.store_label({"title": "X", "source": "aggregator"}) == "Other / giveaway site"


# ------------------------------------------------------------ HTML rendering

def test_html_email_links_each_game_and_names_store():
    html = wr.render_email_html(SAMPLE, date="2026-09-10")

    for g in SAMPLE:
        assert g["url"] in html, f"claim URL missing for {g['title']}"
        assert g["title"].split()[0] in html

    # store names are surfaced prominently
    assert "Epic Games" in html
    assert "Steam" in html
    assert "GOG" in html
    assert "itch.io" in html


def test_html_email_is_valid_shell():
    html = wr.render_email_html(SAMPLE, date="2026-09-10")
    assert html.startswith("<!DOCTYPE html>")
    assert html.rstrip().endswith("</html>")
    assert "<table" in html
    # title hyperlinked directly, plus a claim link
    assert html.count('href="https://store.epicgames.com/en-US/beacon-pines"') == 2


def test_html_email_empty_state():
    html = wr.render_email_html([], date="2026-09-10")
    assert "No paid games are currently free" in html
    assert "<!DOCTYPE html>" in html


def test_html_email_escapes_hostile_title():
    evil = [{
        "title": '<script>alert(1)</script> & "quotes"',
        "url": "https://store.steampowered.com/app/1/x",
        "available_from": "2026-09-10T00:00:00Z",
        "available_until": None,
        "source": "aggregator",
    }]
    html = wr.render_email_html(evil, date="2026-09-10")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_html_email_escapes_hostile_url():
    evil = [{
        "title": "Game",
        "url": 'https://x.test/"><script>bad()</script>',
        "available_from": None,
        "available_until": None,
        "source": "aggregator",
    }]
    html = wr.render_email_html(evil, date="2026-09-10")
    assert "<script>bad()" not in html


# ------------------------------------------------------------ text rendering

def test_text_alternative_lists_games_and_urls():
    txt = wr.render_email_text(SAMPLE, date="2026-09-10")
    assert "Beacon Pines" in txt
    assert "Epic Games" in txt
    assert SAMPLE[0]["url"] in txt


def test_text_alternative_empty_state():
    assert "No paid games are currently free" in wr.render_email_text([], date="2026-09-10")


# --------------------------------------------------------------- CLI wiring

def test_email_dry_run_prints_html_without_credentials():
    """--email --dry-run must render HTML from fixtures and need no API key."""
    cfg = os.path.join(HERE, "fixtures", "all_sources_off.yaml")
    env = dict(os.environ)
    env.pop("AGENTMAIL_API_KEY", None)
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "weekly_report.py"),
         "--email", "--dry-run", "--offline", "--config", cfg],
        capture_output=True, text=True, cwd=ROOT, env=env, timeout=120,
    )
    # all_sources_off → no games → exit 1, but never a crash / traceback
    assert "Traceback" not in proc.stderr
    assert proc.returncode == 1
