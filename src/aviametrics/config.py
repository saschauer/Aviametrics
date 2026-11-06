"""Configuration: one TOML profile + environment variables for paths."""
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = tomllib.loads((ROOT / "config" / os.environ.get("AVIA_PROFILE", "default.toml")).read_text())

DATA = Path(os.environ.get("AVIA_DATA", ROOT / "data")).expanduser()
IMPORT_DIR = Path(os.environ.get("AVIA_IMPORT_DIR", "/import"))          # optional: already extracted days
IMPORT_DATE = os.environ.get("AVIA_IMPORT_DATE", "")                     # date of the day in IMPORT_DIR/day
API_URL = os.environ.get("AVIA_API_URL", "http://localhost:8000")

BBOX = CFG["area"]["bbox_core"]
BUFFER = CFG["area"]["bbox_buffer"]
GAP = CFG["processing"]["segment_gap_s"]


def positions_path(day: str) -> Path:
    return DATA / "positions" / f"day={day}" / "positions.parquet"


def flights_path(day: str) -> Path:
    return DATA / "flights" / f"day={day}" / "flights.parquet"


def geo_dir() -> Path:
    return DATA / "geo"
