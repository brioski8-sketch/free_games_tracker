#!/usr/bin/env python3
"""Free-games collector: a thin, importable API for "what's free right now".

This module REUSES the existing tracker in ``free_games_tracker/`` rather than
re-implementing any scraping. It runs the documented/authorized source adapters
(Epic freeGamesPromotions, GOG catalog API, r/FreeGameFindings JSON feed)
through the tracker's own ``normalize`` + ``filter`` pipeline, so the curation
contract (reject F2P never-paid, add-ons, demos/trials, non-current offers) is
identical to the tracker itself.

Exposes exactly one public function:

    get_current_free_games(*, offline=False, config_path="config.yaml")
        -> list[dict]

Each dict has the shape:

    {
        "title":           str,   # display title
        "url":             str,   # where to claim the free game
        "available_from":  str|None,  # ISO-8601 UTC, None if unknown
        "available_until": str|None,  # ISO-8601 UTC, None if permanent/unknown
        "source":          str,   # "epic" | "gog" | "aggregator"
    }

Returns ``[]`` when no games are currently free (sources down, nothing on offer,
or offline mode with no fixture hits). No credentials are required by any of the
sources used here, and none are read by this module.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from free_games_tracker.collectors import epic, gog, reddit
from free_games_tracker.config import Config, load_config
from free_games_tracker.filter import filter_records
from free_games_tracker.normalize import dedupe, normalize

# Collectors that answer "what is free *right now*", as ``(name, callable)``.
# ``steam_flip`` is excluded on purpose: it fuses state.db history and only emits
# on paid->free *conversion* events, not on currently-free listings — including
# it for a snapshot would both require a StateStore and give misleading results.
_COLLECTORS = {
    "epic": epic.collect,
    "reddit": reddit.collect,
    "gog": gog.collect,
}
_CURRENT_FREE_COLLECTORS = {name: True for name in _COLLECTORS}

# Default config file, resolved relative to the folder that contains this module
# (the deployable workflow root, which also holds free_games_tracker/ and config.yaml).
_DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def get_current_free_games(
    *,
    offline: bool = False,
    config_path: str | None = None,
) -> List[Dict[str, Any]]:
    """Return the games currently available for free (paid→free giveaways).

    Args:
        offline: read committed fixture snapshots instead of live sources
            (deterministic; used by tests/CI).
        config_path: optional override for config.yaml. When omitted, uses the
            repo's ``config.yaml`` if present, else built-in defaults.

    Returns a list of ``{title, url, available_from, available_until, source}``
    dicts (ISO-8601 UTC windows; ``None`` when unknown/permanent), or ``[]``.
    """
    cfg = _load_cfg(config_path)
    raw = _collect(cfg, offline=offline)
    records = dedupe(normalize(raw))
    passing, _diag = filter_records(records, cfg)
    return [_to_output(rec) for rec in passing]


def _collect(cfg: Config, *, offline: bool) -> List[Dict[str, Any]]:
    """Run the enabled *currently-free* collectors into raw candidates.

    Live mode: fetch each source adapter (degrades to a skip on network error,
    matching the tracker's resilience — one source down never sinks the rest).
    Offline mode: read committed fixture snapshots (the reddit fixture is routed
    through ``reddit.collect`` so the parser under test is the live one).
    """
    enabled = {name: True for name, on in (cfg.get("collectors") or {}).items() if on}

    if offline:
        import json

        here = os.path.dirname(os.path.abspath(__file__))
        fixture_dir = os.path.join(here, "free_games_tracker", "fixtures")
        raw: List[Dict[str, Any]] = []
        if not os.path.isdir(fixture_dir):
            return raw
        for fname in sorted(os.listdir(fixture_dir)):
            if not fname.endswith(".json"):
                continue
            stem = fname.replace(".json", "")
            if stem not in _COLLECTORS or stem not in enabled:
                continue
            with open(os.path.join(fixture_dir, fname), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if stem == "reddit":
                raw.extend(reddit.collect(cfg, payload=data))  # same path as live
            else:
                raw.extend(data)
        return raw

    raw = []
    for name, fn in _COLLECTORS.items():
        if name not in enabled:
            continue
        try:
            raw.extend(fn(cfg))
        except Exception as exc:  # one bad source shouldn't abort the snapshot
            print(f"[free_games_collector] source '{name}' failed: {exc}")
    return raw


def _load_cfg(config_path: str | None) -> Config:
    """Build a Config with *currently-free* collectors enabled.

    Respects an on-disk config if it exists (so keys like ``epic.locale`` /
    ``epic.country`` are honoured) but forces the current-free set so a stale
    ``config.yaml`` that disabled e.g. gog can't silently suppress a source.
    The user-facing override (``collectors`` block) is still layered on top.
    """
    path = config_path or (_DEFAULT_CONFIG if os.path.exists(_DEFAULT_CONFIG) else None)
    cfg = load_config(path)
    merged = dict(_CURRENT_FREE_COLLECTORS)  # canonical enablement for this snapshot
    on_disk = (cfg.get("collectors") or {}) if isinstance(cfg, dict) else {}
    for name in _CURRENT_FREE_COLLECTORS:
        # If the config explicitly turns a source off, honour it; otherwise keep it on.
        if name in on_disk:
            merged[name] = bool(on_disk[name])
    cfg["collectors"] = merged
    return cfg


def _to_output(rec: Any) -> Dict[str, Any]:
    """Map a passing GameRecord to the public output dict."""
    title = getattr(rec, "title", "") or ""
    url = getattr(rec, "offer_url", "") or getattr(rec, "store_url", "") or ""
    store = getattr(rec, "store", "") or ""
    source = {"steam": "steam", "epic": "epic", "gog": "gog"}.get(store, "aggregator")
    return {
        "title": title,
        "url": url,
        "available_from": _iso(getattr(rec, "free_since", None)),
        "available_until": _iso(getattr(rec, "end_date", None)),
        "source": source,
    }


def _iso(value: Optional[str]) -> Optional[str]:
    """Normalize an ISO-8601 bound to ``YYYY-MM-DDTHH:MM:SSZ`` (or None)."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s.replace("+00:00", "Z")[:19] + "Z"
