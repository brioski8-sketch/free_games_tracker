"""Zero-or-one notification tests (finding N3).

Covers the "exactly one notification, only when requested" contract using a
mock/spy on the notification function (`notify_all`) to count how many times it
is dispatched, driven through the real CLI entry point:

  * CLI invocation WITHOUT --notify  -> 0 notification calls
  * CLI invocation WITH    --notify  -> exactly 1 notification call

These tests exist to catch the old double-notification bug, where pipeline.py
fired `notify_all` unconditionally and main.py fired it again under --notify.
They run fully offline (fixture snapshots), so no live network is required.
"""
from __future__ import annotations

import os
import tempfile
from unittest import mock

import pytest

from main import main  # the CLI entry point under test


def _write_offline_config(tmpdir: str) -> str:
    """Write a minimal offline config pointing everything at tmpdir."""
    cfg_path = os.path.join(tmpdir, "config.yaml")
    reports_dir = os.path.join(tmpdir, "reports")
    state_db = os.path.join(tmpdir, "state.db")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write(
            "collectors:\n"
            "  epic: true\n"
            "  steam_flip: true\n"
            "  reddit: true\n"
            "  gog: false\n"
            "notify:\n"
            f"  output_dir: {reports_dir}\n"
            f"state_db: {state_db}\n"
            "allow_sub_gated: false\n"
            "sort_mode: score\n"
        )
    return cfg_path


def _cli_command(tmpdir: str, *, notify: bool) -> list[str]:
    cmd = ["--offline", "--config", _write_offline_config(tmpdir)]
    if notify:
        cmd.append("--notify")
    return cmd


@pytest.fixture
def notify_spy():
    """Patch `notify_all` with a shared Mock at both import sites.

    `pipeline.py` binds `notify_all` at module import (`from .notify import
    notify_all`), while the legacy path in `main.py` re-imports it lazily. Both
    are patched to the *same* Mock so any dispatch -- from either call site --
    lands on one counter.
    """
    notifier = mock.Mock()
    patchers = [
        mock.patch("free_games_tracker.pipeline.notify_all", notifier),
        mock.patch("free_games_tracker.notify.notify_all", notifier),
    ]
    for p in patchers:
        p.start()
    try:
        yield notifier
    finally:
        for p in patchers:
            p.stop()


@pytest.mark.parametrize("notify", [False, True])
def test_cli_notification_count(notify: bool, notify_spy):
    """CLI dispatch count: no flag => 0 calls; with flag => exactly 1 call."""
    with tempfile.TemporaryDirectory() as tmp:
        cmd = _cli_command(tmp, notify=notify)
        exit_code = main(cmd)

    assert exit_code == 0
    expected = 1 if notify else 0
    assert notify_spy.call_count == expected, (
        f"expected {expected} notification(s) with --notify={notify!r}, "
        f"got {notify_spy.call_count}"
    )


def test_cli_without_notify_never_calls_notify(notify_spy):
    """Guard: an un-flagged CLI run must stay silent (0 notifications)."""
    with tempfile.TemporaryDirectory() as tmp:
        cmd = _cli_command(tmp, notify=False)
        exit_code = main(cmd)

    assert exit_code == 0
    assert notify_spy.call_count == 0
    # Nothing should even try to pass (unused) arguments to the notification
    notify_spy.assert_not_called()


def test_cli_with_notify_calls_exactly_once(notify_spy):
    """Guard: a --notify CLI run must dispatch exactly one notification."""
    with tempfile.TemporaryDirectory() as tmp:
        cmd = _cli_command(tmp, notify=True)
        exit_code = main(cmd)

    assert exit_code == 0
    notify_spy.assert_called_once()
