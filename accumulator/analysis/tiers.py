"""
Tier building logic.

Builds three tiered accumulators from scored selections:

  Low    – highest confidence, 5-6 picks, ~5/1 combined
  Medium – Low picks + more, 6-8 picks, ~10/1-20/1
  High   – Medium picks + more, 8-10 picks, ~50/1+

Rules:
  - Minimum confidence: Low ≥ 7, Medium ≥ 6, High ≥ 5
  - No duplicate market for same fixture within a tier
  - At least 3 different fixtures per tier
  - Value-flagged selections excluded from Low/Medium; allowed in High with warning
  - High tier only: Correct Score market
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
        "name": "Low",
        "subtitle": "Safe Accumulator",
        "min_confidence": 7,
        "target_picks_min": 5,
        "target_picks_max": 6,
        "target_odds_min": 5.0,   # combined decimal
        "target_odds_max": 7.0,
        "allow_value_flag": False,
        "allow_high_tier_only": False,
    },
    "medium": {
        "name": "Medium",
        "subtitle": "Value Accumulator",
        "min_confidence": 6,
        "target_picks_min": 6,
        "target_picks_max": 8,
        "target_odds_min": 11.0,
        "target_odds_max": 21.0,
        "allow_value_flag": False,
        "allow_high_tier_only": False,
    },
    "high": {
        "name": "High",
        "subtitle": "Longshot Accumulator",
        "min_confidence": 5,
        "target_picks_min": 8,
        "target_picks_max": 10,
        "target_odds_min": 51.0,
        "target_odds_max": 500.0,
        "allow_value_flag": True,
        "allow_high_tier_only": True,
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

def _sort_candidates(candidates: List[Dict], prefer_high_conf: bool = True) -> List[Dict]:
    """
    Sort candidates for greedy selection.
    Primary: confidence (desc)
    Secondary: estimated decimal odds (desc) – adds more to combined odds
    """
    return sorted(
        candidates,
        key=lambda s: (
            s.get("confidence", 0),
            s.get("decimal_odds") or DEFAULT_ODDS,
        ),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Build a single tier
# ---------------------------------------------------------------------------

def build_tier(
    tier_key: str,
    base_selections: List[Dict],
    extra_candidates: List[Dict],
) -> Dict:
    """
    Build a tier starting from base_selections (from the tier below) and
    adding from extra_candidates greedily.

    Returns a tier dict with picks, combined odds, and notes.
    """
    config = TIER_CONFIGS[tier_key]
    min_conf = config["min_confidence"]
    max_picks = config["target_picks_max"]
    allow_value = config["allow_value_flag"]
    allow_high_only = config["allow_high_tier_only"]

    picks = list(base_selections)  # Start from inherited base
    notes = []
    value_flagged_picks = []

    # Filter extra candidates
    eligible = [
        c for c in extra_candidates
        if (
            c.get("confidence", 0) >= min_conf
            and (allow_value or not c.get("value_flag", False))
            and (allow_high_only or not c.get("high_tier_only", False))
        )
    ]

    sorted_eligible = _sort_candidates(eligible)

    for candidate in sorted_eligible:
        if len(picks) >= max_picks:
            break
        if _has_duplicate_market(picks, candidate):
            continue
        picks.append(candidate)

    # If High tier and still not at 50/1, try adding value-flagged picks with warning
    if tier_key == "high":
        current_odds = _combined_odds(picks)
        if current_odds < config["target_odds_min"]:
            value_candidates = [
                c for c in extra_candidates
                if c.get("value_flag", False) and c.get("confidence", 0) >= min_conf
                and not _has_duplicate_market(picks, c)
                and c not in picks
            ]
            for candidate in _sort_candidates(value_candidates, prefer_high_conf=False):
                if len(picks) >= max_picks:
                    break
                if _has_duplicate_market(picks, candidate):
                    continue
                picks.append(candidate)
                value_flagged_picks.append(candidate.get("market_label", ""))

            final_odds = _combined_odds(picks)
            if final_odds < config["target_odds_min"]:
                notes.append(
                    f"Note: Could not reach target odds of {config['target_odds_min']:.0f}/1 "
                    f"without dropping below minimum confidence threshold of {min_conf}. "
                    f"Best achievable odds: {final_odds:.1f} (decimal)."
                )

    if value_flagged_picks:
        notes.append(
            f"Warning: The following selections carry a 'Thin Value' flag – "
            f"bookmaker odds may not reflect true probability: {', '.join(value_flagged_picks)}."
        )

    # Fixture diversity check
    fixture_count = _fixture_count(picks)
    if fixture_count < 3:
        notes.append(
            f"Note: Only {fixture_count} different fixture(s) covered – "
            f"ideally 3+ fixtures for diversification."
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
# Build all three tiers
# ---------------------------------------------------------------------------

def build_all_tiers(all_selections: List[Dict]) -> Dict[str, Dict]:
    """
    Entry point: given all scored selections across all fixtures,
    build Low, Medium, and High tiers.

    Returns dict with keys 'low', 'medium', 'high'.
    """
    # Separate out high-tier-only selections
    standard = [s for s in all_selections if not s.get("high_tier_only", False)]
    high_only = [s for s in all_selections if s.get("high_tier_only", False)]

    # --- Low tier ---
    low_candidates = [s for s in standard if s.get("confidence", 0) >= 7]
    low_tier = build_tier("low", [], low_candidates)

    # --- Medium tier: inherit Low picks, add medium-confidence ---
    medium_candidates = [
        s for s in standard
        if s.get("confidence", 0) >= 6
        and s not in low_tier["picks"]
    ]
    medium_tier = build_tier("medium", list(low_tier["picks"]), medium_candidates)

    # --- High tier: inherit Medium picks, add all eligible ---
    high_candidates = [
        s for s in all_selections
        if s.get("confidence", 0) >= 5
        and s not in medium_tier["picks"]
    ]
    high_tier = build_tier("high", list(medium_tier["picks"]), high_candidates)

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
