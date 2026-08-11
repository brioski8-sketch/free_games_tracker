"""SQLite state persistence.

Tracks two kinds of state for idempotency and Steam change detection:

1. **seen promotions** (`seen` table): every `game_id + end_date + free_since`
   that has already been reported. On a re-run, a game whose (id, end_date,
   free_since) triple is already seen is a "still free" rollup, not a new alert.

2. **Steam appid snapshots** (`steam_snapshots` table): per-appid
   `is_free` + `price_overview.final` + timestamp. Used by the Steam adapter to
   detect `is_free False→True` flips (paid→free conversion) — the only honest
   way to separate a conversion from a native F2P title.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Dict, List, Optional, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    game_id   TEXT PRIMARY KEY,
    end_date  TEXT,
    free_since TEXT,
    first_seen TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS steam_snapshots (
    appid      INTEGER PRIMARY KEY,
    is_free    INTEGER NOT NULL,
    final      REAL,
    currency   TEXT,
    observed_at TEXT
);
"""


class StateStore:
    def __init__(self, path: str):
        self.path = path
        if path not in (":memory:",):
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- seen promotions ----------

    def mark_seen(self, game_id: str, end_date: Optional[str], free_since: str, now_iso: str) -> None:
        """Record that this game/event has already been surfaced."""
        self.conn.execute(
            "INSERT INTO seen (game_id, end_date, free_since, first_seen, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(game_id) DO UPDATE SET "
            "  end_date=excluded.end_date, free_since=excluded.free_since, "
            "  updated_at=excluded.updated_at",
            (game_id, end_date, free_since, now_iso, now_iso),
        )
        self.conn.commit()

    def is_seen(self, game_id: str, end_date: Optional[str], free_since: str) -> bool:
        row = self.conn.execute(
            "SELECT end_date, free_since FROM seen WHERE game_id=?", (game_id,)
        ).fetchone()
        if not row:
            return False
        # A changed end_date/free_since is a *new* event worth surfacing again.
        return row[0] == end_date and row[1] == free_since

    def seen_keys(self) -> List[str]:
        return [r[0] for r in self.conn.execute("SELECT game_id FROM seen").fetchall()]

    # ---------- Steam appid snapshots ----------

    def get_steam_snapshot(self, appid: int) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT is_free, final, currency, observed_at FROM steam_snapshots "
            "WHERE appid=?",
            (int(appid),),
        ).fetchone()
        if not row:
            return None
        return {
            "is_free": bool(row[0]),
            "final": row[1],
            "currency": row[2],
            "observed_at": row[3],
        }

    def put_steam_snapshot(self, appid: int, is_free: bool, final: Optional[float], currency: Optional[str], now_iso: str) -> None:
        self.conn.execute(
            "INSERT INTO steam_snapshots (appid, is_free, final, currency, observed_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(appid) DO UPDATE SET "
            "  is_free=excluded.is_free, final=excluded.final, "
            "  currency=excluded.currency, observed_at=excluded.observed_at",
            (int(appid), int(is_free), final, currency, now_iso),
        )
        self.conn.commit()

    def all_steam_appids(self) -> List[int]:
        return [r[0] for r in self.conn.execute("SELECT appid FROM steam_snapshots").fetchall()]

    def close(self) -> None:
        self.conn.close()
