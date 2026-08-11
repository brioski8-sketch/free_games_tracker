#!/usr/bin/env python3
"""free_games_tracker CLI.

Detect paid PC games that became available for free (free-to-keep giveaways and
permanent paid→free conversions) and report them.

Usage:
    python main.py --config config.yaml
    python main.py --config config.yaml --offline
    python main.py --config config.yaml --digest-only
    python main.py --help
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from free_games_tracker.config import load_config
from free_games_tracker.pipeline import run
from free_games_tracker.state import StateStore


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="free_games_tracker", description=__doc__)
    p.add_argument("--config", default="config.yaml", help="Path to config (YAML preferred).")
    p.add_argument("--state", default=None, help="Override state DB path.")
    p.add_argument("--offline", action="store_true",
                   help="Read fixture snapshots instead of live sources (for CI/tests).")
    p.add_argument("--digest-only", action="store_true",
                   help="Only write reports; suppress stdout notification.")
    p.add_argument("--notify", action="store_true",
                   help="Run the notification adapters (currently no-op without config).")
    p.add_argument("--output-dir", default=None, help="Override report output directory.")
    p.add_argument("--sort", default=None, choices=["score", "newest", "value"],
                   help="Override sort mode.")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    if args.sort:
        cfg["sort_mode"] = args.sort
    if args.digest_only:
        cfg["quiet"] = True

    state_path = args.state or cfg.get("state_db", "state.db")
    state = StateStore(state_path)
    try:
        res = run(cfg, state, offline=args.offline,
                  output_dir=args.output_dir or cfg.get("notify", {}).get("output_dir"),
                  notify=args.notify)
    finally:
        state.close()

    print(f"[done] normalized={len(res.normalized)} passing={len(res.passing)} "
          f"new={len(res.new)}")
    print(f"[done] report -> {res.md_path}")
    print(f"[done] json    -> {res.json_path}")
    if cfg.get("collectors", {}).get("steam_flip") and not args.offline:
        print("[note] Steam change-tracking snapshots updated in state db.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
