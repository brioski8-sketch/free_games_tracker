"""Configuration loading and validation.

Expects a YAML file shaped like `config.yaml`. We avoid a hard dependency on
PyYAML by also accepting a plain `config.ini`-style file or feeding defaults
from a dict (used by tests and the offline harness). If PyYAML is installed
(the requirements pin it), `.yaml`/`.yml` files load fully.
"""
from __future__ import annotations

import os
from typing import Any, Dict

try:
    import yaml as _yaml  # type: ignore
    _HAS_YAML = True
except Exception:  # pragma: no cover
    _yaml = None
    _HAS_YAML = False

DEFAULTS: Dict[str, Any] = {
    "currency_base": "USD",
    "allow_bundles": False,
    "allow_sub_gated": False,
    "min_original_price": 0,
    "sort_mode": "score",  # score | newest | value
    "collectors": {
        "epic": True,
        "steam_flip": True,
        "reddit": True,
        "gog": False,  # feasible but default-off (mostly always-free)
        "ggdeals": False,
        "steamdb": False,
        "freetokeep": False,
        "prime": False,
        "itch": False,
    },
    "epic": {"locale": "en-US", "country": "US"},
    "steam": {"cc": "us", "watched_appids": []},
    "notify": {"output_dir": "reports/"},
    "state_db": "state.db",
    "reddit": {"limit": 25},
    "http": {"timeout": 20, "retries": 2},
}


class Config(dict):
    """Attr-style dict wrapping the resolved config with defaults applied."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError:
            raise AttributeError(item)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | None = None, overrides: Dict[str, Any] | None = None) -> Config:
    raw: Dict[str, Any] = {}

    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            if path.lower().endswith((".yaml", ".yml")) and _yaml is not None:
                loaded = _yaml.safe_load(fh) or {}
            else:
                loaded = _parse_simple(fh.read())
        if isinstance(loaded, dict):
            raw = loaded

    resolved = deep_merge(DEFAULTS, raw)
    if overrides:
        resolved = deep_merge(resolved, overrides)
    return Config(resolved)


def _parse_simple(text: str) -> Dict[str, Any]:
    """Minimal INI-flavoured parser for when PyYAML is unavailable.

    Supports `key: value` and `[section]` blocks, plus booleans/ints/floats.
    Good enough for the flat subset of config we actually use.
    """
    out: Dict[str, Any] = {}
    section: str | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            out.setdefault(section, {})
            continue
        if ":" in line:
            k, v = line.split(":", 1)
        elif "=" in line:
            k, v = line.split("=", 1)
        else:
            continue
        k = k.strip()
        v = v.strip()
        # strip inline comments
        v = v.split("#")[0].strip() if not v.startswith("#") else ""
        val: Any = v
        if v.lower() in ("true", "false"):
            val = v.lower() == "true"
        else:
            try:
                val = int(v)
            except ValueError:
                try:
                    val = float(v)
                except ValueError:
                    val = v
        if section is not None:
            out[section][k] = val
        else:
            out[k] = val
    return out
