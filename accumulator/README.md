# Accumulator / Build-a-Bet Predictor

A responsive single-page web application that pulls football matchday data from free sources, analyses it statistically, and presents three tiered accumulators.

---

## Quick Start (Local)

```bash
cd accumulator

# One-command startup (handles deps + .env creation automatically)
./start.sh

# Custom port
./start.sh 3000
```

Then open:
- **Live data** → http://localhost:8000
- **Demo (no keys needed)** → http://localhost:8000/demo
- **API docs** → http://localhost:8000/docs
- **Activity log** → http://localhost:8000/admin/log

### Manual startup

```bash
pip install -r requirements.txt
cp .env.template .env      # then fill in your API keys
uvicorn main:app --reload --port 8000
```

The app degrades gracefully if API keys are missing — it will still run. Visit `/demo` to see the full UI populated with realistic sample data without any API keys.

---

## Deployment to Render.com (free, no domain needed)

Render gives you a free `https://your-app.onrender.com` subdomain.

1. Push this repo to GitHub (it's already there).

2. Go to [render.com](https://render.com) → **New +** → **Web Service**

3. Connect your GitHub repo and select the `accumulator/` directory as the root
   (or set root directory to `accumulator` in the Render settings).

4. Render will auto-detect the `render.yaml` — settings are:
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT --app-dir .`
   - **Python version**: 3.11

5. In the Render dashboard → **Environment** tab, add:
   ```
   FOOTBALL_DATA_KEY = <your key from football-data.org>
   ODDS_API_KEY      = <your key from the-odds-api.com>
   ```

6. Deploy. Your app will be live at `https://accumulator-predictor.onrender.com`
   (name varies — Render assigns it).

**Note on Render free tier**: The instance sleeps after 15 minutes of inactivity and takes ~30 seconds to wake on the next request. The cache directory is ephemeral and resets on each deploy, so the first request after a deploy will make fresh API calls.

---

---

## Project Structure

```
accumulator/
├── main.py                  # FastAPI app entry point
├── data/
│   ├── fetcher.py           # All API calls and scraping logic
│   ├── cache.py             # Local file-based caching
│   └── parser.py            # Data cleaning and normalisation
├── analysis/
│   ├── selection.py         # Selection logic and confidence scoring
│   ├── matchups.py          # Player vs player matchup analysis
│   └── tiers.py             # Tier building logic
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── logs/
│   └── activity.log         # All API calls, scrapes, and failures
├── cache/                   # Auto-created; stores all cached responses
├── requirements.txt
└── README.md
```

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Serves the frontend SPA |
| `GET /matchday?date=YYYY-MM-DD&leagues=PL,PD` | Full analysis (JSON) |
| `GET /admin/log` | Activity log (plain text) |
| `GET /health` | Health check (JSON) |

### League codes
| Code | League |
|---|---|
| `PL` | Premier League (England) |
| `PD` | La Liga (Spain) |
| `BL1` | Bundesliga (Germany) |
| `SA` | Serie A (Italy) |
| `FL1` | Ligue 1 (France) |

---

## Technical Decisions

### Backend: FastAPI
FastAPI was chosen over Flask because it provides async support, automatic OpenAPI docs, and built-in data validation with Pydantic. The async route handlers allow concurrent data enrichment without blocking.

### No ORM / database
All state is held in local JSON cache files under `/cache`. This keeps the project zero-dependency for persistence and means the entire thing runs from a single machine with no setup beyond `pip install`.

### Caching strategy
Cache files follow the naming pattern `{source}_{leaguecode}_{YYYYMMDD}.json`. Before every external call, the system checks whether a matching cache file exists. This is critical for preserving the Odds API free-tier allowance (500 requests/month). The-Odds-API is called at most once per league per day regardless of how many times `/matchday` is hit.

### Understat scraping approach
Understat embeds match data as a JavaScript variable (`datesData`) inside a `<script>` tag. Rather than parsing the full HTML DOM, we extract it with a targeted regex against the raw source. This is more robust against layout changes because it targets the data transport layer, not the presentation layer.

### FBref scraping approach
`pandas.read_html()` is used rather than raw HTML parsing. FBref's statistical tables are well-structured and this method is significantly more stable than writing BeautifulSoup selectors that break when the site updates its CSS classes. FBref has a multi-index column structure; we flatten it by joining the levels with `_` and then apply a rename map to canonical names.

### Request throttling
- Understat: 2-second minimum delay between requests (global state variable)
- FBref: 3-second minimum delay between requests (global state variable)
Both are implemented as blocking `time.sleep()` calls within the fetcher functions, which is acceptable because data fetching happens once per analysis run and results are cached.

### Selection confidence scoring (1–10 scale)
The base score (1–8) is derived from how far the season average exceeds or falls below the market threshold, expressed as a percentage margin. A 40%+ margin gives a base of 8; under 0% gives a maximum base of 3. H2H penalty (−1) and matchup bonus (+1) are applied on top. This approach means the score is directly interpretable: a 7 means the stat supports the threshold but there is meaningful uncertainty; an 8 means strong support.

### Tier building: greedy algorithm
Selections are sorted by confidence (primary) then individual decimal odds (secondary). The greedy algorithm adds the highest-ranked selection at each step provided it doesn't duplicate a market for the same fixture. This is O(n²) in the worst case but n is always small (<100 selections) so performance is not a concern.

### Correct Score: Poisson approximation
The most likely correct score is estimated by finding the (home_goals, away_goals) pair that maximises `PMF(xG_home, h) × PMF(xG_away, a)` across all (h, a) pairs from 0–4 goals each. This is a standard technique in football analytics and gives reasonable results when xG data is available.

### Frontend: vanilla HTML/CSS/JS
No framework was used by design — the specification requires it. The frontend is a single `fetch` call to `/matchday` and pure DOM manipulation. `innerHTML` is used with an `escHtml()` utility for all user-derived content to prevent XSS. The CSS uses custom properties (variables) for the colour theme and a three-column CSS grid that collapses to one column on mobile via a single `@media` breakpoint.

---

## Data Sources: Known Limitations

### football-data.org (free tier)
- Rate-limited to 10 calls per minute.
- Free tier covers PL, PD, BL1, SA, FL1 (the five leagues used here).
- Player-level data is not available on the free tier; only team/match-level stats are used.
- H2H data is limited to the last 5 matches across all competitions (not just the current league).

### The-Odds-API (free tier)
- 500 requests/month hard limit — caching is critical.
- Does not provide player prop markets (e.g. player cards, player shots) on the free tier.
- Odds coverage varies by bookmaker and market; corners/fouls/cards totals may not always be present.

### Understat.com
- Provides xG at match level for the five major European leagues.
- Corners data is not directly available from Understat; corners are approximated from xG using a linear proxy (corners ≈ xG × 3.8), which is a rough estimate.
- The embedded `datesData` JSON variable was the extraction target as of the build date (2024). If Understat changes this variable name, the parser will log a failure and continue without xG data for affected fixtures.

### FBref.com
- Player per-90 stats are cumulative season stats, not rolling form — a player who was dangerous in September but has been injured since will still appear in the top percentiles.
- FBref implements rate limiting and occasionally serves Cloudflare challenges. The 3-second delay reduces but does not eliminate the risk of being rate-limited.
- Column names in FBref tables change periodically. The column rename map in `fetcher.py` targets the most common patterns (multi-index flattened names) but may need updating if FBref restructures its tables.

---

## Running Self-Tests

Each module has a simple self-test block at the bottom:

```bash
cd accumulator
python data/cache.py
python data/parser.py
python analysis/matchups.py
python analysis/selection.py
python analysis/tiers.py
```

All should print `*-test passed.` with no errors.
