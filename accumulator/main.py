"""
FastAPI application entry point.

Routes:
  GET /               → serves frontend/index.html
  GET /matchday       → full analysis response (JSON)
  GET /admin/log      → activity log as plain text

Environment setup:
  On startup, check for .env file. If missing, create .env from template
  and print instructions. Exit gracefully if keys are empty.
"""

import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path and environment bootstrap
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent

# Add project root to sys.path so relative imports work from CLI
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# .env setup
ENV_PATH = BASE_DIR / ".env"
ENV_TEMPLATE_PATH = BASE_DIR / ".env.template"


def bootstrap_env() -> bool:
    """
    Ensure .env exists. If not, create it from template.
    Returns True if keys appear populated, False otherwise.
    """
    if not ENV_PATH.exists():
        if ENV_TEMPLATE_PATH.exists():
            import shutil
            shutil.copy(ENV_TEMPLATE_PATH, ENV_PATH)
            print("\n" + "=" * 60)
            print("  .env file created from template.")
            print("  Please fill in the following keys in .env:")
            print("    FOOTBALL_DATA_KEY  – from football-data.org")
            print("    ODDS_API_KEY       – from the-odds-api.com")
            print("  Then restart the application.")
            print("=" * 60 + "\n")
        else:
            with open(ENV_PATH, "w") as f:
                f.write("FOOTBALL_DATA_KEY=\nODDS_API_KEY=\n")
            print("Created .env with empty keys. Please fill them in.")
        return False
    return True


# Bootstrap .env before importing dotenv
_env_ready = bootstrap_env()

try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except ImportError:
    pass  # Will work without python-dotenv if env vars set directly

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

# ---------------------------------------------------------------------------
# FastAPI imports
# ---------------------------------------------------------------------------

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Internal imports
# ---------------------------------------------------------------------------

from data.fetcher import (
    fetch_fd_matches,
    fetch_fd_h2h,
    fetch_fd_team_season,
    fetch_odds,
    fetch_understat_league,
    fetch_fbref_player_stats,
    fetch_fbref_misc_stats,
    LEAGUE_CODES,
    LEAGUE_TO_UNDERSTAT,
)
from data.parser import (
    parse_fd_matches,
    parse_fd_team_season,
    parse_fd_h2h,
    parse_odds_for_fixture,
    parse_understat_league,
    parse_understat_season_averages,
    parse_fbref_player_stats,
    parse_fbref_league_averages,
    decimal_to_fractional,
)
from analysis.matchups import analyse_fixture_matchups
from analysis.selection import evaluate_fixture_selections, evaluate_player_card_selections
from analysis.tiers import build_all_tiers, build_excluded_list
from data.demo import get_demo_payload

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Accumulator / Build-a-Bet Predictor",
    description="Football statistical accumulator predictor with tiered selections",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Serve static frontend files
FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

ACTIVE_LEAGUES = ["PL", "ELC", "PD", "BL1", "SA", "FL1", "CL", "EL"]


def _check_source_status(league_code: str, matchday_date: date) -> Dict[str, str]:
    """Return source availability indicators for the UI header."""
    from data.cache import read_cache
    statuses = {}

    fd_data = read_cache("fd_matches", league_code, matchday_date)
    statuses["football-data"] = "ok" if fd_data else "unknown"

    odds_data = read_cache("odds", league_code, matchday_date)
    statuses["odds-api"] = "ok" if odds_data else "unknown"

    us_data = read_cache("understat", league_code, matchday_date)
    statuses["understat"] = "ok" if us_data else "unknown"

    fb_data = read_cache("fbref_players", league_code, matchday_date)
    statuses["fbref"] = "ok" if fb_data else "unknown"

    return statuses


def _enrich_fixture(
    fixture: Dict,
    matchday_date: date,
    fd_team_data: Dict,
    understat_league_data: Any,
    fbref_players: Optional[List[Dict]],
    odds_list: Optional[List[Dict]],
    all_league_players: Optional[List[Dict]],
) -> Dict:
    """
    Enrich a fixture dict with team stats, xG, odds, and player data.
    """
    home_id = fixture["home_team_id"]
    away_id = fixture["away_team_id"]
    comp_id = fixture["competition_id"]
    home_team = fixture["home_team"]
    away_team = fixture["away_team"]

    # --- Home team season stats ---
    home_raw = fd_team_data.get(home_id)
    away_raw = fd_team_data.get(away_id)

    home_stats = parse_fd_team_season(home_raw or {}, home_id, "home")
    away_stats = parse_fd_team_season(away_raw or {}, away_id, "away")

    # --- Understat xG ---
    xg_data = {}
    if understat_league_data:
        xg_data = parse_understat_league(understat_league_data, home_team, away_team, matchday_date)
        if not xg_data:
            # Try season averages as fallback
            home_xg = parse_understat_season_averages(understat_league_data, home_team, "home")
            away_xg = parse_understat_season_averages(understat_league_data, away_team, "away")
            if home_xg or away_xg:
                xg_data = {
                    "home_xg": home_xg.get("xg_for_avg"),
                    "away_xg": away_xg.get("xg_for_avg"),
                    "home_shots": home_xg.get("shots_avg"),
                    "away_shots": away_xg.get("shots_avg"),
                }

    # Enrich home/away stats with xG-derived proxies
    if xg_data.get("home_xg"):
        home_stats["xg_for_avg"] = xg_data["home_xg"]
        home_stats["corners_per_game_approx"] = round(xg_data["home_xg"] * 3.8, 1)
        home_stats["shots_on_target_avg"] = round(xg_data["home_xg"] * 3.5, 1)
    if xg_data.get("away_xg"):
        away_stats["xg_for_avg"] = xg_data["away_xg"]
        away_stats["corners_per_game_approx"] = round(xg_data["away_xg"] * 3.8, 1)
        away_stats["shots_on_target_avg"] = round(xg_data["away_xg"] * 3.5, 1)

    # xG advantage for Asian Handicap
    hxg = xg_data.get("home_xg") or home_stats.get("goals_scored_avg", 1.2)
    axg = xg_data.get("away_xg") or away_stats.get("goals_scored_avg", 1.0)
    xg_data["xg_advantage"] = round(hxg - axg, 2)
    xg_data["xg_advantage_away"] = round(axg - hxg, 2)

    # --- FBref player stats ---
    home_players: List[Dict] = []
    away_players: List[Dict] = []
    if fbref_players:
        home_players = parse_fbref_player_stats(fbref_players, home_team)
        away_players = parse_fbref_player_stats(fbref_players, away_team)

        # Enrich team stats with fouls/cards averages
        for team_stats, players in [(home_stats, home_players), (away_stats, away_players)]:
            if players:
                fouls = [p["fouls_committed_per90"] for p in players
                         if isinstance(p.get("fouls_committed_per90"), float)]
                cards = [p["yellow_cards_per90"] for p in players
                         if isinstance(p.get("yellow_cards_per90"), float)]
                if fouls:
                    team_stats["fouls_per_game_avg"] = round(sum(fouls) * 11 / len(fouls), 1)
                if cards:
                    team_stats["cards_per_game_avg"] = round(sum(cards) * 11 / len(cards), 1)

    # --- Odds ---
    odds_dict = {}
    if odds_list:
        odds_dict = parse_odds_for_fixture(odds_list, home_team, away_team)

    fixture["home_stats"] = home_stats
    fixture["away_stats"] = away_stats
    fixture["xg_data"] = xg_data
    fixture["player_stats"] = home_players + away_players
    fixture["odds"] = odds_dict

    # Store players separately for matchup analysis
    fixture["_home_players"] = home_players
    fixture["_away_players"] = away_players

    return fixture


async def _run_analysis(matchday_date: date, league_codes: List[str]) -> Dict:
    """
    Full analysis pipeline for a given matchday.
    Returns the complete JSON payload for the /matchday endpoint.
    """
    logger.info("Starting analysis for %s | Leagues: %s", matchday_date, league_codes)

    all_fixtures: List[Dict] = []
    all_selections: List[Dict] = []
    all_matchups: List[Dict] = []
    source_statuses: Dict[str, Any] = {}
    leagues_covered: List[str] = []

    fd_key = os.getenv("FOOTBALL_DATA_KEY", "")
    odds_key = os.getenv("ODDS_API_KEY", "")
    has_fd = bool(fd_key)
    has_odds = bool(odds_key)

    for league_code in league_codes:
        logger.info("Processing league: %s", league_code)

        # --- Fetch data ---
        fd_raw = fetch_fd_matches(league_code, matchday_date) if has_fd else None
        odds_raw = fetch_odds(league_code, matchday_date) if has_odds else None
        understat_raw = fetch_understat_league(league_code, matchday_date)
        fbref_raw = fetch_fbref_player_stats(league_code, matchday_date)
        fbref_misc_raw = fetch_fbref_misc_stats(league_code, matchday_date)

        available_sources = {
            "fd": fd_raw is not None,
            "understat": understat_raw is not None,
            "fbref": fbref_raw is not None,
            "odds": odds_raw is not None,
        }

        source_statuses[league_code] = {
            "football-data": "ok" if fd_raw else ("failed" if has_fd else "no_key"),
            "odds-api": "ok" if odds_raw else ("failed" if has_odds else "no_key"),
            "understat": "ok" if understat_raw else "failed",
            "fbref": "ok" if fbref_raw else "failed",
        }

        # --- Parse fixtures ---
        if fd_raw:
            fixtures = parse_fd_matches(fd_raw, league_code)
        else:
            fixtures = []

        if not fixtures:
            logger.info("No fixtures found for %s on %s", league_code, matchday_date)
            continue

        leagues_covered.append(league_code)

        # --- Fetch team season data ---
        fd_team_data: Dict[int, Dict] = {}
        if has_fd and fixtures:
            team_ids = set()
            for f in fixtures:
                team_ids.add(f["home_team_id"])
                team_ids.add(f["away_team_id"])
            comp_id = LEAGUE_CODES.get(league_code, 0)
            for tid in team_ids:
                raw = fetch_fd_team_season(tid, comp_id, matchday_date)
                if raw:
                    fd_team_data[tid] = raw

        # --- All league players for percentile calculation ---
        all_league_players = fbref_raw or []

        # --- Process each fixture ---
        for fixture in fixtures:
            fixture_id = fixture["fixture_id"]

            # Fetch H2H
            if has_fd:
                h2h_raw = fetch_fd_h2h(fixture_id, league_code, matchday_date)
                fixture["h2h_stats"] = parse_fd_h2h(h2h_raw) if h2h_raw else {}
            else:
                fixture["h2h_stats"] = {}

            # Enrich with all data sources
            fixture = _enrich_fixture(
                fixture, matchday_date,
                fd_team_data, understat_raw,
                fbref_raw, odds_raw,
                all_league_players,
            )

            # --- Matchup analysis ---
            matchups = analyse_fixture_matchups(
                fixture["home_team"],
                fixture["away_team"],
                fixture.get("_home_players", []),
                fixture.get("_away_players", []),
                all_league_players,
                fixture.get("home_stats", {}),
                fixture.get("away_stats", {}),
            )
            fixture["matchups"] = matchups
            for m in matchups:
                m["fixture"] = f"{fixture['home_team']} vs {fixture['away_team']}"
            all_matchups.extend(matchups)

            # --- Selection analysis ---
            selections = evaluate_fixture_selections(fixture, matchups, available_sources)

            # Player card selections (if fbref available)
            if available_sources.get("fbref"):
                player_cards = evaluate_player_card_selections(
                    fixture.get("_home_players", []),
                    fixture.get("_away_players", []),
                    all_league_players,
                    matchups,
                    fixture.get("odds", {}),
                    fixture.get("h2h_stats", {}),
                )
                # Add fixture info to player card selections
                for pc in player_cards:
                    pc["fixture_id"] = fixture_id
                    pc["home_team"] = fixture["home_team"]
                    pc["away_team"] = fixture["away_team"]
                    pc["league_code"] = league_code
                    pc["market_key"] = f"player_card_{pc['player'].lower().replace(' ', '_')}"
                    pc["market_label"] = f"Player Card – {pc['player']}"
                    pc["selection"] = f"{pc['player']} to receive a card"
                    pc["fractional_odds"] = (
                        decimal_to_fractional(pc["bookmaker_odds"])
                        if pc.get("bookmaker_odds") else None
                    )
                    pc["decimal_odds"] = pc.get("bookmaker_odds")
                    pc["high_tier_only"] = False
                selections.extend(player_cards)

            all_selections.extend(selections)
            all_fixtures.append(fixture)

    # --- Build tiers ---
    tiers = build_all_tiers(all_selections)
    excluded = build_excluded_list(all_selections, tiers)

    # --- Serialise (remove internal keys) ---
    for f in all_fixtures:
        f.pop("_home_players", None)
        f.pop("_away_players", None)

    # --- Derive overall source status for header ---
    header_sources = _aggregate_source_status(source_statuses)

    return {
        "matchday_date": matchday_date.isoformat(),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "leagues_covered": leagues_covered,
        "source_statuses": source_statuses,
        "header_sources": header_sources,
        "tiers": {
            "low": _serialise_tier(tiers["low"]),
            "medium": _serialise_tier(tiers["medium"]),
            "high": _serialise_tier(tiers["high"]),
        },
        "matchups": all_matchups,
        "excluded_selections": excluded,
        "total_fixtures_analysed": len(all_fixtures),
        "total_selections_evaluated": len(all_selections),
    }


def _aggregate_source_status(source_statuses: Dict) -> List[Dict]:
    """Flatten per-league source statuses into a UI-friendly list."""
    sources: Dict[str, List[str]] = {}
    for league, statuses in source_statuses.items():
        for source, status in statuses.items():
            sources.setdefault(source, []).append(status)

    result = []
    for source, statuses_list in sources.items():
        if all(s == "ok" for s in statuses_list):
            agg = "ok"
        elif all(s in ("failed", "no_key") for s in statuses_list):
            agg = "failed"
        else:
            agg = "partial"

        reason = ""
        if agg == "failed":
            if "no_key" in statuses_list:
                reason = "API key not configured"
            else:
                reason = "All requests failed – check logs"
        elif agg == "partial":
            failed = [l for l, s in zip(source_statuses.keys(), statuses_list) if s in ("failed", "no_key")]
            reason = f"Partial failure for: {', '.join(failed)}"

        result.append({"source": source, "status": agg, "reason": reason})

    return result


def _serialise_tier(tier: Dict) -> Dict:
    """Remove internal/private fields from tier picks before sending to frontend."""
    out = {k: v for k, v in tier.items() if k != "picks"}
    out["picks"] = []
    for pick in tier.get("picks", []):
        clean = {k: v for k, v in pick.items() if not k.startswith("_")}
        out["picks"].append(clean)
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_index():
    """Serve the frontend SPA."""
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return PlainTextResponse("Frontend not found. Run from project root.", status_code=404)


@app.get("/matchday")
async def get_matchday(
    date_str: Optional[str] = Query(None, alias="date", description="YYYY-MM-DD (default: today)"),
    leagues: Optional[str] = Query(None, description="Comma-separated league codes e.g. PL,PD"),
    demo: Optional[bool] = Query(False, description="Return realistic demo data without making external calls"),
):
    """
    Main analysis endpoint.
    Returns tiered accumulator selections and matchup data as JSON.
    Add ?demo=true to see a fully populated sample response without API keys.
    """
    if demo:
        return JSONResponse(content=get_demo_payload())

    try:
        if date_str:
            matchday_date = date.fromisoformat(date_str)
        else:
            matchday_date = date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    if leagues:
        league_codes = [l.strip().upper() for l in leagues.split(",") if l.strip()]
        invalid = [l for l in league_codes if l not in LEAGUE_CODES]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown league codes: {invalid}. Valid: {list(LEAGUE_CODES.keys())}"
            )
    else:
        league_codes = ACTIVE_LEAGUES

    result = await _run_analysis(matchday_date, league_codes)
    return JSONResponse(content=result)


@app.get("/demo", include_in_schema=False)
async def demo_redirect():
    """Shortcut: serves the frontend pre-loaded with demo data."""
    from fastapi.responses import HTMLResponse
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        return PlainTextResponse("Frontend not found.", status_code=404)
    # Inject a flag so app.js auto-loads demo mode
    html = index.read_text(encoding="utf-8")
    html = html.replace(
        "<script src=\"/static/app.js\"></script>",
        "<script>window.DEMO_MODE = true;</script>\n  <script src=\"/static/app.js\"></script>"
    )
    return HTMLResponse(content=html)


@app.get("/admin/log", response_class=PlainTextResponse)
async def get_activity_log():
    """Return the activity log as plain text."""
    log_path = BASE_DIR / "logs" / "activity.log"
    if not log_path.exists():
        return PlainTextResponse("Log file not found.", status_code=404)
    try:
        content = log_path.read_text(encoding="utf-8")
        return PlainTextResponse(content or "(log is empty)")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
async def health():
    """Simple health check."""
    fd_key = bool(os.getenv("FOOTBALL_DATA_KEY"))
    odds_key = bool(os.getenv("ODDS_API_KEY"))
    return {
        "status": "ok",
        "env_ready": _env_ready,
        "football_data_key_set": fd_key,
        "odds_api_key_set": odds_key,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    if not os.getenv("FOOTBALL_DATA_KEY"):
        print("\nWarning: FOOTBALL_DATA_KEY not set. football-data.org features will be disabled.")
    if not os.getenv("ODDS_API_KEY"):
        print("Warning: ODDS_API_KEY not set. Odds features will be disabled.\n")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
