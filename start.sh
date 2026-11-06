#!/usr/bin/env bash
# Aviametrics – one command start.   ./start.sh          (Docker, recommended)
#                                     ./start.sh --local  (without Docker, via uv)
# Optional: use an already extracted day:  AVIA_IMPORT_DIR=~/aviabench AVIA_IMPORT_DATE=2026-11-03 ./start.sh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p data/dagster_home import && touch data/dagster_home/dagster.yaml
[ -d data/geo ] || git clone -q --depth 1 https://github.com/ginseng666/GeoJSON-TopoJSON-Austria data/geo
if [ -d "$HOME/aviabench/live_out/raw/adsb.lol" ] && [ ! -d data/replay ]; then
  mkdir -p data/replay && cp "$HOME"/aviabench/live_out/raw/adsb.lol/*.json data/replay/ 2>/dev/null || true
fi
echo "App: http://localhost:8501   API docs: http://localhost:8000/docs   Pipeline (Dagster): http://localhost:3000"
if [ "${1:-}" = "--local" ]; then
  export AVIA_DATA="$PWD/data" DAGSTER_HOME="$PWD/data/dagster_home" PYTHONPATH="$PWD/src" AVIA_API_URL=http://localhost:8000
  export AVIA_IMPORT_DIR="${AVIA_IMPORT_DIR:-$PWD/import}"
  uv sync -q
  uv run uvicorn aviametrics.api.main:app --port 8000 > data/api.log 2>&1 &
  uv run dagster dev -m aviametrics.pipeline.definitions -p 3000 > data/dagster.log 2>&1 &
  trap 'kill $(jobs -p) 2>/dev/null' EXIT
  uv run streamlit run app/Aviametrics.py
else
  command -v docker >/dev/null || { echo "Docker not found – use ./start.sh --local"; exit 1; }
  docker compose up --build
fi
