#!/usr/bin/env bash
# Refresh the forecast and re-score every place (Part 02 R2.3b; run every 6 hours).
#
#   1. heatwave-ingest forecast   pull today + 3 days from Open-Meteo for every place in
#                                 config/regions.yaml (Part 02)
#   2. heatwave-prepare sample    rebuild data/sample/forecast_features.csv through the
#                                 inference path; the ML service reloads it on its next read
#   3. npm run score-all          score every place x lead 0-3 not yet scored on this forecast
#      -- --only-missing          issue, through the ML service, into MongoDB (Part 07 §B)
#
# Needs the ML service (SERVICE_ROLE=ml) and MongoDB running, and server/.env with the same
# ML_SERVICE_TOKEN as the ML service. Exits non-zero on the first failing step; the data
# then simply ages and the UI flags it as stale, never as current.
#
# cron (Linux/macOS), every 6 hours, logging to a file:
#   0 */6 * * * cd /path/to/heatwave-prediction && deploy/refresh-forecast.sh >> data/local/refresh.log 2>&1
# Windows Task Scheduler: Program `bash.exe` (Git Bash), arguments `deploy/refresh-forecast.sh`,
#   start in the repository root, trigger daily, repeat every 6 hours.
set -euo pipefail

cd "$(dirname "$0")/.."
stamp() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

# The Python tools: through uv when it is installed (the documented setup), else the venv.
if command -v uv >/dev/null 2>&1; then
  py() { uv run "$@"; }
else
  py() { ".venv/bin/$1" "${@:2}"; }
fi

echo "$(stamp) refresh: pulling the forecast"
py heatwave-ingest forecast
echo "$(stamp) refresh: rebuilding the forecast features"
py heatwave-prepare sample
echo "$(stamp) refresh: scoring places not yet scored on this forecast"
(cd server && npm run --silent score-all -- --only-missing)
echo "$(stamp) refresh: done"
