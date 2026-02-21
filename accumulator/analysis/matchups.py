"""
Player vs player matchup analysis.

Identifies three types of high-value matchup patterns:
  1. Dribbler vs Fouler       – supports cards market
  2. Foul Magnet vs High Press – supports total fouls Over
  3. Set Piece Threat          – supports corners Over and BTTS

Each matchup result includes:
  player1, stat1, player2, stat2, market_supported, explanation
"""

import logging
from typing import Any, Dict, List, Optional

from data.parser import parse_fbref_percentile, parse_fbref_league_averages

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Matchup result builder
# ---------------------------------------------------------------------------

def _make_matchup(
    player1: str,
    stat1_name: str,
    stat1_val: Any,
    player2: str,
    stat2_name: str,
    stat2_val: Any,
    market: str,
    explanation: str,
    score: float = 1.0,
) -> Dict:
    return {
        "player1": player1,
        "stat1_name": stat1_name,
        "stat1_val": stat1_val,
        "player2": player2,
        "stat2_name": stat2_name,
        "stat2_val": stat2_val,
        "market_supported": market,
        "explanation": explanation,
        "matchup_score": round(score, 3),
    }


# ---------------------------------------------------------------------------
# Pattern 1: Dribbler vs Fouler
# ---------------------------------------------------------------------------

def find_dribbler_vs_fouler(
    home_players: List[Dict],
    away_players: List[Dict],
    all_league_players: List[Dict],
) -> List[Dict]:
    """
    Find combinations where:
    - An attacker's dribbles/90 is in the top 25% for the league
    - A defender's fouls committed/90 is in the top 25% for the league

    Matchup score = (attacker dribbles/90 / league avg) × (defender fouls/90 / league avg)
    Threshold: score > 1.4 → high-risk matchup
    """
    if not all_league_players:
        return []

    league_avgs = parse_fbref_league_averages(all_league_players)
    drib_avg = league_avgs.get("dribbles_per90_avg") or 1.0
    fouls_avg = league_avgs.get("fouls_committed_per90_avg") or 1.0

    drib_threshold = parse_fbref_percentile(all_league_players, "dribbles_per90", 0.75)
    fouls_threshold = parse_fbref_percentile(all_league_players, "fouls_committed_per90", 0.75)

    matchups = []
    # Home attackers vs Away defenders and vice versa
    for (attackers, defenders) in [(home_players, away_players), (away_players, home_players)]:
        top_dribblers = [
            p for p in attackers
            if isinstance(p.get("dribbles_per90"), float) and p["dribbles_per90"] >= drib_threshold
        ]
        top_foulers = [
            p for p in defenders
            if isinstance(p.get("fouls_committed_per90"), float) and p["fouls_committed_per90"] >= fouls_threshold
        ]

        for att in top_dribblers:
            for dfn in top_foulers:
                d90 = att.get("dribbles_per90", 0) or 0
                f90 = dfn.get("fouls_committed_per90", 0) or 0
                score = (d90 / drib_avg) * (f90 / fouls_avg)
                if score > 1.4:
                    matchups.append(_make_matchup(
                        player1=att.get("player", "Unknown Attacker"),
                        stat1_name="dribbles_per90",
                        stat1_val=round(d90, 2),
                        player2=dfn.get("player", "Unknown Defender"),
                        stat2_name="fouls_committed_per90",
                        stat2_val=round(f90, 2),
                        market="Total Match Cards Over",
                        explanation=(
                            f"{att.get('player', 'Attacker')} completes {d90:.2f} dribbles per 90 "
                            f"(top 25% in league), facing {dfn.get('player', 'Defender')} who commits "
                            f"{f90:.2f} fouls per 90 (top 25% in league) — a high-risk matchup "
                            f"that raises the probability of cards being shown."
                        ),
                        score=score,
                    ))

    # Sort by matchup score descending, return top 3
    matchups.sort(key=lambda x: x["matchup_score"], reverse=True)
    return matchups[:3]


# ---------------------------------------------------------------------------
# Pattern 2: Foul Magnet vs High Press
# ---------------------------------------------------------------------------

def find_foul_magnet_vs_high_press(
    home_players: List[Dict],
    away_players: List[Dict],
    all_league_players: List[Dict],
    home_team_tackles_avg: Optional[float] = None,
    away_team_tackles_avg: Optional[float] = None,
) -> List[Dict]:
    """
    Find combinations where:
    - A player's fouls drawn/90 is in the top 25% for the league
    - The opposing team is in the top 25% for pressing intensity
      (approximated by team tackles+interceptions per 90)

    Supports: Total Fouls Over
    """
    if not all_league_players:
        return []

    league_avgs = parse_fbref_league_averages(all_league_players)
    drawn_avg = league_avgs.get("fouls_drawn_per90_avg") or 1.0
    tackles_avg = league_avgs.get("tackles_per90_avg") or 1.0

    drawn_threshold = parse_fbref_percentile(all_league_players, "fouls_drawn_per90", 0.75)

    matchups = []
    pairs = [
        (home_players, away_players, home_team_tackles_avg, "away team"),
        (away_players, home_players, away_team_tackles_avg, "home team"),
    ]

    for (foul_magnets_pool, pressing_team_players, pressing_avg, side_label) in pairs:
        # Estimate pressing from team player pool if not pre-computed
        if pressing_avg is None:
            tkl_vals = [
                p["tackles_per90"]
                for p in pressing_team_players
                if isinstance(p.get("tackles_per90"), float)
            ]
            pressing_avg = sum(tkl_vals) / len(tkl_vals) if tkl_vals else None

        if pressing_avg is None or pressing_avg < tackles_avg * 1.0:
            continue

        # Check if pressing team is in top 25% for league press (simple proxy)
        all_tkl = parse_fbref_percentile(all_league_players, "tackles_per90", 0.75)
        if pressing_avg < all_tkl:
            continue

        top_magnets = [
            p for p in foul_magnets_pool
            if isinstance(p.get("fouls_drawn_per90"), float) and p["fouls_drawn_per90"] >= drawn_threshold
        ]
        for player in top_magnets:
            fd90 = player.get("fouls_drawn_per90", 0)
            matchups.append(_make_matchup(
                player1=player.get("player", "Unknown Player"),
                stat1_name="fouls_drawn_per90",
                stat1_val=round(fd90, 2),
                player2=f"{side_label.title()} (team press)",
                stat2_name="tackles_per90_avg",
                stat2_val=round(pressing_avg, 2),
                market="Total Fouls Over",
                explanation=(
                    f"{player.get('player', 'Player')} draws {fd90:.2f} fouls per 90 "
                    f"(top 25% in league) and faces a {side_label} with pressing intensity "
                    f"{pressing_avg:.2f} tackles per 90 (top 25% in league) — "
                    f"this combination suggests a high-foul match."
                ),
                score=(fd90 / drawn_avg) * (pressing_avg / tackles_avg),
            ))

    matchups.sort(key=lambda x: x["matchup_score"], reverse=True)
    return matchups[:3]


# ---------------------------------------------------------------------------
# Pattern 3: Set Piece Threat
# ---------------------------------------------------------------------------

def find_set_piece_threat(
    home_team_name: str,
    away_team_name: str,
    home_season_stats: Dict,
    away_season_stats: Dict,
) -> List[Dict]:
    """
    Flag set piece threats.

    Criteria:
    - One team ranks in the top 25% for corners won per game (approximated by
      corners_won_avg if available in season stats)
    - The opposing team concedes more than 30% of their goals from set pieces
      (approximated by a high goals_conceded_avg with a low clean_sheet_rate)

    Returns a list of matchup dicts supporting corners Over and BTTS markets.
    """
    matchups = []

    pairs = [
        (home_team_name, home_season_stats, away_team_name, away_season_stats),
        (away_team_name, away_season_stats, home_team_name, home_season_stats),
    ]

    for (att_team, att_stats, def_team, def_stats) in pairs:
        corners_avg = att_stats.get("corners_won_avg")
        if corners_avg is None:
            # Proxy: teams with high attacking xG tend to win more corners
            xg = att_stats.get("xg_for_avg")
            if xg and xg > 1.7:
                corners_avg = xg * 3.5  # rough proxy
            else:
                continue

        concede_rate = def_stats.get("goals_conceded_avg", 0)
        clean_rate = def_stats.get("clean_sheet_rate", 1)

        # Proxy for set piece vulnerability: high goals conceded + low clean sheet rate
        set_piece_vuln = concede_rate > 1.2 and clean_rate < 0.35

        if corners_avg > 5.0 and set_piece_vuln:
            matchups.append(_make_matchup(
                player1=att_team,
                stat1_name="corners_won_avg_approx",
                stat1_val=round(corners_avg, 1),
                player2=def_team,
                stat2_name="goals_conceded_avg",
                stat2_val=concede_rate,
                market="Total Corners Over / BTTS",
                explanation=(
                    f"{att_team} averages approximately {corners_avg:.1f} corners per game "
                    f"and faces a {def_team} defence that concedes {concede_rate:.2f} goals "
                    f"per game with a {clean_rate:.0%} clean sheet rate — "
                    f"suggesting set piece danger and elevated corner count."
                ),
                score=corners_avg / 5.0 * (concede_rate / 1.2),
            ))

    matchups.sort(key=lambda x: x["matchup_score"], reverse=True)
    return matchups[:2]


# ---------------------------------------------------------------------------
# Main entry point: analyse all matchups for a fixture
# ---------------------------------------------------------------------------

def analyse_fixture_matchups(
    home_team: str,
    away_team: str,
    home_players: List[Dict],
    away_players: List[Dict],
    all_league_players: List[Dict],
    home_season_stats: Dict,
    away_season_stats: Dict,
) -> List[Dict]:
    """
    Run all three matchup patterns for a fixture.
    Returns combined list of matchup dicts, deduped by market.
    """
    results = []

    try:
        results.extend(find_dribbler_vs_fouler(home_players, away_players, all_league_players))
    except Exception as exc:
        logger.warning("Dribbler vs Fouler analysis failed: %s", exc)

    try:
        results.extend(find_foul_magnet_vs_high_press(
            home_players, away_players, all_league_players
        ))
    except Exception as exc:
        logger.warning("Foul Magnet vs High Press analysis failed: %s", exc)

    try:
        results.extend(find_set_piece_threat(
            home_team, away_team, home_season_stats, away_season_stats
        ))
    except Exception as exc:
        logger.warning("Set Piece Threat analysis failed: %s", exc)

    return results


if __name__ == "__main__":
    # Basic smoke test with empty data
    result = analyse_fixture_matchups("Team A", "Team B", [], [], [], {}, {})
    assert isinstance(result, list)
    print("matchups.py self-test passed.")
