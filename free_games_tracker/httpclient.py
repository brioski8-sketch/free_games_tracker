"""Tiny HTTP helper: UA spoofing, timeouts, optional retries, JSON handling.

Centralizes the few network quirks the collectors share so bumping the UA or
adding backoff is a one-line change.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional
import urllib.request
import urllib.error

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class FetchError(Exception):
    pass


def fetch_json(
    url: str,
    *,
    timeout: int = 20,
    retries: int = 2,
    headers: Optional[dict] = None,
) -> Any:
    """Fetch a URL and parse the response body as JSON.

    Retries on transient errors (5xx, timeouts). Raises FetchError on final
    failure so callers can degrade gracefully.
    """
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = exc
            code = getattr(exc, "code", None)
            if code is not None and 400 <= code < 500:
                # 4xx won't get better on retry
                raise FetchError(f"{url}: HTTP {code}") from exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"{url}: {last_err}") from last_err
