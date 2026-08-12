#!/usr/bin/env python3
"""Weekly free-games Telegram report.

Collects *currently available* free games via the free-games collector
(``free_games_collector.get_current_free_games``) and posts a formatted
Telegram HTML message to the configured chat.

This script is the Telegram-delivery surface for the free-games tracker. It
reuses ``get_current_free_games`` from Task 0 (the collector), so source
collection, normalize/dedupe and filtering are identical to the tracker. It
adds only two things:

* an HTML message formatter (title, availability window, direct claim URL,
  with proper HTML escaping), and
* a Telegram Bot API sender plus the ``--dry-run`` preview mode.

Usage:

    python weekly_report.py                  # collect + send a Telegram message
    python weekly_report.py --dry-run        # print the exact message, don't send
    python weekly_report.py --offline        # collect from committed fixtures (no network)
    python weekly_report.py --help

Credentials come from environment variables or a ``.env`` file (never
committed); environment variables always win:

    TELEGRAM_BOT_TOKEN=<bot token from @BotFather>
    TELEGRAM_CHAT_ID=<chat or channel id>

Exit codes:

    0  success (message sent, or --dry-run printed)
    1  runtime failure: no current free games, network/Telegram API error
    2  configuration failure: missing credentials needed to send

``--dry-run`` prints the report regardless of credentials so formatting can be
inspected before wiring up a bot; it exits 1 if there are no current free games
so scheduled invocations surface an alertable condition.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from free_games_collector import get_current_free_games

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
SEND_TIMEOUT_SECONDS = 20


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="weekly_report",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--config",
        default=None,
        help="Override path to config.yaml for the collector "
             "(default: repo config.yaml, else built-in defaults).",
    )
    p.add_argument(
        "--offline",
        action="store_true",
        help="Collect from committed fixture snapshots instead of live sources.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the exact outgoing message to stdout and do not send it.",
    )
    p.add_argument(
        "--env-file",
        default=".env",
        help="Path to a .env file to load credentials from (default: ./.env).",
    )
    return p


# --------------------------------------------------------------------------- #
# .env loading (python-dotenv)
# --------------------------------------------------------------------------- #

def load_env_file(path: str) -> bool:
    """Load `KEY=VALUE` pairs from *path* via python-dotenv.

    Environment variables you have already set always win (dotenv's default
    `override=False`). A missing file is not an error — the caller decides what
    is required. Returns True if the file was loaded, False otherwise.
    """
    if not path or not os.path.isfile(path):
        return False
    load_dotenv(path)  # dotenv only sets keys not already in os.environ
    return True


# --------------------------------------------------------------------------- #
# Message formatting
# --------------------------------------------------------------------------- #

def _short_date(iso: Optional[str]) -> Optional[str]:
    """Format an ISO-8601 timestamp as YYYY-MM-DD (UTC), or None.

    ``available_until=None`` and ``available_from=None`` mean "permanent /
    unknown", which callers render distinctly from a known date.
    """
    if not iso:
        return None
    try:
        import datetime as _dt

        d = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def format_telegram_message(game: Dict[str, Any]) -> str:
    """Render a single collector dict as one Telegram HTML list item.

    ``game`` must have keys ``title``, ``url``, ``available_from``,
    ``available_until``, ``source`` (the collector contract). All dynamic text
    is HTML-escaped; only the claim URL is inserted raw (Telegram requires raw
    URLs in ``href``). Returns a bullet line like::

        • <b>Beacon Pines</b> (Epic) — free until <i>2026-08-13</i> · <a href="...">Claim</a>
    """
    title = html.escape(str(game.get("title") or "").strip())
    source = html.escape(str(game.get("source") or "").strip().lower())
    store = {"epic": "Epic", "gog": "GOG", "steam": "Steam"}.get(source, "Aggregator")

    url = (game.get("url") or "").strip()
    claim_link = f'<a href="{html.escape(url, quote=True)}">Claim</a>' if url else "<b>Claim</b>"

    window = _format_window(game.get("available_from"), game.get("available_until"))
    when = html.escape(window) if window else "free now"

    return f"• <b>{title}</b> ({store}) — {when} · {claim_link}"


def _format_window(available_from: Optional[str], available_until: Optional[str]) -> Optional[str]:
    """Render the availability window as a date range.

    Priority: explicit end date > explicit start date > no window. Permanent
    giveaways (available_until is None) are labelled accordingly rather than
    showing a never-ending range.
    """
    start = _short_date(available_from)
    end = _short_date(available_until)

    if end and not start:
        return f"free until {end}"
    if end:
        return f"free {start} → {end}"
    if start:
        return f"free from {start}"
    return None


def build_message(games: List[Dict[str, Any]], *, date: Optional[str] = None) -> str:
    """Build the complete Telegram HTML message from a list of collector dicts.

    Empty input renders a short "nothing right now" note (the caller decides
    whether that is an error path — see ``main``).
    """
    import datetime as _dt

    date = date or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    header = f"<b>🎮 Free games this week — {html.escape(date)}</b>"

    if not games:
        return header + "\n_No paid games are currently free._"

    lines = [header, f"{len(games)} paid game{'s' if len(games) != 1 else ''} now free — act before they expire:"]
    lines.extend(format_telegram_message(g) for g in games)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Telegram sending
# --------------------------------------------------------------------------- #

class TelegramSendError(Exception):
    """Raised when the Telegram Bot API is unreachable or rejects the message."""


def send_telegram(token: str, chat_id: str, text: str, *, timeout: int = SEND_TIMEOUT_SECONDS) -> Dict[str, Any]:
    """POST *text* to the configured Telegram chat via the Bot API.

    Returns the parsed ``result`` object on success. Raises ``TelegramSendError``
    on transport failure or API rejection. The bot token is embedded only in the
    request URL and is never logged or printed.
    """
    url = TELEGRAM_API.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "free_games_tracker-weekly-report/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise TelegramSendError(f"Telegram HTTP {exc.code}: {detail.strip() or exc.reason}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise TelegramSendError(f"could not reach Telegram API: {exc}") from exc

    try:
        response = json.loads(body)
    except json.JSONDecodeError:
        raise TelegramSendError(f"unexpected non-JSON response from Telegram API: {body[:200]}")

    if not response.get("ok"):
        raise TelegramSendError(
            f"Telegram API error: {response.get('description', 'unknown error')} "
            f"(error_code={response.get('error_code', '?')})"
        )
    return response.get("result", response)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def _resolve_credentials() -> Dict[str, str]:
    """Return ``{token, chat_id}`` from env, or raise ``TelegramSendError``."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        missing = [name for name, val in (
            ("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat_id)
        ) if not val]
        raise TelegramSendError(
            "missing required Telegram credential(s): " + ", ".join(missing)
            + ". Set them via environment variables or a .env file "
              "(see .env.example). Run with --dry-run to preview without sending."
        )
    return {"token": token, "chat_id": chat_id}


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(args.env_file)

    # 1. Collect current free games.
    try:
        games = get_current_free_games(offline=args.offline, config_path=args.config)
    except Exception as exc:  # collector/config/source failure
        print(f"[error] could not collect current free games: {exc}", file=sys.stderr)
        return 1

    message = build_message(games)

    # 2. Nothing currently free is an alertable condition for a *scheduled*
    #    report — print a readable message and exit nonzero so automation can
    #    notice. (A per-source outage degrades the collector to fewer games,
    #    and zero games most likely means nothing on offer or a source break.)
    if not games:
        print(message)
        print("[error] no current free games — nothing to report", file=sys.stderr)
        return 1

    # 3. --dry-run prints the exact message without sending and without needing
    #    credentials (so formatting can be inspected pre-setup).
    if args.dry_run:
        print(message)
        return 0

    # 4. Resolve credentials and send.
    try:
        creds = _resolve_credentials()
    except TelegramSendError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    try:
        send_telegram(creds["token"], creds["chat_id"], message)
    except TelegramSendError as exc:
        print(f"[error] send failed: {exc}", file=sys.stderr)
        return 1

    print(f"[ok] Telegram message sent to chat {creds['chat_id']} "
          f"({len(games)} game(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
