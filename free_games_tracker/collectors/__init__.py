"""Source adapter package.

Each module exposes a `collect(cfg) -> list[dict]` of raw candidate objects with
at least: store, title, current_price, store_url, offer_url, detected_at, plus
adapter-specific fields the normalizer consumes.
"""
