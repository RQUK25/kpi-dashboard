#!/usr/bin/env bash
# ================================================================
# Accumulator Predictor – Local startup script
# Usage: ./start.sh [port]          (default port: 8000)
# Demo:  ./start.sh --demo          (open demo mode in browser)
# ================================================================

set -e

PORT="${1:-8000}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ----------------------------------------------------------------
# 1. Check Python
# ----------------------------------------------------------------
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found. Please install Python 3.9+."
  exit 1
fi

PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python $PYVER detected."

# ----------------------------------------------------------------
# 2. Install / check dependencies
# ----------------------------------------------------------------
echo "Checking dependencies..."
python3 -c "import fastapi, uvicorn, requests, bs4, pandas" 2>/dev/null || {
  echo "Installing dependencies from requirements.txt..."
  pip3 install -r requirements.txt --quiet
}
echo "Dependencies OK."

# ----------------------------------------------------------------
# 3. .env check
# ----------------------------------------------------------------
if [ ! -f ".env" ]; then
  cp .env.template .env
  echo ""
  echo "============================================================"
  echo "  Created .env from template."
  echo "  The app will run, but you need API keys for live data."
  echo "  Edit .env and fill in:"
  echo "    FOOTBALL_DATA_KEY  →  football-data.org  (free tier)"
  echo "    ODDS_API_KEY       →  the-odds-api.com   (free tier)"
  echo "  Then re-run ./start.sh"
  echo ""
  echo "  You can still preview the UI at:"
  echo "    http://localhost:${PORT}/demo"
  echo "============================================================"
  echo ""
fi

# ----------------------------------------------------------------
# 4. Start server
# ----------------------------------------------------------------
echo ""
echo "Starting Accumulator Predictor on port $PORT..."
echo ""
echo "  Live data:  http://localhost:${PORT}"
echo "  Demo mode:  http://localhost:${PORT}/demo"
echo "  API docs:   http://localhost:${PORT}/docs"
echo "  Activity:   http://localhost:${PORT}/admin/log"
echo ""
echo "Press Ctrl+C to stop."
echo ""

exec uvicorn main:app --host 0.0.0.0 --port "$PORT" --app-dir .
