"""Idempotency tests — re-running on the same snapshot produces identical output
and does NOT re-notify already-seen games as "new" (spec §4.6 / §6.4)."""
from __future__ import annotations

import os
import tempfile
from free_games_tracker.config import Config
from free_games_tracker.pipeline import run
from free_games_tracker.state import StateStore


def _cfg(tmpdir: str) -> Config:
    return Config({
        "sort_mode": "score",
        "collectors": {"epic": True, "steam_flip": True, "reddit": True, "gog": False},
        "notify": {"output_dir": os.path.join(tmpdir, "reports")},
        "state_db": os.path.join(tmpdir, "state.db"),
        "allow_sub_gated": False,
    })


def _first_run(tmpdir: str):
    cfg = _cfg(tmpdir)
    state = StateStore(cfg["state_db"])
    try:
        return run(cfg, state, offline=True)
    finally:
        state.close()


def test_two_runs_identical_report_and_no_dup_new():
    with tempfile.TemporaryDirectory() as tmp:
        run1 = _first_run(tmp)
        # second run reusing same state.db → no new alerts
        cfg = _cfg(tmp)
        state = StateStore(cfg["state_db"])
        try:
            run2 = run(cfg, state, offline=True)
        finally:
            state.close()

        assert len(run1.new) > 0, "expected new alerts on first run"
        assert run2.new == [], "second run should surface no NEW alerts"
        # identical report content (same date stamp logic aside — compare bodies)
        assert run1.report_md == run2.report_md
        assert run1.json_path == run2.json_path


def test_changed_end_date_is_new_again():
    with tempfile.TemporaryDirectory() as tmp:
        run1 = _first_run(tmp)
        # Simulate a changed event for one game by poking the state DB directly:
        # mark the game with a DIFFERENT end_date than what's recorded.
        cfg = _cfg(tmp)
        state = StateStore(cfg["state_db"])
        game = run1.ranked[0]
        # Change end_date in the DB so is_seen returns False for the new triple
        state.conn.execute(
            "UPDATE seen SET end_date='2099-01-01T00:00:00Z' WHERE game_id=?",
            (game.game_id,),
        )
        state.conn.commit()
        run2 = run(cfg, state, offline=True)
        state.close()
        # The game whose end_date changed should surface as new again
        new_ids = {r.game_id for r in run2.new}
        assert game.game_id in new_ids
