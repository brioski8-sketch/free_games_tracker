#!/usr/bin/env python3
"""Inspect / seed the Steam watchlist for paid→free change-tracking.

Prints the current appdetails status (name, is_free, price) for a set of appids
so you can decide what to add to `config.yaml -> steam.watched_appids`.

Usage:
    python scripts/seed_steam_watchlist.py 340580 1158310 1238840
    python scripts/seed_steam_watchlist.py --config config.yaml
"""
from __future__ import annotations

import argparse
import os
import sys

# Make the repo package importable when invoked from anywhere (scripts/ subdir).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from free_games_tracker.collectors import steam
from free_games_tracker.config import load_config
from free_games_tracker.httpclient import FetchError, fetch_json


def inspect(appids):
    for appid in appids:
        url = f"{steam.API}?appids={appid}&cc=us&l=en"
        try:
            payload = fetch_json(url, timeout=20, retries=2)
        except FetchError as exc:
            print(f"{appid}: fetch failed ({exc})")
            continue
        data = (payload or {}).get(str(appid)) or {}
        if not data.get("success"):
            print(f"{appid}: not found / denied")
            continue
        info = data.get("data") or {}
        pv = info.get("price_overview") or {}
        price = f"{pv.get('final_formatted', 'n/a')}" if pv else "free (no price_overview)"
        print(f"{appid}: {info.get('name')} | is_free={info.get('is_free')} | {price}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("appids", nargs="*", type=int, help="AppIDs to inspect")
    p.add_argument("--config", default="config.yaml", help="Also show the configured watchlist")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    configured = (cfg.get("steam") or {}).get("watched_appids") or []
    ids = list(dict.fromkeys(list(args.appids) + configured))

    if not ids:
        print("No appids given and none configured. Pass appids or add to config.")
        return 1

    print("Inspecting Steam appdetails for:")
    inspect(ids)
    return 0


if __name__ == "__main__":
    sys.exit(main())
