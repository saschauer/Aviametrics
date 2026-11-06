# Aviametrics – showcase prototype (branch `showcase`)
Flight data analysis platform for the BMLV (diploma thesis TGM 2026/27, Stefan Aschauer & Isaac Jerryson).
Showcase for the open day, built on the planned Core architecture; created with AI assistance (Claude), reviewed by the team.

## Start
    ./start.sh                 # Docker Compose: pipeline (Dagster), api (FastAPI), app (Streamlit)
    ./start.sh --local         # same without Docker (uv)
App http://localhost:8501 · API docs http://localhost:8000/docs · Dagster http://localhost:3000

Load a day: in the app (Time travel → Load another day) or in Dagster (materialize partition).
Use an already extracted day without downloading: `AVIA_IMPORT_DIR=~/aviabench AVIA_IMPORT_DATE=2026-11-03 ./start.sh`
(expects the extracted archive in `~/aviabench/day`).

## Architecture
adsb.lol archive → Dagster assets (positions → flights) → Parquet in data/ → repository (DuckDB) → FastAPI (/v1/…, JSON + Arrow, role masking) → Streamlit app and external plugins.
Data: adsb.lol (ODbL) · Borders: Statistik Austria via ginseng666 (CC BY 4.0) · Map tiles: © CARTO, © OpenStreetMap.
