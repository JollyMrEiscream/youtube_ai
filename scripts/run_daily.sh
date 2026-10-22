#!/bin/sh
# Cron entry, from the repo root, after `pip install -e .` and a filled-in .env:
#   15 8 * * * /path/to/youtube_ai/scripts/run_daily.sh >> /path/to/youtube_ai/logs/daily.log 2>&1
# Upload is a separate command you run after review:
#   0 18 * * * cd /path/to/youtube_ai && .venv/bin/python -m news_youtube_bot upload
set -eu
cd "$(dirname "$0")/.."
if [ -f .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python3
fi
exec "$PY" -m news_youtube_bot run
