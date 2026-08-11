"""Notify — write the report to disk (default) and support an optional hook.

The primary deliverable is the markdown report + `free_games.json` written under
`notify.output_dir`. `notify_all()` is the insertion point where you'd hand the
markdown/JSON to a chat gateway (Telegram/Discord/Slack), email, or webhook.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import List, Optional

from .model import GameRecord


def output_paths(output_dir: str, stamp: str) -> tuple[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    md = os.path.join(output_dir, f"free-games-{stamp}.md")
    js = os.path.join(output_dir, "free_games.json")
    return md, js


def write_report(records: List[GameRecord], output_dir: str, *,
                 markdown: Optional[str] = None, source_feeds: Optional[List[str]] = None) -> tuple[str, str, str]:
    """Write markdown + json. Returns (markdown_path, json_path, full_markdown)."""
    import datetime as _dt
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    md_path, js_path = output_paths(output_dir, stamp)

    md = markdown
    if md is None:
        from .report import render_markdown
        md = render_markdown(records, date=stamp, source_feeds=source_feeds)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(render_json_records(records))
    return md_path, js_path, md


def render_json_records(records: List[GameRecord]) -> str:
    from .report import render_json
    return render_json(records)


def notify_all(records: List[GameRecord], markdown: str, cfg) -> None:
    """Dispatch notification. Default is stdout/file only.

    Drop a chat/email/webhook adapter here when you have targets configured.
    This is intentionally a no-op beyond logging so the pipeline is always safe
    to run without external credentials.
    """
    if records:
        _quiet = cfg.get("quiet", False)
        if not _quiet:
            print(markdown)
