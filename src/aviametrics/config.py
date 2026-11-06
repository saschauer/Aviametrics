"""Configuration: one TOML profile + environment variables for paths."""
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = tomllib.loads((ROOT / "config" / os.environ.get("AVIA_PROFILE", "default.toml")).read_text())

DATA = Path(os.environ.get("AVIA_DATA", ROOT.parent / "aviametrics-data")).expanduser()
IMPORT_DIR = Path(os.environ.get("AVIA_IMPORT_DIR", "/import"))          # optional: already extracted days
IMPORT_DATE = os.environ.get("AVIA_IMPORT_DATE", "")                     # date of the extracted day
IMPORT_NAME = os.environ.get("AVIA_IMPORT_NAME", "day")                  # folder name inside IMPORT_DIR
API_URL = os.environ.get("AVIA_API_URL", "http://localhost:8000")
HOST_HOME = os.environ.get("AVIA_HOST_HOME", "")      # host home dir, mounted read-only at /host in Docker
HOST_MOUNT = "/host"


def to_container(path: str) -> Path:
    """Translate a path on the user's computer into the path visible inside the container."""
    p = os.path.expanduser(path.strip())
    if HOST_HOME and p.startswith(HOST_HOME):
        return Path(HOST_MOUNT + p[len(HOST_HOME):])
    return Path(p)

BBOX = CFG["area"]["bbox_core"]
BUFFER = CFG["area"]["bbox_buffer"]
GAP = CFG["processing"]["segment_gap_s"]


def positions_path(day: str) -> Path:
    return DATA / "positions" / f"day={day}" / "positions.parquet"


def flights_path(day: str) -> Path:
    return DATA / "flights" / f"day={day}" / "flights.parquet"


def geo_dir() -> Path:
    return DATA / "geo"
