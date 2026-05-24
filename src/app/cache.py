"""Redis cache helpers. No-op without REDIS_URL.

Used to memoize RapidAPI sold-listing responses so we don't burn the monthly
quota when multiple users grieve in the same town/week. Cache is keyed by
(town, beds_min, beds_max, status) plus an ISO week stamp so freshness rolls
over naturally without explicit eviction.
"""

import datetime
import hashlib
import json
import os


_redis = None  # lazy client


def _client():
    global _redis
    if _redis is not None:
        return _redis
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        import redis
        _redis = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
        # Touch to confirm reachable; if not, fall through to no-cache.
        _redis.ping()
        return _redis
    except Exception as e:
        print(f"Redis unavailable, falling back to no-cache: {e}")
        _redis = None
        return None


def _week_stamp() -> str:
    """ISO-8601 week (e.g. '2026-W20'). Lets cache TTL be expressed as
    'until end of this week' implicitly — different week → different key."""
    today = datetime.date.today()
    iso = today.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _cache_key(prefix: str, parts: list) -> str:
    raw = "|".join(str(p) for p in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"griever:{prefix}:{_week_stamp()}:{digest}"


def get_rapidapi_cached(location: str, beds_min, beds_max, status: str | None):
    """Return the cached JSON list for this query, or None on miss/no-cache."""
    cli = _client()
    if cli is None:
        return None
    try:
        key = _cache_key("rapidapi", [location.lower().strip(), beds_min, beds_max, status or ""])
        raw = cli.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        print(f"Redis get failed: {e}")
        return None


def set_rapidapi_cached(location: str, beds_min, beds_max, status: str | None, data: list, ttl: int = 7 * 24 * 3600):
    """Store the response. Default TTL is 7 days; the ISO-week prefix in the
    key also rolls fresh data in on the week boundary."""
    cli = _client()
    if cli is None:
        return
    try:
        key = _cache_key("rapidapi", [location.lower().strip(), beds_min, beds_max, status or ""])
        cli.set(key, json.dumps(data), ex=ttl)
    except Exception as e:
        print(f"Redis set failed: {e}")
