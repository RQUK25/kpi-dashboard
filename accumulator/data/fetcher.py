"""
All API calls and scraping logic.

Priority order:
  1. football-data.org  – fixtures, form, records
  2. The-Odds-API       – bookmaker odds (cached aggressively)
  3. Understat.com      – xG, shots, corners
  4. FBref.com          – player-level stats

Each source is isolated: a failure in one must never propagate to others.
"""

import json
import logging
import os
import re
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from data.cache import read_cache, write_cache, read_cache_raw, write_cache_raw

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Activity logger – writes to logs/activity.log
# ---------------------------------------------------------------------------
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "logs" / "activity.log"


def _log_activity(source: str, endpoint: str, success: bool, elapsed_ms: int, note: str = "") -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    status = "SUCCESS" if success else "FAILURE"
    line = f"{ts} | {source:20s} | {status:7s} | {elapsed_ms:6d}ms | {endpoint}"
    if note:
        line += f" | {note}"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Shared session with sensible defaults
# ---------------------------------------------------------------------------
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
})

# ---------------------------------------------------------------------------
# 1. football-data.org
# ---------------------------------------------------------------------------
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"

LEAGUE_CODES = {
    "PL":  2021,  # Premier League
    "ELC": 2016,  # Championship
    "PD":  2014,  # La Liga
    "BL1": 2002,  # Bundesliga
    "SA":  2019,  # Serie A
    "FL1": 2015,  # Ligue 1
    "CL":  2001,  # UEFA Champions League
    "EL":  2333,  # UEFA Europa League
}


def _fd_headers() -> Dict[str, str]:
    key = os.getenv("FOOTBALL_DATA_KEY", "")
    return {"X-Auth-Token": key}


def fetch_fd_matches(league_code: str, matchday_date: date) -> Optional[Dict]:
    """
    Fetch scheduled matches for a given league and date from football-data.org.
    Returns raw API response dict or None on failure.
    Cached per league per day.
    """
    cached = read_cache("fd_matches", league_code, matchday_date)
    if cached is not None:
        return cached

    competition_id = LEAGUE_CODES.get(league_code)
    if not competition_id:
        logger.warning("Unknown league code: %s", league_code)
        return None

    date_str = matchday_date.strftime("%Y-%m-%d")
    url = f"{FOOTBALL_DATA_BASE}/competitions/{competition_id}/matches"
    params = {"dateFrom": date_str, "dateTo": date_str}

    start = time.monotonic()
    try:
        resp = SESSION.get(url, headers=_fd_headers(), params=params, timeout=15)
        elapsed = int((time.monotonic() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()
        _log_activity("football-data.org", url, True, elapsed)
        write_cache("fd_matches", league_code, matchday_date, data)
        return data
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        _log_activity("football-data.org", url, False, elapsed, str(exc))
        logger.error("football-data.org fetch failed: %s", exc)
        return None


def fetch_fd_h2h(fixture_id: int, league_code: str, matchday_date: date) -> Optional[Dict]:
    """
    Fetch last 5 H2H meetings for a fixture.
    """
    cache_key_raw = f"fd_h2h_{fixture_id}_{matchday_date.strftime('%Y%m%d')}.json"
    cached = read_cache_raw(cache_key_raw)
    if cached is not None:
        return cached

    url = f"{FOOTBALL_DATA_BASE}/matches/{fixture_id}/head2head"
    params = {"limit": 5}

    start = time.monotonic()
    try:
        resp = SESSION.get(url, headers=_fd_headers(), params=params, timeout=15)
        elapsed = int((time.monotonic() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()
        _log_activity("football-data.org", url, True, elapsed)
        write_cache_raw(cache_key_raw, data)
        return data
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        _log_activity("football-data.org", url, False, elapsed, str(exc))
        logger.error("football-data.org H2H fetch failed for fixture %s: %s", fixture_id, exc)
        return None


def fetch_fd_team_season(team_id: int, competition_id: int, matchday_date: date) -> Optional[Dict]:
    """Fetch season matches for a team to derive form/stats."""
    season_year = matchday_date.year if matchday_date.month >= 7 else matchday_date.year - 1
    cache_key_raw = f"fd_team_{team_id}_comp_{competition_id}_{season_year}.json"
    cached = read_cache_raw(cache_key_raw)
    if cached is not None:
        return cached

    url = f"{FOOTBALL_DATA_BASE}/teams/{team_id}/matches"
    params = {
        "competitions": competition_id,
        "season": season_year,
        "status": "FINISHED",
        "limit": 40,
    }

    start = time.monotonic()
    try:
        resp = SESSION.get(url, headers=_fd_headers(), params=params, timeout=15)
        elapsed = int((time.monotonic() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()
        _log_activity("football-data.org", url, True, elapsed)
        write_cache_raw(cache_key_raw, data)
        return data
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        _log_activity("football-data.org", url, False, elapsed, str(exc))
        logger.error("football-data.org team season fetch failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 2. The-Odds-API
# ---------------------------------------------------------------------------
ODDS_BASE = "https://api.the-odds-api.com/v4"

LEAGUE_TO_SPORT = {
    "PL":  "soccer_england_premier_league",
    "PD":  "soccer_spain_la_liga",
    "BL1": "soccer_germany_bundesliga",
    "SA":  "soccer_italy_serie_a",
    "FL1": "soccer_france_ligue_one",
}


def fetch_odds(league_code: str, matchday_date: date) -> Optional[List[Dict]]:
    """
    Fetch bookmaker odds for all fixtures in a league on a given day.
    Cached aggressively – one call per league per day maximum.
    """
    cached = read_cache("odds", league_code, matchday_date)
    if cached is not None:
        return cached

    sport = LEAGUE_TO_SPORT.get(league_code)
    if not sport:
        return None

    key = os.getenv("ODDS_API_KEY", "")
    if not key:
        logger.warning("ODDS_API_KEY not set – skipping odds fetch")
        return None

    url = f"{ODDS_BASE}/sports/{sport}/odds"
    params = {
        "apiKey": key,
        "regions": "uk",
        "markets": "h2h,totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }

    start = time.monotonic()
    try:
        resp = SESSION.get(url, params=params, timeout=15)
        elapsed = int((time.monotonic() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()
        _log_activity("the-odds-api", url, True, elapsed)
        write_cache("odds", league_code, matchday_date, data)
        return data
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        _log_activity("the-odds-api", url, False, elapsed, str(exc))
        logger.error("The-Odds-API fetch failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 3. Understat.com
# ---------------------------------------------------------------------------
UNDERSTAT_BASE = "https://understat.com"

LEAGUE_TO_UNDERSTAT = {
    "PL":  "EPL",
    "PD":  "La_liga",
    "BL1": "Bundesliga",
    "SA":  "Serie_A",
    "FL1": "Ligue_1",
}

_understat_last_request: float = 0.0
_UNDERSTAT_DELAY = 2.0  # seconds between requests


def _understat_wait() -> None:
    global _understat_last_request
    elapsed = time.monotonic() - _understat_last_request
    if elapsed < _UNDERSTAT_DELAY:
        time.sleep(_UNDERSTAT_DELAY - elapsed)
    _understat_last_request = time.monotonic()


def _extract_json_var(html: str, var_name: str) -> Optional[Any]:
    """
    Extract a JSON object from a JavaScript variable assignment in page source.
    Pattern:  var VAR_NAME = JSON.parse('...')  or  var VAR_NAME = {...}
    """
    # Try JSON.parse('...') pattern first (Understat encodes data this way)
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*JSON\.parse\('(.+?)'\)"
    match = re.search(pattern, html, re.DOTALL)
    if match:
        raw = match.group(1)
        # Understat uses unicode escapes – unescape then parse
        try:
            decoded = raw.encode("utf-8").decode("unicode_escape")
            return json.loads(decoded)
        except Exception:
            pass
        try:
            return json.loads(raw)
        except Exception:
            pass

    # Fallback: plain assignment pattern
    pattern2 = rf"var\s+{re.escape(var_name)}\s*=\s*(\{{.+?\}}|\[.+?\])\s*;"
    match2 = re.search(pattern2, html, re.DOTALL)
    if match2:
        try:
            return json.loads(match2.group(1))
        except Exception:
            pass

    return None


def fetch_understat_league(league_code: str, matchday_date: date) -> Optional[Dict]:
    """
    Scrape Understat for xG, shot volume, and shot location data for a season.
    Returns a dict keyed by match id with relevant stats, or None on failure.
    """
    cached = read_cache("understat", league_code, matchday_date)
    if cached is not None:
        return cached

    understat_league = LEAGUE_TO_UNDERSTAT.get(league_code)
    if not understat_league:
        return None

    season_year = matchday_date.year if matchday_date.month >= 7 else matchday_date.year - 1
    url = f"{UNDERSTAT_BASE}/league/{understat_league}/{season_year}"

    _understat_wait()
    start = time.monotonic()
    try:
        resp = SESSION.get(url, timeout=20)
        elapsed = int((time.monotonic() - start) * 1000)
        resp.raise_for_status()

        # Extract datesData JS variable which contains match-level xG data
        data = _extract_json_var(resp.text, "datesData")
        if data is None:
            _log_activity("understat.com", url, False, elapsed, "datesData not found")
            logger.warning("Understat: datesData not found at %s", url)
            return None

        _log_activity("understat.com", url, True, elapsed)
        write_cache("understat", league_code, matchday_date, data)
        return data
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        _log_activity("understat.com", url, False, elapsed, str(exc))
        logger.error("Understat fetch failed for %s: %s", league_code, exc)
        return None


def fetch_understat_match(match_id: str, matchday_date: date) -> Optional[Dict]:
    """Scrape individual match page on Understat for detailed shot data."""
    cache_key_raw = f"understat_match_{match_id}_{matchday_date.strftime('%Y%m%d')}.json"
    cached = read_cache_raw(cache_key_raw)
    if cached is not None:
        return cached

    url = f"{UNDERSTAT_BASE}/match/{match_id}"
    _understat_wait()
    start = time.monotonic()
    try:
        resp = SESSION.get(url, timeout=20)
        elapsed = int((time.monotonic() - start) * 1000)
        resp.raise_for_status()

        shotsData = _extract_json_var(resp.text, "shotsData")
        if shotsData is None:
            _log_activity("understat.com", url, False, elapsed, "shotsData not found")
            return None

        result = {"shots": shotsData}
        _log_activity("understat.com", url, True, elapsed)
        write_cache_raw(cache_key_raw, result)
        return result
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        _log_activity("understat.com", url, False, elapsed, str(exc))
        logger.error("Understat match fetch failed %s: %s", match_id, exc)
        return None


# ---------------------------------------------------------------------------
# 4. FBref.com
# ---------------------------------------------------------------------------
FBREF_BASE = "https://fbref.com"

FBREF_LEAGUE_URLS = {
    "PL":  "/en/comps/9/stats/Premier-League-Stats",
    "PD":  "/en/comps/12/stats/La-Liga-Stats",
    "BL1": "/en/comps/20/stats/Bundesliga-Stats",
    "SA":  "/en/comps/11/stats/Serie-A-Stats",
    "FL1": "/en/comps/13/stats/Ligue-1-Stats",
}

FBREF_MISC_URLS = {
    "PL":  "/en/comps/9/misc/Premier-League-Stats",
    "PD":  "/en/comps/12/misc/La-Liga-Stats",
    "BL1": "/en/comps/20/misc/Bundesliga-Stats",
    "SA":  "/en/comps/11/misc/Serie-A-Stats",
    "FL1": "/en/comps/13/misc/Ligue-1-Stats",
}

_fbref_last_request: float = 0.0
_FBREF_DELAY = 3.0  # seconds between requests


def _fbref_wait() -> None:
    global _fbref_last_request
    elapsed = time.monotonic() - _fbref_last_request
    if elapsed < _FBREF_DELAY:
        time.sleep(_FBREF_DELAY - elapsed)
    _fbref_last_request = time.monotonic()


def fetch_fbref_player_stats(league_code: str, matchday_date: date) -> Optional[Any]:
    """
    Scrape FBref for player-level stats using pandas read_html.
    Returns a list of dicts (records) with relevant columns or None.
    Cached per league per matchday date.
    """
    import pandas as pd  # imported here to avoid top-level import delay

    cached = read_cache("fbref_players", league_code, matchday_date)
    if cached is not None:
        return cached

    path = FBREF_LEAGUE_URLS.get(league_code)
    if not path:
        return None

    url = FBREF_BASE + path
    _fbref_wait()
    start = time.monotonic()
    try:
        tables = pd.read_html(url, header=[0, 1])
        elapsed = int((time.monotonic() - start) * 1000)

        # FBref standard stats table is usually the first large table
        # It has a MultiIndex header; flatten it
        if not tables:
            _log_activity("fbref.com", url, False, elapsed, "no tables found")
            return None

        df = tables[0].copy()
        # Flatten MultiIndex columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["_".join(str(c) for c in col).strip("_") for col in df.columns]

        # Drop header rows repeated in data
        df = df[df.iloc[:, 0] != df.columns[0]]
        df = df.dropna(subset=[df.columns[0]])

        # Rename to normalised names where possible
        col_map = {}
        for col in df.columns:
            cl = col.lower()
            if "player" in cl and "player" not in col_map.values():
                col_map[col] = "player"
            elif "squad" in cl or "team" in cl:
                col_map[col] = "team"
            elif "90" in cl and "drib" in cl:
                col_map[col] = "dribbles_per90"
            elif "fls" in cl and "per" in cl:
                col_map[col] = "fouls_committed_per90"
            elif "fld" in cl and "per" in cl:
                col_map[col] = "fouls_drawn_per90"
            elif ("crd" in cl or "yel" in cl) and "per" in cl:
                col_map[col] = "yellow_cards_per90"
            elif "tkl" in cl and "per" in cl:
                col_map[col] = "tackles_per90"

        df = df.rename(columns=col_map)

        # Keep only columns we care about (union of found + originals)
        keep = [c for c in ["player", "team", "dribbles_per90", "fouls_committed_per90",
                             "fouls_drawn_per90", "yellow_cards_per90", "tackles_per90"]
                if c in df.columns]
        if not keep:
            _log_activity("fbref.com", url, False, elapsed, "required columns not found")
            return None

        df = df[keep]
        # Convert numeric columns
        for col in keep:
            if col not in ("player", "team"):
                df[col] = pd.to_numeric(df[col], errors="coerce")

        records = df.to_dict(orient="records")
        _log_activity("fbref.com", url, True, elapsed)
        write_cache("fbref_players", league_code, matchday_date, records)
        return records

    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        _log_activity("fbref.com", url, False, elapsed, str(exc))
        logger.error("FBref player stats fetch failed for %s: %s", league_code, exc)
        return None


def fetch_fbref_misc_stats(league_code: str, matchday_date: date) -> Optional[Any]:
    """
    Scrape FBref miscellaneous stats: fouls, cards, etc.
    Returns list of dicts or None.
    """
    import pandas as pd

    cached = read_cache("fbref_misc", league_code, matchday_date)
    if cached is not None:
        return cached

    path = FBREF_MISC_URLS.get(league_code)
    if not path:
        return None

    url = FBREF_BASE + path
    _fbref_wait()
    start = time.monotonic()
    try:
        tables = pd.read_html(url, header=[0, 1])
        elapsed = int((time.monotonic() - start) * 1000)
        if not tables:
            _log_activity("fbref.com", url, False, elapsed, "no tables")
            return None

        df = tables[0].copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["_".join(str(c) for c in col).strip("_") for col in df.columns]

        df = df[df.iloc[:, 0] != df.columns[0]]
        df = df.dropna(subset=[df.columns[0]])

        col_map = {}
        for col in df.columns:
            cl = col.lower()
            if "player" in cl and "player" not in col_map.values():
                col_map[col] = "player"
            elif "squad" in cl or "team" in cl:
                col_map[col] = "team"
            elif "crd" in cl and "y" in cl:
                col_map[col] = "yellow_cards"
            elif "crd" in cl and "r" in cl:
                col_map[col] = "red_cards"
            elif "fls" in cl:
                col_map[col] = "fouls_committed"
            elif "fld" in cl:
                col_map[col] = "fouls_drawn"

        df = df.rename(columns=col_map)
        keep = [c for c in ["player", "team", "yellow_cards", "red_cards",
                             "fouls_committed", "fouls_drawn"]
                if c in df.columns]
        df = df[keep] if keep else df
        for col in keep:
            if col not in ("player", "team"):
                df[col] = pd.to_numeric(df[col], errors="coerce")

        records = df.to_dict(orient="records")
        _log_activity("fbref.com", url, True, elapsed)
        write_cache("fbref_misc", league_code, matchday_date, records)
        return records

    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        _log_activity("fbref.com", url, False, elapsed, str(exc))
        logger.error("FBref misc stats fetch failed for %s: %s", league_code, exc)
        return None


# ---------------------------------------------------------------------------
# Source status helper
# ---------------------------------------------------------------------------
def get_source_statuses(league_codes: List[str], matchday_date: date) -> Dict[str, str]:
    """
    Return a dict of source -> status ('ok', 'partial', 'failed') for the UI.
    This only checks cache/connectivity quickly without making new requests.
    """
    statuses = {}
    for league in league_codes:
        fd = read_cache("fd_matches", league, matchday_date)
        statuses[f"football-data_{league}"] = "ok" if fd else "unknown"
        odds = read_cache("odds", league, matchday_date)
        statuses[f"odds-api_{league}"] = "ok" if odds else "unknown"
        us = read_cache("understat", league, matchday_date)
        statuses[f"understat_{league}"] = "ok" if us else "unknown"
        fb = read_cache("fbref_players", league, matchday_date)
        statuses[f"fbref_{league}"] = "ok" if fb else "unknown"
    return statuses


if __name__ == "__main__":
    print("fetcher.py loaded OK – individual fetchers require API keys in .env")
