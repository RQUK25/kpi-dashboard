"""
Data cleaning and normalisation.

Converts raw API / scrape responses into normalised internal data structures
that the analysis layer can consume without knowing about source format details.
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal data model (plain dicts for JSON-serialisability)
# ---------------------------------------------------------------------------

def make_fixture(
    fixture_id: int,
    home_team: str,
    away_team: str,
    home_team_id: int,
    away_team_id: int,
    kickoff: str,
    league_code: str,
    competition_id: int,
) -> Dict:
    return {
        "fixture_id": fixture_id,
        "home_team": home_team,
        "away_team": away_team,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "kickoff": kickoff,
        "league_code": league_code,
        "competition_id": competition_id,
        # Populated later by analysis
        "home_stats": {},
        "away_stats": {},
        "h2h_stats": {},
        "odds": {},
        "xg_data": {},
        "player_stats": [],
    }


# ---------------------------------------------------------------------------
# football-data.org parsers
# ---------------------------------------------------------------------------

def parse_fd_matches(raw: Dict, league_code: str) -> List[Dict]:
    """
    Parse football-data.org /competitions/{id}/matches response.
    Returns a list of fixture dicts.
    """
    if not raw or "matches" not in raw:
        return []

    fixtures = []
    competition_id = None
    if raw.get("competition"):
        competition_id = raw["competition"].get("id")

    for m in raw.get("matches", []):
        if m.get("status") not in ("SCHEDULED", "TIMED", "IN_PLAY", "PAUSED", "FINISHED"):
            continue
        home = m.get("homeTeam", {})
        away = m.get("awayTeam", {})
        fixture = make_fixture(
            fixture_id=m.get("id", 0),
            home_team=home.get("name", home.get("shortName", "Unknown")),
            away_team=away.get("name", away.get("shortName", "Unknown")),
            home_team_id=home.get("id", 0),
            away_team_id=away.get("id", 0),
            kickoff=m.get("utcDate", ""),
            league_code=league_code,
            competition_id=competition_id or 0,
        )
        fixtures.append(fixture)

    return fixtures


def parse_fd_team_season(raw: Dict, team_id: int, venue: str) -> Dict:
    """
    Derive season stats for a team from their match history.
    venue: 'home' or 'away'

    Returns a stats dict with keys like:
      goals_scored_avg, goals_conceded_avg, btts_rate, clean_sheet_rate,
      matches_played, wins, draws, losses
    """
    if not raw or "matches" not in raw:
        return {}

    matches = raw.get("matches", [])
    relevant = []
    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        home_id = m.get("homeTeam", {}).get("id")
        away_id = m.get("awayTeam", {}).get("id")
        score = m.get("score", {}).get("fullTime", {})
        home_goals = score.get("home")
        away_goals = score.get("away")
        if home_goals is None or away_goals is None:
            continue

        if venue == "home" and home_id == team_id:
            relevant.append({
                "scored": home_goals,
                "conceded": away_goals,
                "won": home_goals > away_goals,
                "drawn": home_goals == away_goals,
            })
        elif venue == "away" and away_id == team_id:
            relevant.append({
                "scored": away_goals,
                "conceded": home_goals,
                "won": away_goals > home_goals,
                "drawn": away_goals == home_goals,
            })

    if not relevant:
        return {}

    n = len(relevant)
    scored_total = sum(r["scored"] for r in relevant)
    conceded_total = sum(r["conceded"] for r in relevant)
    btts = sum(1 for r in relevant if r["scored"] > 0 and r["conceded"] > 0)
    clean_sheets = sum(1 for r in relevant if r["conceded"] == 0)
    wins = sum(1 for r in relevant if r["won"])
    draws = sum(1 for r in relevant if r["drawn"])

    return {
        "matches_played": n,
        "goals_scored_avg": round(scored_total / n, 2),
        "goals_conceded_avg": round(conceded_total / n, 2),
        "btts_rate": round(btts / n, 2),
        "clean_sheet_rate": round(clean_sheets / n, 2),
        "win_rate": round(wins / n, 2),
        "draw_rate": round(draws / n, 2),
        "loss_rate": round((n - wins - draws) / n, 2),
    }


def parse_fd_h2h(raw: Dict) -> Dict:
    """
    Parse H2H response into summary stats.
    Returns dict with: matches_played, avg_total_goals, btts_rate, avg_corners (if available)
    """
    if not raw:
        return {}

    matches = raw.get("matches", [])
    finished = [m for m in matches if m.get("status") == "FINISHED"]
    if not finished:
        return {}

    total_goals = []
    btts_count = 0
    for m in finished:
        score = m.get("score", {}).get("fullTime", {})
        hg = score.get("home")
        ag = score.get("away")
        if hg is not None and ag is not None:
            total_goals.append(hg + ag)
            if hg > 0 and ag > 0:
                btts_count += 1

    n = len(total_goals)
    if n == 0:
        return {}

    return {
        "matches_played": n,
        "avg_total_goals": round(sum(total_goals) / n, 2),
        "btts_rate": round(btts_count / n, 2),
    }


# ---------------------------------------------------------------------------
# The-Odds-API parsers
# ---------------------------------------------------------------------------

def parse_odds_for_fixture(
    odds_data: List[Dict],
    home_team: str,
    away_team: str,
) -> Dict:
    """
    Find odds for a specific fixture in the odds response list.
    Normalises team names for fuzzy matching.
    Returns a dict with market -> best_odds mapping.
    """
    if not odds_data:
        return {}

    def normalise(name: str) -> str:
        return name.lower().replace("fc ", "").replace(" fc", "").replace("  ", " ").strip()

    home_n = normalise(home_team)
    away_n = normalise(away_team)

    best_match = None
    best_score = 0
    for event in odds_data:
        eh = normalise(event.get("home_team", ""))
        ea = normalise(event.get("away_team", ""))
        # Simple overlap scoring
        score = (
            sum(1 for w in home_n.split() if w in eh) +
            sum(1 for w in away_n.split() if w in ea)
        )
        if score > best_score:
            best_score = score
            best_match = event

    if not best_match or best_score < 1:
        return {}

    result: Dict[str, Any] = {}
    for bookmaker in best_match.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            key = market.get("key")
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "")
                price = outcome.get("price")
                if price is None:
                    continue
                mkey = f"{key}_{name}".replace(" ", "_").lower()
                # Keep lowest (most generous) odds across bookmakers
                if mkey not in result or price > result[mkey]:
                    result[mkey] = price

    return result


# ---------------------------------------------------------------------------
# Understat parsers
# ---------------------------------------------------------------------------

def parse_understat_league(raw: Any, home_team: str, away_team: str, matchday_date: date) -> Dict:
    """
    Extract xG and shot stats for a specific fixture from Understat league data.
    raw is the datesData structure: list of matches or dict of date -> matches.
    """
    if not raw:
        return {}

    target_date = matchday_date.strftime("%Y-%m-%d")

    def normalise(name: str) -> str:
        return name.lower().strip()

    home_n = normalise(home_team)
    away_n = normalise(away_team)

    # datesData can be a list or a dict
    matches_list = raw if isinstance(raw, list) else []
    if isinstance(raw, dict):
        for key, val in raw.items():
            if isinstance(val, list):
                matches_list.extend(val)

    for match in matches_list:
        if not isinstance(match, dict):
            continue
        mdate = match.get("datetime", match.get("date", ""))
        if target_date not in mdate:
            continue
        mh = normalise(match.get("h", {}).get("title", match.get("team_h", "")))
        ma = normalise(match.get("a", {}).get("title", match.get("team_a", "")))
        if home_n[:4] not in mh and away_n[:4] not in ma:
            continue

        return {
            "home_xg": _safe_float(match.get("xG", {}).get("h") or match.get("xg_home")),
            "away_xg": _safe_float(match.get("xG", {}).get("a") or match.get("xg_away")),
            "home_shots": _safe_int(match.get("shots", {}).get("h") or match.get("home_shots")),
            "away_shots": _safe_int(match.get("shots", {}).get("a") or match.get("away_shots")),
            "understat_match_id": str(match.get("id", "")),
        }

    return {}


def parse_understat_season_averages(raw: Any, team_name: str, venue: str) -> Dict:
    """
    Calculate season average xG and shot stats for a team from datesData.
    venue: 'home' or 'away'
    """
    if not raw:
        return {}

    def normalise(name: str) -> str:
        return name.lower().strip()

    team_n = normalise(team_name)
    venue_key = "h" if venue == "home" else "a"
    opp_key = "a" if venue == "home" else "h"

    matches_list = raw if isinstance(raw, list) else []
    if isinstance(raw, dict):
        for key, val in raw.items():
            if isinstance(val, list):
                matches_list.extend(val)

    xg_for, xg_against, shots_for = [], [], []
    for match in matches_list:
        if not isinstance(match, dict):
            continue
        team_data = match.get(venue_key, {})
        if isinstance(team_data, dict):
            t = normalise(team_data.get("title", ""))
        else:
            t = ""
        if team_n[:4] not in t:
            continue

        xgf = match.get("xG", {}).get(venue_key)
        xga = match.get("xG", {}).get(opp_key)
        sf = match.get("shots", {}).get(venue_key)

        if xgf is not None:
            xg_for.append(_safe_float(xgf))
        if xga is not None:
            xg_against.append(_safe_float(xga))
        if sf is not None:
            shots_for.append(_safe_int(sf))

    if not xg_for:
        return {}

    return {
        "xg_for_avg": round(sum(xg_for) / len(xg_for), 2),
        "xg_against_avg": round(sum(xg_against) / len(xg_against), 2) if xg_against else None,
        "shots_avg": round(sum(shots_for) / len(shots_for), 2) if shots_for else None,
        "games": len(xg_for),
    }


# ---------------------------------------------------------------------------
# FBref parsers
# ---------------------------------------------------------------------------

def parse_fbref_player_stats(records: List[Dict], team_name: str) -> List[Dict]:
    """
    Filter FBref player records to players from a given team.
    Normalises team name for matching.
    """
    if not records:
        return []

    def normalise(name: str) -> str:
        return name.lower().replace("fc ", "").replace(" fc", "").strip()

    team_n = normalise(team_name)
    result = []
    for rec in records:
        team = normalise(str(rec.get("team", "")))
        if team_n[:5] in team or team[:5] in team_n:
            result.append(rec)
    return result


def parse_fbref_league_averages(records: List[Dict]) -> Dict:
    """
    Calculate league average per-90 stats from FBref player records.
    Used for percentile ranking in matchup analysis.
    """
    if not records:
        return {}

    def avg(col: str) -> Optional[float]:
        vals = [r[col] for r in records if isinstance(r.get(col), (int, float)) and r[col] == r[col]]
        return round(sum(vals) / len(vals), 3) if vals else None

    return {
        "dribbles_per90_avg": avg("dribbles_per90"),
        "fouls_committed_per90_avg": avg("fouls_committed_per90"),
        "fouls_drawn_per90_avg": avg("fouls_drawn_per90"),
        "yellow_cards_per90_avg": avg("yellow_cards_per90"),
        "tackles_per90_avg": avg("tackles_per90"),
    }


def parse_fbref_percentile(records: List[Dict], col: str, threshold_pct: float = 0.75) -> float:
    """Return the value at the given percentile for a stat column."""
    vals = sorted(
        r[col] for r in records
        if isinstance(r.get(col), (int, float)) and r[col] == r[col]
    )
    if not vals:
        return 0.0
    idx = max(0, int(len(vals) * threshold_pct) - 1)
    return vals[idx]


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def decimal_to_fractional(decimal_odds: float) -> str:
    """Convert decimal odds to a fractional string like '5/2'."""
    if decimal_odds is None:
        return "—"
    if decimal_odds <= 1.0:
        return "Evs"
    numerator = decimal_odds - 1
    # Find a reasonable fraction
    for denominator in [1, 2, 4, 5, 8, 10, 20, 50, 100]:
        num_candidate = round(numerator * denominator)
        if abs(num_candidate / denominator - numerator) < 0.02:
            from math import gcd
            g = gcd(int(num_candidate), denominator)
            return f"{int(num_candidate) // g}/{denominator // g}"
    # Fallback: multiply by 10 and reduce
    from math import gcd
    n = round(numerator * 10)
    d = 10
    g = gcd(n, d)
    return f"{n // g}/{d // g}"


if __name__ == "__main__":
    # Quick assertions
    assert decimal_to_fractional(2.0) == "1/1", decimal_to_fractional(2.0)
    assert decimal_to_fractional(6.0) == "5/1", decimal_to_fractional(6.0)
    print("parser.py self-test passed.")
