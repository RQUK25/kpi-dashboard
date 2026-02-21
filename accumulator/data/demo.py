"""
Demo data for the Accumulator Predictor.

Returns a fully realistic matchday payload so the UI can be demonstrated
without any API keys or live internet access.

Activated via:  GET /matchday?demo=true
or:             GET /demo
"""

from datetime import date
from data.parser import decimal_to_fractional

DEMO_DATE = "2025-03-15"


def get_demo_payload() -> dict:
    picks_low = [
        _pick(
            fid=1001, home="Arsenal", away="Chelsea", league="PL",
            mkey="btts_yes", mlabel="Both Teams to Score - Yes",
            selection="Both Teams to Score - Yes",
            conf=8, decimal_odds=1.72,
            h2h_conflict=False, value_flag=False, matchup_boost=True,
            key_stats={
                "home_btts_rate": "0.71",
                "away_btts_rate": "0.65",
                "home_goals_avg": "2.1",
                "away_goals_avg": "1.8",
            },
            explanation="Arsenal BTTS rate of 71% (home) and Chelsea 65% (away) both comfortably exceed the 50% threshold.",
        ),
        _pick(
            fid=1002, home="Liverpool", away="Man City", league="PL",
            mkey="corners_over_95", mlabel="Total Corners Over 9.5",
            selection="Total Corners Over 9.5",
            conf=8, decimal_odds=1.85,
            h2h_conflict=False, value_flag=False, matchup_boost=False,
            key_stats={
                "home_corners_approx": "6.2",
                "away_corners_approx": "5.9",
                "combined_approx": "12.1",
            },
            explanation="Combined corner approximation of 12.1 per game exceeds 9.5 threshold by 27%.",
        ),
        _pick(
            fid=1003, home="Atletico Madrid", away="Real Madrid", league="PD",
            mkey="cards_over_35", mlabel="Total Cards Over 3.5",
            selection="Total Cards Over 3.5",
            conf=8, decimal_odds=1.91,
            h2h_conflict=False, value_flag=False, matchup_boost=True,
            key_stats={
                "home_cards_avg": "2.3",
                "away_cards_avg": "2.1",
                "combined_avg": "4.4",
            },
            explanation="Combined cards average of 4.4 per game exceeds the 3.5 threshold by 26%. Matchup analysis flagged a high-risk dribbler/fouler pairing.",
        ),
        _pick(
            fid=1004, home="Bayern Munich", away="Dortmund", league="BL1",
            mkey="btts_yes", mlabel="Both Teams to Score - Yes",
            selection="Both Teams to Score - Yes",
            conf=7, decimal_odds=1.66,
            h2h_conflict=False, value_flag=False, matchup_boost=False,
            key_stats={
                "home_btts_rate": "0.68",
                "away_btts_rate": "0.72",
                "home_goals_avg": "2.4",
                "away_goals_avg": "2.0",
            },
            explanation="Both teams average over 2 goals per game at their respective venues. BTTS rate average 70%.",
        ),
        _pick(
            fid=1005, home="Inter Milan", away="AC Milan", league="SA",
            mkey="fouls_over", mlabel="Total Fouls Over",
            selection="Total Fouls Over 20.5",
            conf=7, decimal_odds=1.95,
            h2h_conflict=True, value_flag=False, matchup_boost=True,
            key_stats={
                "home_fouls_avg": "11.8",
                "away_fouls_avg": "12.1",
                "combined_avg": "23.9",
            },
            explanation="Combined fouls average of 23.9 per game exceeds 20.5 threshold. Note: H2H average is 18.2, diverging >20% — confidence reduced by 1.",
        ),
    ]

    picks_medium_extra = [
        _pick(
            fid=1001, home="Arsenal", away="Chelsea", league="PL",
            mkey="corners_over_105", mlabel="Total Corners Over 10.5",
            selection="Total Corners Over 10.5",
            conf=6, decimal_odds=2.10,
            h2h_conflict=False, value_flag=False, matchup_boost=False,
            key_stats={
                "home_corners_approx": "5.8",
                "away_corners_approx": "5.5",
                "combined_approx": "11.3",
            },
            explanation="Combined corner approximation of 11.3 per game exceeds 10.5 threshold by 7.6%.",
        ),
        _pick(
            fid=1006, home="PSG", away="Marseille", league="FL1",
            mkey="cards_over_25", mlabel="Total Cards Over 2.5",
            selection="Total Cards Over 2.5",
            conf=7, decimal_odds=1.70,
            h2h_conflict=False, value_flag=False, matchup_boost=True,
            key_stats={
                "home_cards_avg": "1.9",
                "away_cards_avg": "1.8",
                "combined_avg": "3.7",
            },
            explanation="Le Classique historically volatile. Combined card average 3.7 comfortably exceeds 2.5. Matchup boost applied.",
        ),
        _pick(
            fid=1002, home="Liverpool", away="Man City", league="PL",
            mkey="asian_handicap_home", mlabel="Asian Handicap - Home",
            selection="Liverpool -0.5 Asian Handicap",
            conf=6, decimal_odds=2.05,
            h2h_conflict=False, value_flag=False, matchup_boost=False,
            key_stats={
                "home_xg_avg": "2.31",
                "away_xg_avg": "1.89",
                "xg_advantage": "0.42",
            },
            explanation="Liverpool's home xG advantage of +0.42 over the City average supports a slight edge at Anfield.",
        ),
    ]

    picks_high_extra = [
        _pick(
            fid=1003, home="Atletico Madrid", away="Real Madrid", league="PD",
            mkey="player_card_koke", mlabel="Player Card – Koke",
            selection="Koke to receive a card",
            conf=6, decimal_odds=2.50,
            h2h_conflict=False, value_flag=False, matchup_boost=True,
            key_stats={
                "yellow_cards_per90": "0.51",
                "league_avg_yc_per90": "0.29",
            },
            explanation="Koke commits 0.51 yellow-card-eligible fouls per 90, 76% above league average. Matchup analysis highlights a direct clash with a top-25% dribbler.",
        ),
        _pick(
            fid=1004, home="Bayern Munich", away="Dortmund", league="BL1",
            mkey="shots_on_target_over", mlabel="Total Shots on Target Over",
            selection="Total Shots on Target Over 7.5",
            conf=6, decimal_odds=1.88,
            h2h_conflict=False, value_flag=False, matchup_boost=False,
            key_stats={
                "home_shots_on_target_avg": "5.2",
                "away_shots_on_target_avg": "4.1",
                "combined_avg": "9.3",
            },
            explanation="Combined shots on target average of 9.3 exceeds 7.5 threshold by 24%.",
        ),
        _pick(
            fid=1006, home="PSG", away="Marseille", league="FL1",
            mkey="correct_score", mlabel="Correct Score",
            selection="2-1",
            conf=5, decimal_odds=7.50,
            h2h_conflict=False, value_flag=False, matchup_boost=False,
            high_tier_only=True,
            key_stats={
                "home_xg": "2.15",
                "away_xg": "1.22",
                "predicted_score": "2-1",
            },
            explanation="Poisson model (home xG 2.15, away xG 1.22) produces peak probability at 2-1 (approx 12.4%).",
        ),
    ]

    picks_medium = picks_low + picks_medium_extra
    picks_high = picks_medium + picks_high_extra

    def combined(picks):
        r = 1.0
        for p in picks:
            r *= p.get("decimal_odds") or 1.9
        return round(r, 2)

    matchups = [
        {
            "fixture": "Atletico Madrid vs Real Madrid",
            "player1": "Vinícius Júnior",
            "stat1_name": "dribbles_per90",
            "stat1_val": 3.82,
            "player2": "Koke",
            "stat2_name": "fouls_committed_per90",
            "stat2_val": 2.41,
            "market_supported": "Total Match Cards Over",
            "explanation": "Vinícius completes 3.82 dribbles per 90 (top 25% in La Liga), facing Koke who commits 2.41 fouls per 90 (top 25% in La Liga) — a high-risk matchup that raises the probability of cards being shown.",
            "matchup_score": 2.14,
        },
        {
            "fixture": "Inter Milan vs AC Milan",
            "player1": "Lautaro Martínez",
            "stat1_name": "fouls_drawn_per90",
            "stat1_val": 2.88,
            "player2": "AC Milan (team press)",
            "stat2_name": "tackles_per90_avg",
            "stat2_val": 3.21,
            "market_supported": "Total Fouls Over",
            "explanation": "Lautaro draws 2.88 fouls per 90 (top 25% in Serie A) and faces an AC Milan high press averaging 3.21 tackles per 90 (top 25% in league) — this combination suggests a high-foul match.",
            "matchup_score": 1.79,
        },
        {
            "fixture": "PSG vs Marseille",
            "player1": "PSG",
            "stat1_name": "corners_won_avg_approx",
            "stat1_val": 7.3,
            "player2": "Marseille",
            "stat2_name": "goals_conceded_avg",
            "stat2_val": 1.4,
            "market_supported": "Total Corners Over / BTTS",
            "explanation": "PSG averages approximately 7.3 corners per game and faces a Marseille defence that concedes 1.4 goals per game with a 21% clean sheet rate — suggesting set piece danger and elevated corner count.",
            "matchup_score": 1.46,
        },
    ]

    excluded = [
        {
            "fixture": "Arsenal vs Chelsea",
            "market": "Asian Handicap - Away",
            "selection": "Chelsea -0.5 Asian Handicap",
            "confidence": 6,
            "bookmaker_odds": 2.85,
            "implied_probability": 35.1,
            "reason": "Thin Value: bookmaker implied probability exceeds statistical estimate by >10pp",
        },
        {
            "fixture": "Bayern Munich vs Dortmund",
            "market": "Total Cards Over 4.5",
            "selection": "Total Cards Over 4.5",
            "confidence": 5,
            "bookmaker_odds": 3.10,
            "implied_probability": 32.3,
            "reason": "Thin Value: bookmaker implied probability exceeds statistical estimate by >10pp",
        },
    ]

    combined_low = combined(picks_low)
    combined_med = combined(picks_medium)
    combined_high = combined(picks_high)

    return {
        "matchday_date": DEMO_DATE,
        "generated_at": f"{DEMO_DATE}T10:00:00Z",
        "demo_mode": True,
        "leagues_covered": ["PL", "PD", "BL1", "SA", "FL1"],
        "source_statuses": {
            league: {
                "football-data": "ok",
                "odds-api": "ok",
                "understat": "ok",
                "fbref": "ok",
            }
            for league in ["PL", "PD", "BL1", "SA", "FL1"]
        },
        "header_sources": [
            {"source": "football-data", "status": "ok", "reason": ""},
            {"source": "odds-api",      "status": "ok", "reason": ""},
            {"source": "understat",     "status": "ok", "reason": ""},
            {"source": "fbref",         "status": "ok", "reason": ""},
        ],
        "tiers": {
            "low": {
                "tier": "low",
                "name": "Low",
                "subtitle": "Safe Accumulator",
                "target_odds_range": "5/1 – 7/1",
                "estimated_combined_decimal": combined_low,
                "estimated_combined_fractional": decimal_to_fractional(combined_low),
                "pick_count": len(picks_low),
                "fixture_count": len({p["fixture_id"] for p in picks_low}),
                "notes": [],
                "picks": picks_low,
            },
            "medium": {
                "tier": "medium",
                "name": "Medium",
                "subtitle": "Value Accumulator",
                "target_odds_range": "11/1 – 21/1",
                "estimated_combined_decimal": combined_med,
                "estimated_combined_fractional": decimal_to_fractional(combined_med),
                "pick_count": len(picks_medium),
                "fixture_count": len({p["fixture_id"] for p in picks_medium}),
                "notes": [],
                "picks": picks_medium,
            },
            "high": {
                "tier": "high",
                "name": "High",
                "subtitle": "Longshot Accumulator",
                "target_odds_range": "51/1 – 500/1",
                "estimated_combined_decimal": combined_high,
                "estimated_combined_fractional": decimal_to_fractional(combined_high),
                "pick_count": len(picks_high),
                "fixture_count": len({p["fixture_id"] for p in picks_high}),
                "notes": [
                    "Warning: Correct Score selection carries a 'Thin Value' flag — verify odds before including."
                ],
                "picks": picks_high,
            },
        },
        "matchups": matchups,
        "excluded_selections": excluded,
        "total_fixtures_analysed": 6,
        "total_selections_evaluated": 24,
    }


def _pick(
    fid, home, away, league,
    mkey, mlabel, selection,
    conf, decimal_odds,
    h2h_conflict=False, value_flag=False, matchup_boost=False,
    high_tier_only=False,
    key_stats=None,
    explanation="",
) -> dict:
    return {
        "fixture_id": fid,
        "home_team": home,
        "away_team": away,
        "league_code": league,
        "market_key": mkey,
        "market_label": mlabel,
        "selection": selection,
        "confidence": conf,
        "confidence_pct": conf * 10.0,
        "h2h_conflict": h2h_conflict,
        "value_flag": value_flag,
        "matchup_boost": matchup_boost,
        "high_tier_only": high_tier_only,
        "decimal_odds": decimal_odds,
        "fractional_odds": decimal_to_fractional(decimal_odds),
        "bookmaker_odds": decimal_odds,
        "implied_probability": round(100 / decimal_odds, 1) if decimal_odds else None,
        "season_avg_explanation": explanation,
        "key_stats": key_stats or {},
    }
