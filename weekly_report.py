#!/usr/bin/env python3
"""Weekly free-games report — HTML email (primary) + Telegram (optional).

Collects *currently available* free games via the free-games collector
(``free_games_collector.get_current_free_games``) and delivers a formatted
report. Two delivery surfaces:

* **HTML email (primary)** — an HTML document with a table of free games,
  the game title hyperlinked directly to its claim/store page, the store
  that is providing the giveaway, and the availability window. Sent via the
  AgentMail SDK.
* **Telegram (optional)** — the original compact HTML message, kept for
  backwards compatibility.

Collection is reused verbatim from the collector, so source gathering,
normalize/dedupe and filtering match the tracker itself.

Usage:

    python weekly_report.py --email               # collect + email the HTML report
    python weekly_report.py --email --dry-run     # print HTML to stdout, don't send
    python weekly_report.py --dry-run             # print the Telegram message
    python weekly_report.py --offline --email     # from committed fixtures
    python weekly_report.py --help

Credentials come from environment variables, ``~/.hermes/config.yaml``
(``mcp_servers.agentmail.env.AGENTMAIL_API_KEY`` or top-level), or a ``.env``
file. Environment variables always win.

    AGENTMAIL_API_KEY=<key>
    TELEGRAM_BOT_TOKEN=<bot token>     # only for the Telegram path
    TELEGRAM_CHAT_ID=<chat or id>      # only for the Telegram path

Exit codes:

    0  success (delivered / dry-run printed)
    1  runtime failure: no current free games, network/API error
    2  configuration failure: missing credentials needed to send
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from free_games_collector import get_current_free_games

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
SEND_TIMEOUT_SECONDS = 20

DEFAULT_EMAIL_TO = "brioski8@gmail.com"
DEFAULT_EMAIL_FROM = "agentvi@agentmail.to"


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
        help="Print the exact outgoing payload to stdout and do not send it.",
    )
    p.add_argument(
        "--email",
        action="store_true",
        help="Deliver the report as an HTML email via AgentMail (primary mode).",
    )
    p.add_argument(
        "--to",
        default=DEFAULT_EMAIL_TO,
        help=f"Recipient email address (default: {DEFAULT_EMAIL_TO}).",
    )
    p.add_argument(
        "--from-inbox",
        default=DEFAULT_EMAIL_FROM,
        help=f"Sender AgentMail inbox (default: {DEFAULT_EMAIL_FROM}).",
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


def get_agentmail_api_key() -> Optional[str]:
    """Resolve the AgentMail API key from env, config.yaml, or ~/.hermes/.env.

    Mirrors the proven lookup order used by the other AgentMail senders
    (env var → mcp_servers.agentmail.env → top-level env → ~/.hermes/.env).
    """
    if os.environ.get("AGENTMAIL_API_KEY"):
        return os.environ["AGENTMAIL_API_KEY"]

    config_path = os.path.expanduser("~/.hermes/config.yaml")
    if os.path.exists(config_path):
        try:
            import yaml

            with open(config_path, "r", errors="ignore") as f:
                cfg = yaml.safe_load(f) or {}
            key = (cfg.get("mcp_servers", {})
                      .get("agentmail", {})
                      .get("env", {})
                      .get("AGENTMAIL_API_KEY"))
            if key:
                return key
            key = (cfg.get("env", {}) or {}).get("AGENTMAIL_API_KEY")
            if key:
                return key
        except Exception as exc:  # pragma: no cover - best-effort lookup
            print(f"[warn] could not read config.yaml: {exc}", file=sys.stderr)

    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", errors="ignore") as f:
                for line in f:
                    if line.startswith("AGENTMAIL_API_KEY="):
                        return line.split("=", 1)[1].strip().strip("\"'")
        except Exception:  # pragma: no cover
            pass

    return None


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #

def _short_date(iso: Optional[str]) -> Optional[str]:
    """Format an ISO-8601 timestamp as YYYY-MM-DD (UTC), or None.

    ``available_until=None`` and ``available_from=None`` mean "permanent /
    unknown", which callers render distinctly from a known date.
    """
    if not iso:
        return None
    try:
        d = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


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


# Host → human store name, used when the collector reports a generic
# "aggregator" source but the claim URL points at a known storefront or
# giveaway platform.
_HOST_STORE = (
    ("epicgames.com", "Epic Games"),
    ("store.steampowered.com", "Steam"),
    ("steampowered.com", "Steam"),
    ("gog.com", "GOG"),
    ("itch.io", "itch.io"),
    ("microsoft.com", "Microsoft Store"),
    ("xbox.com", "Xbox"),
    ("gaming.amazon.com", "Prime Gaming"),
    ("amazon.com", "Amazon / Prime Gaming"),
    ("ubisoft.com", "Ubisoft"),
    ("ea.com", "EA"),
    ("battle.net", "Battle.net"),
    ("humblebundle.com", "Humble Bundle"),
    ("fanatical.com", "Fanatical"),
    ("alienwarearena.com", "Alienware Arena"),
    ("gleam.io", "Gleam.io"),
    ("givee.club", "Givee.club"),
    ("lenovo.com", "Lenovo Gaming"),
    ("indiegala.com", "IndieGala"),
    ("greenmangaming.com", "Green Man Gaming"),
)

_SOURCE_STORE = {"epic": "Epic Games", "gog": "GOG", "steam": "Steam"}


def store_label(game: Dict[str, Any]) -> str:
    """Best-effort human store name for a collector dict.

    Prefers the collector's ``source`` (authoritative for Epic/GOG/Steam
    adapters); otherwise derives the storefront from the claim URL host so an
    r/FGF aggregate entry still tells the reader *which* store is giving the
    game away. Falls back to "Other / giveaway site".
    """
    source = str(game.get("source") or "").strip().lower()
    if source in _SOURCE_STORE:
        return _SOURCE_STORE[source]

    url = str(game.get("url") or "").strip().lower()
    for host, label in _HOST_STORE:
        if host in url:
            return label
    return "Other / giveaway site"


def format_telegram_message(game: Dict[str, Any]) -> str:
    """Render a single collector dict as one Telegram HTML list item.

    ``game`` must have keys ``title``, ``url``, ``available_from``,
    ``available_until``, ``source`` (the collector contract). All dynamic text
    is HTML-escaped; only the claim URL is inserted raw (Telegram requires raw
    URLs in ``href``). Returns a bullet line like::

        • <b>Beacon Pines</b> (Epic Games) — free until <i>2026-08-13</i> · <a href="...">Claim</a>
    """
    title = html.escape(str(game.get("title") or "").strip())
    store = html.escape(store_label(game))

    url = (game.get("url") or "").strip()
    claim_link = f'<a href="{html.escape(url, quote=True)}">Claim</a>' if url else "<b>Claim</b>"

    window = _format_window(game.get("available_from"), game.get("available_until"))
    when = html.escape(window) if window else "free now"

    return f"• <b>{title}</b> ({store}) — {when} · {claim_link}"


def build_message(games: List[Dict[str, Any]], *, date: Optional[str] = None) -> str:
    """Build the complete Telegram HTML message from a list of collector dicts.

    Empty input renders a short "nothing right now" note (the caller decides
    whether that is an error path — see ``main``).
    """
    date = date or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    header = f"<b>🎮 Free games this week — {html.escape(date)}</b>"

    if not games:
        return header + "\n_No paid games are currently free._"

    lines = [header, f"{len(games)} paid game{'s' if len(games) != 1 else ''} now free — act before they expire:"]
    lines.extend(format_telegram_message(g) for g in games)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# HTML email rendering
# --------------------------------------------------------------------------- #

def _subject(games: List[Dict[str, Any]], date: str) -> str:
    n = len(games)
    return f"Free games this week - {date} ({n} game{'s' if n != 1 else ''})"


def render_email_html(games: List[Dict[str, Any]], *, date: Optional[str] = None) -> str:
    """Render a standalone HTML email document for the current free games.

    Each row links the game title directly to its claim/store page and names
    the store providing the giveaway. Inline styles only (email clients strip
    <style> blocks inconsistently). All dynamic text is HTML-escaped.
    """
    date = date or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    n = len(games)

    rows = []
    for g in games:
        title_raw = str(g.get("title") or "").strip()
        url = (g.get("url") or "").strip()
        store = store_label(g)
        window = _format_window(g.get("available_from"), g.get("available_until")) or "free now"

        title_html = html.escape(title_raw or "(untitled)")
        if url:
            title_cell = (
                f'<a href="{html.escape(url, quote=True)}" '
                f'style="color:#1a5fb4;text-decoration:none;font-weight:600;">'
                f'{title_html}</a>'
            )
            claim_cell = (
                f'<a href="{html.escape(url, quote=True)}" '
                f'style="color:#0b5cad;text-decoration:none;font-weight:600;">Claim &rarr;</a>'
            )
        else:
            title_cell = title_html
            claim_cell = "<span style='color:#888;'>no link</span>"

        rows.append(
            "<tr>"
            f'<td style="padding:10px 12px;border-bottom:1px solid #e6e6e6;">{title_cell}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e6e6e6;white-space:nowrap;color:#333;">{html.escape(store)}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e6e6e6;white-space:nowrap;color:#333;">{html.escape(window)}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e6e6e6;white-space:nowrap;">{claim_cell}</td>'
            "</tr>"
        )

    if rows:
        body = (
            '<table role="presentation" cellpadding="0" cellspacing="0" '
            'style="border-collapse:collapse;width:100%;font-size:15px;">'
            "<thead><tr>"
            '<th align="left" style="padding:8px 12px;border-bottom:2px solid #1a5fb4;color:#1a5fb4;font-size:13px;text-transform:uppercase;letter-spacing:.03em;">Game</th>'
            '<th align="left" style="padding:8px 12px;border-bottom:2px solid #1a5fb4;color:#1a5fb4;font-size:13px;text-transform:uppercase;letter-spacing:.03em;">Store</th>'
            '<th align="left" style="padding:8px 12px;border-bottom:2px solid #1a5fb4;color:#1a5fb4;font-size:13px;text-transform:uppercase;letter-spacing:.03em;">Availability</th>'
            '<th align="left" style="padding:8px 12px;border-bottom:2px solid #1a5fb4;color:#1a5fb4;font-size:13px;text-transform:uppercase;letter-spacing:.03em;">Get it</th>'
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )
        intro = (
            f"<strong>{n}</strong> normally-paid game{'s are' if n != 1 else ' is'} "
            f"currently free. Act before the window closes &mdash; tap a title to claim it."
        )
    else:
        body = '<p style="margin:0;color:#444;">No paid games are currently free.</p>'
        intro = "Nothing to claim right now."

    return (
        "<!DOCTYPE html>"
        '<html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Free games - {html.escape(date)}</title></head>"
        '<body style="margin:0;padding:0;background:#f4f5f7;">'
        '<div style="max-width:680px;margin:0 auto;padding:24px 16px;">'
        '<div style="background:#ffffff;border-radius:10px;overflow:hidden;'
        'box-shadow:0 1px 3px rgba(0,0,0,.08);">'
        '<div style="background:#1a5fb4;color:#ffffff;padding:18px 20px;">'
        f'<div style="font-size:20px;font-weight:700;">Free games this week</div>'
        f'<div style="font-size:13px;opacity:.85;margin-top:2px;">{html.escape(date)}</div>'
        "</div>"
        '<div style="padding:18px 20px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#222;">'
        f'<p style="margin:0 0 14px;color:#333;">{intro}</p>'
        f"{body}"
        "</div>"
        '<div style="padding:12px 20px;background:#fafbfc;color:#888;font-size:12px;'
        'border-top:1px solid #eee;">'
        "Sources: Epic Games Store, GOG, Steam, r/FreeGameFindings &mdash; "
        "filtered to genuinely paid games that are now free."
        "</div>"
        "</div></div></body></html>"
    )


def render_email_text(games: List[Dict[str, Any]], *, date: Optional[str] = None) -> str:
    """Plain-text alternative body (deliverability + non-HTML clients)."""
    date = date or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    lines = [f"Free games this week - {date}", ""]
    if not games:
        lines.append("No paid games are currently free.")
        return "\n".join(lines)
    for g in games:
        title = str(g.get("title") or "").strip()
        store = store_label(g)
        window = _format_window(g.get("available_from"), g.get("available_until")) or "free now"
        url = (g.get("url") or "").strip()
        lines.append(f"- {title} [{store}] ({window})")
        if url:
            lines.append(f"  {url}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Delivery — AgentMail HTML email
# --------------------------------------------------------------------------- #

class EmailSendError(Exception):
    """Raised when the email could not be sent (config or transport failure)."""


def send_email(
    subject: str,
    html_body: str,
    text_body: str,
    *,
    to: str = DEFAULT_EMAIL_TO,
    from_inbox: str = DEFAULT_EMAIL_FROM,
) -> str:
    """Send the HTML report via the AgentMail SDK. Returns the message id."""
    api_key = get_agentmail_api_key()
    if not api_key:
        raise EmailSendError(
            "missing AGENTMAIL_API_KEY — set it in the environment, "
            "~/.hermes/config.yaml, or ~/.hermes/.env"
        )

    try:
        from agentmail import AgentMail
    except ImportError as exc:
        raise EmailSendError(
            "agentmail SDK not importable — run under "
            "~/.hermes/hermes-agent/venv/bin/python3"
        ) from exc

    try:
        client = AgentMail(api_key=api_key)
        response = client.inboxes.messages.send(
            inbox_id=from_inbox,
            to=to,
            subject=subject,
            text=text_body,
            html=html_body,
        )
    except Exception as exc:  # transport / API rejection
        raise EmailSendError(f"AgentMail delivery failed: {exc}") from exc

    return str(getattr(response, "id", None) or getattr(response, "message_id", "") or "sent")


# --------------------------------------------------------------------------- #
# Delivery — Telegram (optional, legacy)
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


def _resolve_telegram_credentials() -> Dict[str, str]:
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


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(args.env_file)

    # 1. Collect current free games.
    try:
        games = get_current_free_games(offline=args.offline, config_path=args.config)
    except Exception as exc:  # collector/config/source failure
        print(f"[error] could not collect current free games: {exc}", file=sys.stderr)
        return 1

    date = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

    # 2. Nothing currently free is an alertable condition for a *scheduled*
    #    report — print a readable message and exit nonzero so automation can
    #    notice. (A per-source outage degrades the collector to fewer games,
    #    and zero games most likely means nothing on offer or a source break.)
    if not games:
        note = build_message(games, date=date)
        print(note)
        print("[error] no current free games — nothing to report", file=sys.stderr)
        return 1

    # 3. Build the payload for the chosen surface.
    if args.email:
        subject = _subject(games, date)
        html_body = render_email_html(games, date=date)
        text_body = render_email_text(games, date=date)
    else:
        subject = ""
        html_body = ""
        text_body = build_message(games, date=date)

    # 4. --dry-run prints the exact payload without sending and without needing
    #    credentials (so formatting can be inspected pre-setup).
    if args.dry_run:
        if args.email:
            print(f"[subject] {subject}")
            print("[mime] text/html + text/plain")
            print(html_body)
        else:
            print(text_body)
        return 0

    # 5. Deliver.
    if args.email:
        try:
            msg_id = send_email(subject, html_body, text_body, to=args.to, from_inbox=args.from_inbox)
        except EmailSendError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 2 if "AGENTMAIL_API_KEY" in str(exc) else 1
        print(f"[ok] emailed HTML report to {args.to} "
              f"({len(games)} game(s), id: {msg_id}).")
        return 0

    try:
        creds = _resolve_telegram_credentials()
    except TelegramSendError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    try:
        send_telegram(creds["token"], creds["chat_id"], text_body)
    except TelegramSendError as exc:
        print(f"[error] send failed: {exc}", file=sys.stderr)
        return 1

    print(f"[ok] Telegram message sent to chat {creds['chat_id']} "
          f"({len(games)} game(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
