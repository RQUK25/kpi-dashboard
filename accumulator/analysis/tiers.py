"""
Tier building logic.

Builds three independently constructed accumulators from scored selections:

  Low    – highest confidence, 4-6 picks, ~4/1-8/1 combined
  Medium – mid confidence + higher odds, 5-8 picks, ~10/1-25/1
  High   – wider net + speculative, 6-10 picks, ~30/1+

Rules:
  - ONE selection per fixture per tier (no duplicate fixtures)
  - No duplicate market for same fixture within a tier
  - At least 3 different fixtures per tier
  - Value-flagged selections excluded from Low/Medium; allowed in High with warning
  - High tier only: Correct Score market
  - Each tier is built independently for genuine variety
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from data.parser import decimal_to_fractional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

TIER_CONFIGS = {
    "low": {
        "name": "Low Risk",
        "subtitle": "Safe Accumulator",
        "min_confidence": 7,
        "target_picks_min": 4,
        "target_picks_max": 6,
        "target_odds_min": 4.0,
        "target_odds_max": 8.0,
        "allow_value_flag": False,
        "allow_high_tier_only": False,
        "prefer_low_odds": True,
    },
    "medium": {
        "name": "Medium Risk",
        "subtitle": "Value Accumulator",
        "min_confidence": 6,
        "target_picks_min": 5,
        "target_picks_max": 8,
        "target_odds_min": 10.0,
        "target_odds_max": 25.0,
        "allow_value_flag": False,
        "allow_high_tier_only": False,
        "prefer_low_odds": False,
    },
    "high": {
        "name": "High Risk",
        "subtitle": "Longshot Accumulator",
        "min_confidence": 5,
        "target_picks_min": 6,
        "target_picks_max": 10,
        "target_odds_min": 30.0,
        "target_odds_max": 500.0,
        "allow_value_flag": True,
        "allow_high_tier_only": True,
        "prefer_low_odds": False,
    },
}

DEFAULT_ODDS = 1.9  # Used when bookmaker odds not available


def _combined_odds(selections: List[Dict]) -> float:
    result = 1.0
    for s in selections:
        odds = s.get("decimal_odds") or DEFAULT_ODDS
        result *= odds
    return round(result, 2)


def _fixture_count(selections: List[Dict]) -> int:
    return len({s["fixture_id"] for s in selections})


def _fixture_ids(selections: List[Dict]) -> set:
    return {s["fixture_id"] for s in selections}


def _has_fixture(selections: List[Dict], candidate: Dict) -> bool:
    """Return True if the candidate's fixture is already in the selections."""
    fid = candidate["fixture_id"]
    return any(s["fixture_id"] == fid for s in selections)


def _has_duplicate_market(selections: List[Dict], candidate: Dict) -> bool:
    """Return True if the candidate would duplicate a market for the same fixture."""
    fid = candidate["fixture_id"]
    mkey = candidate["market_key"]
    for s in selections:
        if s["fixture_id"] == fid and s["market_key"] == mkey:
            return True
    return False


# ---------------------------------------------------------------------------
# Sort candidates for greedy selection
# ---------------------------------------------------------------------------

def _sort_candidates(candidates: List[Dict], prefer_low_odds: bool = True) -> List[Dict]:
    """
    Sort candidates for greedy selection.
    - prefer_low_odds=True (Low tier): confidence desc, then lower odds first (safer)
    - prefer_low_odds=False (Medium/High): confidence desc, then higher odds first (more value)
    """
    if prefer_low_odds:
        return sorted(
            candidates,
            key=lambda s: (
                s.get("confidence", 0),
                -(s.get("decimal_odds") or DEFAULT_ODDS),
            ),
            reverse=True,
        )
    return sorted(
        candidates,
        key=lambda s: (
            s.get("confidence", 0),
            s.get("decimal_odds") or DEFAULT_ODDS,
        ),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Build a single tier (independently)
# ---------------------------------------------------------------------------

def build_tier(
    tier_key: str,
    candidates: List[Dict],
) -> Dict:
    """
    Build a tier by greedily picking from candidates.
    Enforces ONE selection per fixture for diversity.

    Returns a tier dict with picks, combined odds, and notes.
    """
    config = TIER_CONFIGS[tier_key]
    min_conf = config["min_confidence"]
    max_picks = config["target_picks_max"]
    allow_value = config["allow_value_flag"]
    allow_high_only = config["allow_high_tier_only"]
    prefer_low = config.get("prefer_low_odds", True)

    notes = []
    value_flagged_picks = []

    # Filter eligible candidates
    eligible = [
        c for c in candidates
        if (
            c.get("confidence", 0) >= min_conf
            and (allow_value or not c.get("value_flag", False))
            and (allow_high_only or not c.get("high_tier_only", False))
        )
    ]

    sorted_eligible = _sort_candidates(eligible, prefer_low_odds=prefer_low)

    # Greedy pick: one selection per fixture
    picks: List[Dict] = []
    for candidate in sorted_eligible:
        if len(picks) >= max_picks:
            break
        if _has_fixture(picks, candidate):
            continue
        picks.append(candidate)

    # If High tier and still below target, try adding value-flagged picks
    if tier_key == "high":
        current_odds = _combined_odds(picks)
        if current_odds < config["target_odds_min"]:
            value_candidates = [
                c for c in candidates
                if c.get("value_flag", False) and c.get("confidence", 0) >= min_conf
                and not _has_fixture(picks, c)
            ]
            for candidate in _sort_candidates(value_candidates, prefer_low_odds=False):
                if len(picks) >= max_picks:
                    break
                if _has_fixture(picks, candidate):
                    continue
                picks.append(candidate)
                value_flagged_picks.append(candidate.get("market_label", ""))

            final_odds = _combined_odds(picks)
            if final_odds < config["target_odds_min"]:
                notes.append(
                    f"Could not reach target odds of {config['target_odds_min']:.0f}/1 "
                    f"without dropping below minimum confidence of {min_conf}. "
                    f"Best achievable: {final_odds:.1f} (decimal)."
                )

    if value_flagged_picks:
        notes.append(
            f"Thin Value flag on: {', '.join(value_flagged_picks)}. "
            f"Bookmaker odds may not reflect true probability."
        )

    # Fixture diversity check
    fixture_count = _fixture_count(picks)
    if fixture_count < 3 and picks:
        notes.append(
            f"Only {fixture_count} fixture(s) covered — "
            f"ideally 3+ for diversification."
        )

    combined = _combined_odds(picks)
    return {
        "tier": tier_key,
        "name": config["name"],
        "subtitle": config["subtitle"],
        "target_odds_range": f"{config['target_odds_min']:.0f}/1 – {config['target_odds_max']:.0f}/1",
        "estimated_combined_decimal": combined,
        "estimated_combined_fractional": decimal_to_fractional(combined),
        "pick_count": len(picks),
        "fixture_count": fixture_count,
        "picks": picks,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Build all three tiers (independently for genuine variety)
# ---------------------------------------------------------------------------

def build_all_tiers(all_selections: List[Dict]) -> Dict[str, Dict]:
    """
    Entry point: given all scored selections across all fixtures,
    build Low, Medium, and High tiers independently.

    Each tier picks the best selection per fixture according to its own
    criteria, so Medium/High are NOT just Low + extras.
    """
    standard = [s for s in all_selections if not s.get("high_tier_only", False)]

    # --- Low tier: top confidence, safest odds ---
    low_candidates = [s for s in standard if s.get("confidence", 0) >= 7]
    low_tier = build_tier("low", low_candidates)

    # --- Medium tier: slightly broader, prefer higher-odds picks ---
    # For each fixture, prefer a DIFFERENT market than Low picked (variety)
    low_picks_set = {(s["fixture_id"], s["market_key"]) for s in low_tier["picks"]}
    medium_candidates = sorted(
        [s for s in standard if s.get("confidence", 0) >= 6],
        key=lambda s: (
            0 if (s["fixture_id"], s["market_key"]) in low_picks_set else 1,
            -s.get("confidence", 0),
        ),
        reverse=True,
    )
    medium_tier = build_tier("medium", medium_candidates)

    # --- High tier: widest net, include high-tier-only markets ---
    medium_picks_set = {(s["fixture_id"], s["market_key"]) for s in medium_tier["picks"]}
    high_candidates = sorted(
        [s for s in all_selections if s.get("confidence", 0) >= 5],
        key=lambda s: (
            0 if (s["fixture_id"], s["market_key"]) in medium_picks_set else 1,
            -s.get("confidence", 0),
        ),
        reverse=True,
    )
    high_tier = build_tier("high", high_candidates)

    return {
        "low": low_tier,
        "medium": medium_tier,
        "high": high_tier,
    }


# ---------------------------------------------------------------------------
# Excluded selections builder
# ---------------------------------------------------------------------------

def build_excluded_list(all_selections: List[Dict], tiers: Dict[str, Dict]) -> List[Dict]:
    """
    Return selections that were excluded from all tiers due to value flag,
    with their reason.
    """
    all_tier_picks = set()
    for tier in tiers.values():
        for pick in tier.get("picks", []):
            all_tier_picks.add((pick.get("fixture_id"), pick.get("market_key")))

    excluded = []
    for s in all_selections:
        key = (s.get("fixture_id"), s.get("market_key"))
        if key not in all_tier_picks and s.get("value_flag", False):
            excluded.append({
                "fixture": f"{s.get('home_team')} vs {s.get('away_team')}",
                "market": s.get("market_label"),
                "selection": s.get("selection"),
                "confidence": s.get("confidence"),
                "bookmaker_odds": s.get("decimal_odds"),
                "implied_probability": s.get("implied_probability"),
                "reason": "Thin Value: bookmaker implied probability exceeds statistical estimate by >10pp",
            })
    return excluded


if __name__ == "__main__":
    # Smoke test
    dummy_selections = [
        {
            "fixture_id": 1, "home_team": "Arsenal", "away_team": "Chelsea",
            "league_code": "PL", "market_key": "btts_yes",
            "market_label": "BTTS Yes", "selection": "Both Teams to Score - Yes",
            "confidence": 8, "confidence_pct": 75, "decimal_odds": 1.8,
            "fractional_odds": "4/5", "value_flag": False, "h2h_conflict": False,
            "matchup_boost": False, "high_tier_only": False, "key_stats": {},
        },
        {
            "fixture_id": 2, "home_team": "Man Utd", "away_team": "Liverpool",
            "league_code": "PL", "market_key": "corners_over_95",
            "market_label": "Corners Over 9.5", "selection": "Corners Over 9.5",
            "confidence": 7, "confidence_pct": 65, "decimal_odds": 1.9,
            "fractional_odds": "9/10", "value_flag": False, "h2h_conflict": False,
            "matchup_boost": True, "high_tier_only": False, "key_stats": {},
        },
        {
            "fixture_id": 3, "home_team": "Spurs", "away_team": "City",
            "league_code": "PL", "market_key": "cards_over_35",
            "market_label": "Cards Over 3.5", "selection": "Total Cards Over 3.5",
            "confidence": 6, "confidence_pct": 55, "decimal_odds": 2.1,
            "fractional_odds": "11/10", "value_flag": False, "h2h_conflict": True,
            "matchup_boost": False, "high_tier_only": False, "key_stats": {},
        },
    ]
    tiers = build_all_tiers(dummy_selections)
    assert "low" in tiers and "medium" in tiers and "high" in tiers
    print(f"tiers.py self-test passed. Low: {tiers['low']['pick_count']} picks, "
          f"Medium: {tiers['medium']['pick_count']}, High: {tiers['high']['pick_count']}")
