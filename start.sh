#!/usr/bin/env bash
# Aviametrics – start everything with one command.
#
#   ./start.sh                         start (Docker); load days later in the app or in Dagster
#   ./start.sh --day 2026-11-03        start and load this day right away (download ≈ 3 GB, ≈ 10 min)
#   ./start.sh --day 2026-11-03 --import ~/aviabench/day    use an already extracted day instead of downloading
#   ./start.sh --local                 same without Docker (needs uv)
#   ./stop.sh                          stop everything
set -euo pipefail
cd "$(dirname "$0")"
MODE=docker DAY="" IMPORT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --local) MODE=local ;;
    --day) DAY="$2"; shift ;;
    --import) IMPORT="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac; shift
done

[ -f .env ] && set -a && . ./.env && set +a
D="${AVIA_DATA_DIR:-../aviametrics-data}"; mkdir -p "$D"; D="$(cd "$D" && pwd)"; export AVIA_DATA_DIR="$D"
mkdir -p "$D/dagster_home" "$D/.home" import && touch "$D/dagster_home/dagster.yaml"
[ -d "$D/geo" ] || git clone -q --depth 1 https://github.com/ginseng666/GeoJSON-TopoJSON-Austria "$D/geo"
if [ -n "$IMPORT" ]; then
  [ -d "$IMPORT" ] || { echo "import folder not found: $IMPORT"; exit 1; }
  [ -n "$DAY" ] || { echo "--import needs --day YYYY-MM-DD"; exit 1; }
  export AVIA_IMPORT_DIR="$(dirname "$IMPORT")" AVIA_IMPORT_DATE="$DAY" AVIA_IMPORT_NAME="$(basename "$IMPORT")"
fi
export AVIA_UID="$(id -u)" AVIA_GID="$(id -g)"

wait_api() { for _ in $(seq 1 120); do curl -sf http://localhost:8000/v1/health >/dev/null && return 0; sleep 2; done; return 1; }
load_day() { [ -z "$DAY" ] && return 0; echo "Loading day $DAY (progress: Dagster http://localhost:3000)"; curl -sf -X POST "http://localhost:8000/v1/days/$DAY" >/dev/null || echo "could not start pipeline"; }
banner() { echo; echo "  ✈  AVIAMETRICS is running"; echo "     App       http://localhost:8501"; echo "     API docs  http://localhost:8000/docs"; echo "     Pipeline  http://localhost:3000"; echo; }

if [ "$MODE" = local ]; then
  command -v uv >/dev/null || { echo "uv missing: sudo pacman -S uv  (or https://docs.astral.sh/uv/)"; exit 1; }
  export AVIA_DATA="$(cd "$D" && pwd)" DAGSTER_HOME="$(cd "$D" && pwd)/dagster_home" PYTHONPATH="$PWD/src" AVIA_API_URL=http://localhost:8000
  export AVIA_IMPORT_DIR="${AVIA_IMPORT_DIR:-$PWD/import}"
  uv sync -q
  uv run uvicorn aviametrics.api.main:app --port 8000 > "$D/api.log" 2>&1 &
  uv run dagster dev -m aviametrics.pipeline.definitions -p 3000 > "$D/dagster.log" 2>&1 &
  trap 'kill $(jobs -p) 2>/dev/null' EXIT
  wait_api && load_day && banner
  uv run streamlit run app/Aviametrics.py
else
  command -v docker >/dev/null || { echo "Docker missing – install it or use ./start.sh --local"; exit 1; }
  docker info >/dev/null 2>&1 || { echo "Docker is not running or no permission: sudo systemctl start docker; sudo usermod -aG docker \$USER (then log in again)"; exit 1; }
  docker compose up -d --build
  echo "waiting for the API ..."; wait_api || { echo "API did not start – see: docker compose logs api"; exit 1; }
  load_day; banner
  echo "Logs follow (Ctrl+C stops only the log view; ./stop.sh stops Aviametrics)"; docker compose logs -f --tail 5
fi
