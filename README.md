# Aviametrics – showcase prototype (branch `showcase`)
Flight data analysis platform for the BMLV (diploma thesis TGM 2026/27, Stefan Aschauer & Isaac Jerryson).
Showcase for the open day, built on the planned Core architecture; created with AI assistance (Claude), reviewed by the team.

## Quick start
Requirements: Docker (or `uv` for `--local`) and git. No data is included – it is downloaded on demand into `data/` (not in git).

    git clone -b showcase https://github.com/saschauer/Aviametrics.git && cd Aviametrics
    ./start.sh
    ./stop.sh

Then open the app and use the **Data** tab: download a day, or let the app auto-detect already extracted
adsb.lol days in your folders and import them. Storage location: `.env` (see `.env.example`).
Without Docker: `./start.sh --local`.
App http://localhost:8501 · API docs http://localhost:8000/docs · Pipeline (Dagster) http://localhost:3000
More days: in the app (Time travel → Load another day) or in Dagster (materialize a partition).
Data location: `data/` in the project folder; set `AVIA_DATA` to store it elsewhere (e.g. a server disk).

## Architecture
adsb.lol archive → Dagster assets (positions → flights) → Parquet in data/ → repository (DuckDB) → FastAPI (/v1/…, JSON + Arrow, role masking) → Streamlit app and external plugins.
Data: adsb.lol (ODbL) · Borders: Statistik Austria via ginseng666 (CC BY 4.0) · Map tiles: © CARTO, © OpenStreetMap.
