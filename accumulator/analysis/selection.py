"""
Selection logic and confidence scoring.

Five-step pipeline per selection:
  1. Season average check
  2. H2H check (with penalty)
  3. Matchup bonus
  4. Value check (vs bookmaker implied probability)
  5. Final confidence score (1–10)
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from data.parser import decimal_to_fractional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Market definitions
# ---------------------------------------------------------------------------

MARKETS = {
    "btts_yes": {
        "label": "Both Teams to Score - Yes",
        "requires": ["fd"],
        "stat_key": "btts_rate",
        "direction": "over",  # season stat should be >= threshold
        "threshold": 0.5,
    },
    "btts_no": {
        "label": "Both Teams to Score - No",
        "requires": ["fd"],
        "stat_key": "btts_rate",
        "direction": "under",
        "threshold": 0.5,
    },
    "corners_over_85": {
        "label": "Total Corners Over 8.5",
        "requires": ["understat"],
        "stat_key": "corners_per_game_approx",
        "direction": "over",
        "threshold": 8.5,
    },
    "corners_over_95": {
        "label": "Total Corners Over 9.5",
        "requires": ["understat"],
        "stat_key": "corners_per_game_approx",
        "direction": "over",
        "threshold": 9.5,
    },
    "corners_over_105": {
        "label": "Total Corners Over 10.5",
        "requires": ["understat"],
        "stat_key": "corners_per_game_approx",
        "direction": "over",
        "threshold": 10.5,
    },
    "corners_over_115": {
        "label": "Total Corners Over 11.5",
        "requires": ["understat"],
        "stat_key": "corners_per_game_approx",
        "direction": "over",
        "threshold": 11.5,
    },
    "shots_on_target_over": {
        "label": "Total Shots on Target Over",
        "requires": ["understat"],
        "stat_key": "shots_on_target_avg",
        "direction": "over",
        "threshold": 7.5,
    },
    "shots_outside_box_over": {
        "label": "Total Shots Outside Box Over",
        "requires": ["understat"],
        "stat_key": "shots_outside_box_avg",
        "direction": "over",
        "threshold": 5.5,
    },
    "fouls_over": {
        "label": "Total Fouls Over",
        "requires": ["fbref"],
        "stat_key": "fouls_per_game_avg",
        "direction": "over",
        "threshold": 20.5,
    },
    "cards_over_25": {
        "label": "Total Cards Over 2.5",
        "requires": ["fbref"],
        "stat_key": "cards_per_game_avg",
        "direction": "over",
        "threshold": 2.5,
    },
    "cards_over_35": {
        "label": "Total Cards Over 3.5",
        "requires": ["fbref"],
        "stat_key": "cards_per_game_avg",
        "direction": "over",
        "threshold": 3.5,
    },
    "cards_over_45": {
        "label": "Total Cards Over 4.5",
        "requires": ["fbref"],
        "stat_key": "cards_per_game_avg",
        "direction": "over",
        "threshold": 4.5,
    },
    "asian_handicap_home": {
        "label": "Asian Handicap - Home",
        "requires": ["fd", "understat"],
        "stat_key": "xg_advantage",
        "direction": "over",
        "threshold": 0.4,
    },
    "asian_handicap_away": {
        "label": "Asian Handicap - Away",
        "requires": ["fd", "understat"],
        "stat_key": "xg_advantage_away",
        "direction": "over",
        "threshold": 0.4,
    },
    "correct_score": {
        "label": "Correct Score",
        "requires": ["understat"],
        "stat_key": "predicted_score",
        "direction": "exact",
        "threshold": None,
        "high_tier_only": True,
    },
}

PLAYER_CARD_MARKET = "player_to_receive_card"


# ---------------------------------------------------------------------------
# Step 1: Season average check
# ---------------------------------------------------------------------------

def season_average_check(
    market_key: str,
    fixture_stats: Dict,
) -> Tuple[bool, float, str]:
    """
    Check if the season average for both teams supports the market threshold.
    Returns (passes, combined_stat_value, explanation).
    """
    market = MARKETS.get(market_key)
    if not market:
        return False, 0.0, "Unknown market"

    stat_key = market["stat_key"]
    direction = market["direction"]
    threshold = market["threshold"]

    home_stats = fixture_stats.get("home_stats", {})
    away_stats = fixture_stats.get("away_stats", {})

    home_val = home_stats.get(stat_key)
    away_val = away_stats.get(stat_key)

    # Special handling for combined stats
    if market_key.startswith("corners") or market_key.startswith("shots") or market_key.startswith("fouls") or market_key.startswith("cards"):
        # Sum home + away for totals markets
        if home_val is not None and away_val is not None:
            combined = home_val + away_val
        elif home_val is not None:
            combined = home_val * 2  # extrapolate from one side
        elif away_val is not None:
            combined = away_val * 2
        else:
            return False, 0.0, f"No data for {stat_key}"
    elif market_key == "btts_yes":
        if home_val is not None and away_val is not None:
            combined = (home_val + away_val) / 2
        else:
            return False, 0.0, "No BTTS data"
    elif market_key == "btts_no":
        if home_val is not None and away_val is not None:
            combined = 1 - (home_val + away_val) / 2
        else:
            return False, 0.0, "No BTTS data"
    elif market_key in ("asian_handicap_home", "asian_handicap_away"):
        combined = fixture_stats.get("xg_data", {}).get("xg_advantage", 0.0)
    elif market_key == "correct_score":
        return True, 0.0, "Correct score evaluated separately"
    else:
        combined = home_val if home_val is not None else 0.0

    if direction == "over":
        passes = combined >= threshold
        explanation = f"Combined {stat_key}: {combined:.2f} {'≥' if passes else '<'} {threshold}"
    elif direction == "under":
        passes = combined <= threshold
        explanation = f"Combined {stat_key}: {combined:.2f} {'≤' if passes else '>'} {threshold}"
    else:
        passes = True
        explanation = "Exact market - proceeding"

    return passes, combined, explanation


# ---------------------------------------------------------------------------
# Step 2: H2H check
# ---------------------------------------------------------------------------

def h2h_check(
    market_key: str,
    season_stat: float,
    h2h_stats: Dict,
) -> Tuple[int, bool]:
    """
    Compare season stat with H2H average.
    Returns (confidence_penalty, h2h_conflict_flag).
    """
    market = MARKETS.get(market_key)
    if not market or not h2h_stats:
        return 0, False

    stat_key = market["stat_key"]

    # Map market stat to H2H equivalent
    h2h_key_map = {
        "btts_rate": "btts_rate",
        "corners_per_game_approx": "avg_total_goals",  # proxy
        "fouls_per_game_avg": "avg_total_goals",  # proxy
        "cards_per_game_avg": "avg_total_goals",  # proxy
        "xg_advantage": "avg_total_goals",
    }
    h2h_key = h2h_key_map.get(stat_key)
    h2h_val = h2h_stats.get(h2h_key) if h2h_key else None

    if h2h_val is None or season_stat == 0:
        return 0, False

    divergence = abs(h2h_val - season_stat) / max(abs(season_stat), 0.01)

    if divergence > 0.20:
        return -1, True

    return 0, False


# ---------------------------------------------------------------------------
# Step 3: Matchup bonus
# ---------------------------------------------------------------------------

def matchup_bonus(market_key: str, fixture_matchups: List[Dict]) -> int:
    """
    Return +1 if any matchup directly supports this market.
    """
    market = MARKETS.get(market_key, {})
    market_label = market.get("label", "")

    for matchup in fixture_matchups:
        supported = matchup.get("market_supported", "")
        if (
            market_key in supported.lower()
            or supported.lower() in market_label.lower()
            or _markets_overlap(market_label, supported)
        ):
            return 1
    return 0


def _markets_overlap(label: str, supported: str) -> bool:
    keywords = {
        "cards": ["card", "yellow"],
        "fouls": ["foul"],
        "corners": ["corner", "set piece"],
        "btts": ["btts", "both teams", "set piece"],
    }
    ll = label.lower()
    sl = supported.lower()
    for group_keys in keywords.values():
        if any(k in ll for k in group_keys) and any(k in sl for k in group_keys):
            return True
    return False


# ---------------------------------------------------------------------------
# Step 4: Value check
# ---------------------------------------------------------------------------

def value_check(
    confidence_pct: float,
    bookmaker_odds: Optional[float],
) -> Tuple[bool, Optional[float]]:
    """
    Returns (value_flag, implied_probability).
    value_flag = True means bookmaker over-prices the market (implied prob > our estimate + 10pp).
    """
    if bookmaker_odds is None or bookmaker_odds <= 1.0:
        return False, None

    implied_prob = 1.0 / bookmaker_odds
    our_estimate = confidence_pct / 100.0

    # If bookmaker's implied probability is more than 10 percentage points
    # higher than our estimate, the market offers poor value
    value_flag = implied_prob > (our_estimate + 0.10)
    return value_flag, round(implied_prob * 100, 1)


# ---------------------------------------------------------------------------
# Step 5: Confidence score
# ---------------------------------------------------------------------------

def confidence_score(
    combined_stat: float,
    threshold: float,
    direction: str,
    h2h_penalty: int,
    matchup_bonus_val: int,
) -> int:
    """
    Score 1–10.
    Base score (1–8) from how strongly the season stat supports the threshold.
    Modified by H2H penalty (-1) and matchup bonus (+1).
    Capped at 10.
    """
    if direction == "over" and threshold > 0:
        margin = (combined_stat - threshold) / threshold
    elif direction == "under" and threshold > 0:
        margin = (threshold - combined_stat) / threshold
    else:
        margin = 0.0

    # Map margin to base score 1–8
    if margin >= 0.40:
        base = 8
    elif margin >= 0.25:
        base = 7
    elif margin >= 0.15:
        base = 6
    elif margin >= 0.05:
        base = 5
    elif margin >= 0.0:
        base = 4
    else:
        base = max(1, int(3 + margin * 10))  # negative margin → low base

    score = base + h2h_penalty + matchup_bonus_val
    return max(1, min(10, score))


# ---------------------------------------------------------------------------
# Player card selection
# ---------------------------------------------------------------------------

def evaluate_player_card_selections(
    home_players: List[Dict],
    away_players: List[Dict],
    all_league_players: List[Dict],
    fixture_matchups: List[Dict],
    odds_data: Dict,
    h2h_stats: Dict,
) -> List[Dict]:
    """
    Evaluate player to receive a card selections.
    Criteria:
    - Minimum 3 cards this season (approximated by yellow_cards stat)
    - Per-90 yellow card rate above 0.3
    """
    if not all_league_players:
        return []

    # Compute league average for yellow cards per 90
    yc_vals = [
        r["yellow_cards_per90"]
        for r in all_league_players
        if isinstance(r.get("yellow_cards_per90"), float) and r["yellow_cards_per90"] == r["yellow_cards_per90"]
    ]
    league_yc_avg = sum(yc_vals) / len(yc_vals) if yc_vals else 0.3

    selections = []
    all_players = home_players + away_players

    for player in all_players:
        yc90 = player.get("yellow_cards_per90")
        if not isinstance(yc90, float) or yc90 < 0.3:
            continue

        # Approximate total cards from per-90 rate × estimated minutes
        # We don't have exact minutes, so use a simple threshold
        # The requirement of "minimum 3 cards this season" is approximated
        # by yc_per90 > 0.3 being a sustained rate (not a one-off)

        player_name = player.get("player", "Unknown")

        # Try to find player card odds
        odds_key = f"h2h_{player_name.lower().replace(' ', '_')}"
        bookmaker_odds = odds_data.get(odds_key)

        # Base confidence from per-90 rate
        base_conf_pct = min(85, yc90 / league_yc_avg * 40)

        # Matchup bonus
        mb = matchup_bonus(PLAYER_CARD_MARKET, fixture_matchups)

        # H2H check (limited for player markets – use generic penalty 0)
        h2h_pen = 0

        raw_score = confidence_score(yc90, 0.3, "over", h2h_pen, mb)

        value_flag, implied_prob = value_check(base_conf_pct, bookmaker_odds)

        selections.append({
            "player": player_name,
            "team": player.get("team", ""),
            "market": "Player to Receive a Card",
            "yellow_cards_per90": round(yc90, 2),
            "confidence": raw_score,
            "confidence_pct": round(base_conf_pct, 1),
            "value_flag": value_flag,
            "h2h_conflict": False,
            "matchup_boost": mb > 0,
            "bookmaker_odds": bookmaker_odds,
            "implied_probability": implied_prob,
            "key_stats": {
                "yellow_cards_per90": round(yc90, 2),
                "league_avg_yc_per90": round(league_yc_avg, 3),
            },
        })

    # Sort by confidence descending
    selections.sort(key=lambda x: x["confidence"], reverse=True)
    return selections[:3]  # Return top 3 candidates


# ---------------------------------------------------------------------------
# Main selection evaluator
# ---------------------------------------------------------------------------

def evaluate_fixture_selections(
    fixture: Dict,
    fixture_matchups: List[Dict],
    available_sources: Dict[str, bool],
) -> List[Dict]:
    """
    Run all five steps for every applicable market on a fixture.
    Returns list of selection dicts ready for tier building.
    """
    home_stats = fixture.get("home_stats", {})
    away_stats = fixture.get("away_stats", {})
    h2h_stats = fixture.get("h2h_stats", {})
    odds_data = fixture.get("odds", {})
    xg_data = fixture.get("xg_data", {})

    fd_available = available_sources.get("fd", False)
    understat_available = available_sources.get("understat", False)
    fbref_available = available_sources.get("fbref", False)
    odds_available = available_sources.get("odds", False)

    source_map = {
        "fd": fd_available,
        "understat": understat_available,
        "fbref": fbref_available,
    }

    selections = []

    for market_key, market_def in MARKETS.items():
        # Check if required sources are available
        required = market_def.get("requires", [])
        if not all(source_map.get(src, False) for src in required):
            continue

        # Merge xg_data into fixture_stats for lookup
        fixture_stats_merged = {
            "home_stats": home_stats,
            "away_stats": away_stats,
            "xg_data": xg_data,
        }

        # Step 1: Season average check
        passes, combined_stat, explanation = season_average_check(market_key, fixture_stats_merged)
        if not passes:
            continue

        market_def_copy = MARKETS[market_key]
        threshold = market_def_copy["threshold"] or 0.0
        direction = market_def_copy["direction"]

        # Step 2: H2H check
        h2h_penalty, h2h_conflict = h2h_check(market_key, combined_stat, h2h_stats)

        # Step 3: Matchup bonus
        mb = matchup_bonus(market_key, fixture_matchups)

        # Step 5: Confidence score
        conf = confidence_score(combined_stat, threshold, direction, h2h_penalty, mb)

        # Step 4: Value check
        # Derive bookmaker odds for this market
        bk_odds = _lookup_odds(market_key, odds_data)
        conf_pct = conf / 10.0 * 100
        value_flag, implied_prob = value_check(conf_pct, bk_odds)

        selection = {
            "fixture_id": fixture.get("fixture_id"),
            "home_team": fixture.get("home_team"),
            "away_team": fixture.get("away_team"),
            "league_code": fixture.get("league_code"),
            "market_key": market_key,
            "market_label": market_def_copy["label"],
            "selection": _derive_selection_label(market_key, fixture, xg_data),
            "confidence": conf,
            "confidence_pct": round(conf_pct, 1),
            "combined_stat": round(combined_stat, 3),
            "threshold": threshold,
            "season_avg_explanation": explanation,
            "h2h_penalty": h2h_penalty,
            "h2h_conflict": h2h_conflict,
            "matchup_boost": mb > 0,
            "value_flag": value_flag,
            "bookmaker_odds": bk_odds,
            "implied_probability": implied_prob,
            "decimal_odds": bk_odds,
            "fractional_odds": decimal_to_fractional(bk_odds) if bk_odds else None,
            "high_tier_only": market_def_copy.get("high_tier_only", False),
            "key_stats": _build_key_stats(market_key, home_stats, away_stats, xg_data),
        }
        selections.append(selection)

    return selections


def _lookup_odds(market_key: str, odds_data: Dict) -> Optional[float]:
    """Attempt to find matching bookmaker odds for a market key."""
    if not odds_data:
        return None

    odds_key_map = {
        "btts_yes": "h2h_yes",
        "btts_no": "h2h_no",
        "corners_over_85": "totals_over_8.5",
        "corners_over_95": "totals_over_9.5",
        "corners_over_105": "totals_over_10.5",
        "corners_over_115": "totals_over_11.5",
        "shots_on_target_over": "totals_over_7.5",
        "fouls_over": "totals_over_20.5",
        "cards_over_25": "totals_over_2.5",
        "cards_over_35": "totals_over_3.5",
        "cards_over_45": "totals_over_4.5",
        "asian_handicap_home": "h2h_home",
        "asian_handicap_away": "h2h_away",
    }

    key = odds_key_map.get(market_key)
    if key:
        # Try a few variant lookups
        for candidate in [key, key.replace(".", ""), key.replace("_", " ")]:
            for k, v in odds_data.items():
                if candidate.lower() in k.lower():
                    return v

    return None


def _derive_selection_label(market_key: str, fixture: Dict, xg_data: Dict) -> str:
    """Build a human-readable selection label."""
    home = fixture.get("home_team", "Home")
    away = fixture.get("away_team", "Away")

    labels = {
        "btts_yes": "Both Teams to Score - Yes",
        "btts_no": "Both Teams to Score - No",
        "corners_over_85": "Total Corners Over 8.5",
        "corners_over_95": "Total Corners Over 9.5",
        "corners_over_105": "Total Corners Over 10.5",
        "corners_over_115": "Total Corners Over 11.5",
        "shots_on_target_over": "Total Shots on Target Over 7.5",
        "shots_outside_box_over": "Total Shots Outside Box Over 5.5",
        "fouls_over": "Total Fouls Over 20.5",
        "cards_over_25": "Total Cards Over 2.5",
        "cards_over_35": "Total Cards Over 3.5",
        "cards_over_45": "Total Cards Over 4.5",
        "asian_handicap_home": f"{home} -0.5 Asian Handicap",
        "asian_handicap_away": f"{away} -0.5 Asian Handicap",
        "correct_score": _predict_correct_score(xg_data),
    }
    return labels.get(market_key, market_key)


def _predict_correct_score(xg_data: Dict) -> str:
    """Estimate most likely correct score from xG data using Poisson approximation."""
    import math

    home_xg = xg_data.get("home_xg", 1.3)
    away_xg = xg_data.get("away_xg", 1.1)

    if not home_xg or not away_xg:
        return "1-1"

    # Find most probable score using Poisson PMF
    best_prob = 0
    best_score = (1, 1)
    for h in range(5):
        for a in range(5):
            p = _poisson_pmf(home_xg, h) * _poisson_pmf(away_xg, a)
            if p > best_prob:
                best_prob = p
                best_score = (h, a)
    return f"{best_score[0]}-{best_score[1]}"


def _poisson_pmf(lam: float, k: int) -> float:
    import math
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k * math.exp(-lam)) / math.factorial(k)


def _build_key_stats(market_key: str, home_stats: Dict, away_stats: Dict, xg_data: Dict) -> Dict:
    """Compile the key stats to display in the expanded selection row."""
    stats: Dict = {}

    if market_key.startswith("btts"):
        stats["home_btts_rate"] = home_stats.get("btts_rate")
        stats["away_btts_rate"] = away_stats.get("btts_rate")
        stats["home_goals_avg"] = home_stats.get("goals_scored_avg")
        stats["away_goals_avg"] = away_stats.get("goals_scored_avg")
    elif market_key.startswith("corners"):
        stats["home_corners_approx"] = home_stats.get("corners_per_game_approx")
        stats["away_corners_approx"] = away_stats.get("corners_per_game_approx")
    elif market_key.startswith("shots"):
        stats["home_xg_avg"] = home_stats.get("xg_for_avg")
        stats["away_xg_avg"] = away_stats.get("xg_for_avg")
        stats["home_shots_avg"] = home_stats.get("shots_avg")
        stats["away_shots_avg"] = away_stats.get("shots_avg")
    elif market_key.startswith("fouls") or market_key.startswith("cards"):
        stats["home_fouls_avg"] = home_stats.get("fouls_per_game_avg")
        stats["away_fouls_avg"] = away_stats.get("fouls_per_game_avg")
        stats["home_cards_avg"] = home_stats.get("cards_per_game_avg")
        stats["away_cards_avg"] = away_stats.get("cards_per_game_avg")
    elif market_key.startswith("asian"):
        stats["home_xg_avg"] = xg_data.get("home_xg")
        stats["away_xg_avg"] = xg_data.get("away_xg")
        stats["home_goals_avg"] = home_stats.get("goals_scored_avg")
        stats["away_goals_avg"] = away_stats.get("goals_scored_avg")
    elif market_key == "correct_score":
        stats["home_xg"] = xg_data.get("home_xg")
        stats["away_xg"] = xg_data.get("away_xg")

    return {k: v for k, v in stats.items() if v is not None}


if __name__ == "__main__":
    # Smoke test
    dummy_fixture = {
        "fixture_id": 1,
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "league_code": "PL",
        "home_stats": {
            "btts_rate": 0.65,
            "goals_scored_avg": 1.8,
            "goals_conceded_avg": 1.1,
            "xg_for_avg": 1.7,
            "corners_per_game_approx": 5.5,
        },
        "away_stats": {
            "btts_rate": 0.60,
            "goals_scored_avg": 1.5,
            "goals_conceded_avg": 1.2,
            "xg_for_avg": 1.5,
            "corners_per_game_approx": 5.2,
        },
        "h2h_stats": {"btts_rate": 0.6, "avg_total_goals": 2.8},
        "odds": {},
        "xg_data": {"home_xg": 1.7, "away_xg": 1.3},
    }
    available = {"fd": True, "understat": True, "fbref": False, "odds": False}
    results = evaluate_fixture_selections(dummy_fixture, [], available)
    assert isinstance(results, list)
    print(f"selection.py self-test passed. Found {len(results)} selections.")
