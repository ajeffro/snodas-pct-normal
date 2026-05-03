#!/usr/bin/env bash
# ===========================================================================
# SNODAS SWE Percent-of-Average Tool — Quick Start
# ===========================================================================
#
# This script runs the full pipeline from scratch:
#   1. Downloads SNODAS historical archive (THIS TAKES HOURS on first run)
#   2. Builds the day-of-year climatology
#   3. Downloads latest SNODAS data
#   4. Computes today's percent-of-average and generates map tiles
#   5. Starts the web viewer
#
# Prerequisites:
#   python -m venv .venv && source .venv/bin/activate
#   pip install -r requirements.txt
#
# For subsequent daily updates, just run:
#   python scripts/download_snodas.py
#   python scripts/compute_daily_pct.py
#
# ===========================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo "WARNING: No active virtual environment detected."
    echo "         Run: python -m venv .venv && source .venv/bin/activate"
    echo "         Then re-run this script."
    echo ""
fi

run_step() {
    local step="$1" label="$2"; shift 2
    echo ""
    echo "[${step}] ${label} — $(date '+%H:%M:%S')"
    "$@" || { echo "FAILED at step ${step}: ${label}"; exit 1; }
    echo "      done — $(date '+%H:%M:%S')"
}

echo "================================================"
echo "SNODAS SWE Percent-of-Average Tool"
echo "================================================"
echo ""
echo "Step 1 will take several hours on first run."
echo "(Ctrl+C to cancel — progress is saved)"

run_step "1/5" "Downloading SNODAS historical archive" \
    python scripts/download_snodas.py --backfill --start-year 2004

run_step "2/5" "Building day-of-year climatology" \
    python scripts/build_climatology.py

run_step "3/5" "Downloading latest SNODAS data" \
    python scripts/download_snodas.py

run_step "4/5" "Computing percent-of-average and generating tiles" \
    python scripts/compute_daily_pct.py

echo ""
echo "Open http://localhost:8080 in your browser"
run_step "5/5" "Starting web viewer" \
    python webapp/app.py
