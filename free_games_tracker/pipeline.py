"""Pipeline orchestrator: collect → normalize/dedupe → filter → rank → state → report.

Runs each stage as a pure-ish step (idempotent). The only network/fetch side
effects live in the collectors; `--offline` swaps them for fixture snapshots so
tests and CI can run the whole pipeline deterministically.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List

from .collectors import epic, gog, reddit, steam
from .config import Config
from .filter import filter_records, passes
from .model import GameRecord
from .normalize import dedupe, normalize
from .notify import notify_all, write_report
from .rank import rank
from .report import render_markdown
from .state import StateStore

COLLECTOR_REGISTRY = {
    "epic": epic.collect,
    "steam_flip": steam.collect,
    "gog": gog.collect,
    "reddit": reddit.collect,
}


def collect_all(cfg: Config, state: StateStore, offline: bool = False) -> List[Dict[str, Any]]:
    """Run enabled collectors; return raw candidates.

    In offline mode, reads fixture snapshots from `free_games_tracker/fixtures/`
    committed in the repo (deterministic for CI/tests).
    """
    if offline:
        return _offline_collect(cfg)

    raw: List[Dict[str, Any]] = []
    collectors = cfg.get("collectors") or {}
    for name, fn in COLLECTOR_REGISTRY.items():
        if not collectors.get(name, False):
            continue
        try:
            if name == "steam_flip":
                candidates = fn(cfg, state)
            else:
                candidates = fn(cfg)
            raw.extend(candidates)
        except Exception as exc:  # one bad source shouldn't kill the pipeline
            print(f"[pipeline] collector '{name}' failed: {exc}")
    return raw


def _offline_collect(cfg: Config) -> List[Dict[str, Any]]:
    """Load fixture snapshots committed in the repo (see free_games_tracker/fixtures/).

    Most fixtures are stored in the collector's *raw output* shape and fed
    straight into normalize. The Reddit fixture is stored as the live API payload
    (`r/FreeGameFindings/hot.json` shape) and routed through `reddit.collect` so
    the offline path exercises the SAME parsing logic as a live fetch — that way
    a fabricated `original_price` can never leak in via the fixture when the live
    collector would not have produced it.
    """
    import json
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    fixture_dir = os.path.join(here, "fixtures")
    raw: List[Dict[str, Any]] = []
    collectors = cfg.get("collectors") or {}
    if not os.path.isdir(fixture_dir):
        return raw
    for fname in sorted(os.listdir(fixture_dir)):
        if not fname.endswith(".json"):
            continue
        # only load fixtures for enabled collectors
        stem = fname.replace(".json", "")
        if not collectors.get(stem, False):
            continue
        with open(os.path.join(fixture_dir, fname), "r", encoding="utf-8") as f:
            data = json.load(f)
        if stem == "reddit":
            # Same code path as a live fetch: feed the payload through the
            # collector, which parses original_price from the post metadata.
            raw.extend(reddit.collect(cfg, payload=data))
        else:
            raw.extend(data)
    return raw


class PipelineResult:
    def __init__(self):
        self.raw_count = 0
        self.normalized: List[GameRecord] = []
        self.passing: List[GameRecord] = []
        self.diagnostics: List[dict] = []
        self.ranked: List[GameRecord] = []
        self.new: List[GameRecord] = []
        self.report_md = ""
        self.md_path = ""
        self.json_path = ""


def run(cfg: Config, state: StateStore, *, offline: bool = False,
        mark_state: bool = True, output_dir: str | None = None,
        notify: bool = False) -> PipelineResult:
    res = PipelineResult()

    raw = collect_all(cfg, state, offline=offline)
    res.raw_count = len(raw)

    normalized = normalize(raw)
    normalized = dedupe(normalized)
    res.normalized = normalized

    passing, diag = filter_records(normalized, cfg)
    res.passing = passing
    res.diagnostics = diag

    ranked = rank(passing, cfg.get("sort_mode", "score"))
    res.ranked = ranked

    # New-vs-still-free using the seen table. A record is "new" if not yet seen
    # with its current (id, end_date, free_since) triple.
    now_iso = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new = []
    for rec in ranked:
        is_new = not state.is_seen(rec.game_id, rec.end_date, rec.free_since)
        if mark_state:
            state.mark_seen(rec.game_id, rec.end_date, rec.free_since, now_iso)
        if is_new:
            new.append(rec)
    res.new = new

    out_dir = output_dir or cfg.get("notify", {}).get("output_dir", "reports/")
    md_path, js_path, md = write_report(ranked, out_dir, source_feeds=_feeds(ranked))
    res.report_md = md
    res.md_path = md_path
    res.json_path = js_path

    if notify:
        notify_all(ranked, md, cfg)
    return res


def _feeds(records: List[GameRecord]) -> List[str]:
    seen = set()
    out = []
    for r in records:
        for f in (r.source_feed or "").split(","):
            f = f.strip()
            if f and f not in seen:
                seen.add(f)
                out.append(f)
    return out
