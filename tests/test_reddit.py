"""Reddit collector original_price handling + offline/live parity (task B1).

Regression guard: reddit.py must NOT hardcode `original_price: 0.0` for every
post (that made filter.py reject every r/FGF post as `f2p_never_paid`), and the
reddit fixture must go through the SAME parsing code path as a live fetch so a
fabricated price can't leak in via the fixture.
"""
from __future__ import annotations

import os

import pytest

from free_games_tracker.config import Config
from free_games_tracker.collectors import reddit


def _payload(*posts):
    """Wrap post dicts in the r/FGF hot.json Listing envelope."""
    return {
        "kind": "Listing",
        "data": {
            "children": [{"kind": "t3", "data": p} for p in posts],
        },
    }


def _post(title, selftext="", flair=None, id_="x1"):
    return {
        "id": id_, "title": title, "selftext": selftext,
        "link_flair_text": flair, "permalink": f"/r/FreeGameFindings/comments/{id_}/",
        "preview": {"images": [{"source": {"url": "https://preview.redd.it/x.jpg"}}]},
    }


def _collect(*posts, cfg=None):
    return reddit.collect(cfg or Config({}), payload=_payload(*posts))


def test_no_parsable_price_is_rejected_not_passed():
    """A give-away post whose title/body carries NO explicit MSRP must keep
    original_price=0.0 so the filter rejects it as f2p_never_paid — never a
    fabricated passing row."""
    raw = _collect(_post("Boreal Blade free to claim on GOG",
                         selftext="GOG giveaway - grab it while the offer lasts."))
    assert len(raw) == 1
    assert raw[0]["original_price"] == 0.0


def test_parses_demonstrable_msrp_from_selftext():
    raw = _collect(_post("Moonlighter is FREE on Steam (limited time)",
                         selftext="Originally priced at $24.99, now free to keep."))
    assert raw[0]["original_price"] == 24.99
    assert raw[0]["original_price_currency"] == "USD"


def test_parses_demonstrable_msrp_from_title():
    raw = _collect(_post("Metro 2033 was $19.99 on GOG, now free"))
    assert raw[0]["original_price"] == 19.99


def test_price_after_marker_parses():
    raw = _collect(_post("€24.99 was regular price — free now"))
    assert raw[0]["original_price"] == 24.99
    assert raw[0]["original_price_currency"] == "EUR"


def test_unframed_price_is_ignored():
    """A bare price with no MSRP framing (current/regional/unrelated) must NOT be
    read as the paid original price."""
    raw = _collect(_post("Free game of the day $1.99"))
    assert raw[0]["original_price"] == 0.0


def test_f2p_to_paid_flair_is_skipped():
    """'f2p to paid' is the inverse signal (a F2P game became PAID) — never emit
    it as a free giveaway candidate."""
    raw = _collect(
        _post("[F2P to paid] Battlerite is no longer free-to-play",
              selftext="switched to paid", flair="F2P to Paid")
    )
    assert raw == []


def test_offline_fixture_uses_same_code_path_as_live():
    """The committed reddit.json fixture is routed through reddit.collect (same
    parsing logic as a live fetch) in offline mode. A price present in the post
    payload passes; a price-less post does NOT — proving the fixture can't be
    used to smuggle in a fabricated original_price."""
    from free_games_tracker.config import Config
    from free_games_tracker.pipeline import _offline_collect
    cfg = Config({"collectors": {"reddit": True, "epic": False, "steam_flip": False, "gog": False}})
    raw = _offline_collect(cfg)
    by_id = {r["reddit_post_id"]: r for r in raw}
    # demonstrable MSRP in the post body -> parsed
    assert by_id["ab12"]["original_price"] == 24.99
    # price-less giveaway -> rejected path (original_price stays 0.0)
    assert by_id["cd34"]["original_price"] == 0.0
    # inverse-flaired post -> not emitted at all
    assert "ef56" not in by_id


def test_fixture_file_is_real_api_payload_shape(tmp_path):
    """The reddit fixture must look like the live API response (a Listing with
    children), so it flows through collect() exactly like network data."""
    import json
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fixture = os.path.join(here, "free_games_tracker", "fixtures", "reddit.json")
    with open(fixture, encoding="utf-8") as f:
        data = json.load(f)
    assert data["kind"] == "Listing"
    assert "children" in data.get("data", {})


def test_fixture_detected_at_is_deterministic(monkeypatch):
    """Offline runs must be idempotent for the aggregator row too.

    reddit.collect() stamps `detected_at` on every record. For a live fetch the
    fetch time is correct; for a fixture payload the payload may carry its own
    top-level `detected_at` so the aggregator record's free_since (= detected_at
    via normalize) is STABLE across runs. Without this, every offline run emits a
    fresh detected_at and the aggregator row is forever \"new\" (new=1 on every
    run, never idempotent) — the exact offline/live parity gap B1 was meant to
    close. Live payloads have no such field and keep the fetch-time fallback.
    """
    from free_games_tracker.pipeline import _offline_collect
    cfg = Config({"collectors": {"reddit": True, "epic": False, "steam_flip": False, "gog": False}})

    # Fixture path: the committed reddit.json carries a top-level detected_at, so
    # the aggregator row's detected_at (and hence free_since) is stable — same
    # value no matter when the offline run executes.
    raw = _offline_collect(cfg)
    by_id = {r["reddit_post_id"]: r for r in raw}
    assert by_id["ab12"]["detected_at"] == "2026-08-06T15:00:00Z"

    # Live path: a payload WITHOUT detected_at falls back to the fetch time.
    class _FixedNow:
        def strftime(self, fmt):
            return "2026-08-11T00:00:00Z"

    class _FixedDatetime:
        @staticmethod
        def now(tz=None):
            return _FixedNow()

    monkeypatch.setattr(reddit._dt, "datetime", _FixedDatetime)
    live = reddit.collect(cfg, payload={"kind": "Listing", "data": {"children": [
        {"kind": "t3", "data": _post("Something was $9.99, now free", id_="zz1")}]}})
    assert live[0]["detected_at"] == "2026-08-11T00:00:00Z"
