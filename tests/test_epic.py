"""Epic collector unit tests — live promotion_window timezone handling.

Regression N1: collectors/epic.py created a naive datetime for the promotion
start (line truncated the ISO-8601 startDate to 19 chars and swapped 'T' for a
space, dropping the offset) while the end stayed a full aware ISO-8601 string.
`_window_label` subtracted aware-from-naive -> TypeError, which was swallowed by
the bare `except (ValueError, TypeError)` -> promotion_window rendered "unknown"
on the live path. These tests pin the requirement that a 7-day giveaway window
renders "168h" (not "unknown"), both at the `_window_label` unit level and
end-to-end through the live `collect()` path with a mocked API response.

Conventions: plain pytest functions, no third-party mocks (repo uses stdlib +
pytest's built-in `monkeypatch` for the network seam). These are offline unit
tests, not `@pytest.mark.network`.
"""
from __future__ import annotations

from free_games_tracker.collectors import epic
from free_games_tracker.config import Config


# --- _window_label unit level -------------------------------------------------

def test_window_label_aware_utc_span_168h():
    # The live API returns full ISO-8601 stamps ending in Z for both bounds.
    assert epic._window_label("2026-08-06T15:00:00.000Z", "2026-08-13T15:00:00.000Z") == "168h"


def test_window_label_mixed_naive_start_aware_end_168h():
    # Regression guard: a naive start ("2026-08-06 15:00:00", the truncated form
    # that the live path previously produced) paired with an aware end must NOT
    # raise the offset-naive/offset-aware TypeError and must render a meaningful
    # label, not "unknown".
    assert epic._window_label("2026-08-06 15:00:00", "2026-08-13T15:00:00.000Z") == "168h"


def test_window_label_offset_inputs_normalized_to_utc():
    # Equal wall-clock bounds in the same offset span exactly 7 days.
    assert epic._window_label("2026-08-06T15:00:00+02:00", "2026-08-13T15:00:00+02:00") == "168h"
    # Equal instants in different offset encodings -> 0h (both bounds aware UTC).
    assert epic._window_label("2026-08-06T07:00:00Z", "2026-08-06T07:00:00+00:00") == "0h"
    # A real instant difference survives offset normalization: 17:00+02:00 ==
    # 15:00 UTC, so span 13:00Z -> 15:00Z is 2h.
    assert epic._window_label("2026-08-06T13:00:00Z", "2026-08-06T17:00:00+02:00") == "2h"


def test_window_label_invalid_inputs_fall_back_to_unknown():
    assert epic._window_label("", "") == "unknown"
    assert epic._window_label("not-a-date", "also-bogus") == "unknown"
    # The live path coerces a missing endDate via `or ""`, so the empty string
    # is the realistic invalid-bound shape.
    assert epic._window_label("2026-08-06T15:00:00.000Z", "") == "unknown"


# --- live collect() path (mocked API response) ---------------------------------

def _payload_with_giveaway():
    """A minimal `freeGamesPromotions` payload mirroring the real API shape.

    startDate/endDate carry millisecond precision with a trailing 'Z'. The live
    path truncated startDate with `[:19].replace('T',' ')` -> a *naive*
    "2026-08-06 15:00" while endDate stayed a full aware string. That mismatch
    is what previously rendered promotion_window as "unknown".
    """
    return {
        "data": {
            "Catalog": {
                "searchStore": {
                    "elements": [
                        {
                            "id": "beacon-pines",
                            "title": "Beacon Pines",
                            "offerType": "BASE_GAME",
                            "productSlug": "beacon-pines",
                            "keyImages": [{"type": "OfferImageWide", "url": "https://cdn/img.jpg"}],
                            "price": {
                                "totalPrice": {
                                    "discountPrice": 0,
                                    "originalPrice": 1999,
                                    "currencyCode": "USD",
                                }
                            },
                            "promotions": {
                                "promotionalOffers": [
                                    {
                                        "promotionalOffers": [
                                            {
                                                "startDate": "2026-08-06T15:00:00.000Z",
                                                "endDate": "2026-08-13T15:00:00.000Z",
                                                "discountSetting": {"discountPercentage": 0},
                                            }
                                        ]
                                    }
                                ],
                                "upcomingPromotionalOffers": [],
                            },
                        }
                    ]
                }
            }
        }
    }


def test_collect_live_path_promotion_window_not_unknown(monkeypatch):
    """Regression: the live collect() path must render a meaningful window.

    Previously line 84 truncated startDate to a naive datetime while endDate
    stayed aware, so _window_label swallowed the TypeError and the output record
    carried promotion_window == "unknown". With the timezone normalization fix
    in place this must be "168h" for a 7-day giveaway.
    """
    def fake_fetch_json(url, timeout=None, retries=None):
        return _payload_with_giveaway()

    monkeypatch.setattr(epic, "fetch_json", fake_fetch_json)
    raw = epic.collect(Config({"epic": {"locale": "en-US", "country": "US"}}))

    assert len(raw) == 1, "mocked payload should yield one candidate"
    rec = raw[0]
    assert rec["store"] == "epic"
    assert rec["title"] == "Beacon Pines"
    assert rec["promotion_window"] == "168h", (
        "7-day giveaway must render '168h', not 'unknown'"
    )
