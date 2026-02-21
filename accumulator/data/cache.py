"""
Local file-based caching system.

Cache files are named: {source}_{leaguecode}_{YYYYMMDD}.json
All cache files live in /cache directory relative to project root.
Before any external call, callers must check cache first.
"""

import json
import os
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolve cache directory relative to this file's location
CACHE_DIR = Path(__file__).parent.parent / "cache"


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def cache_key(source: str, league_code: str, matchday_date: date) -> str:
    """Return a canonical cache filename (without path)."""
    date_str = matchday_date.strftime("%Y%m%d")
    # Sanitise inputs to avoid path traversal
    source = source.replace("/", "_").replace("..", "_")
    league_code = league_code.replace("/", "_").replace("..", "_")
    return f"{source}_{league_code}_{date_str}.json"


def cache_path(source: str, league_code: str, matchday_date: date) -> Path:
    return CACHE_DIR / cache_key(source, league_code, matchday_date)


def read_cache(source: str, league_code: str, matchday_date: date):
    """Return cached data as a Python object, or None if not cached."""
    _ensure_cache_dir()
    path = cache_path(source, league_code, matchday_date)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.debug("Cache HIT: %s", path.name)
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cache read failed for %s: %s", path.name, exc)
            return None
    logger.debug("Cache MISS: %s", path.name)
    return None


def write_cache(source: str, league_code: str, matchday_date: date, data) -> bool:
    """Write data to cache. Returns True on success."""
    _ensure_cache_dir()
    path = cache_path(source, league_code, matchday_date)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("Cache WRITE: %s", path.name)
        return True
    except OSError as exc:
        logger.warning("Cache write failed for %s: %s", path.name, exc)
        return False


def read_cache_raw(key: str):
    """Read a raw cache file by exact filename key (no date suffix logic)."""
    _ensure_cache_dir()
    path = CACHE_DIR / key
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def write_cache_raw(key: str, data) -> bool:
    """Write a raw cache file by exact filename key."""
    _ensure_cache_dir()
    path = CACHE_DIR / key
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from datetime import date as d
    test_date = d(2024, 8, 17)
    write_cache("test", "PL", test_date, {"hello": "world"})
    result = read_cache("test", "PL", test_date)
    assert result == {"hello": "world"}, f"Unexpected: {result}"
    print("cache.py self-test passed.")
