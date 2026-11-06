"""Pipeline steps as plain functions (used by the Dagster assets and callable without Dagster)."""
import os
import subprocess
from multiprocessing import Pool
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from aviametrics import progress, storage
from aviametrics.config import BUFFER, DATA, GAP, geo_dir
from aviametrics.sources.adsblol import raw_day_dir, read_trace, trace_files

SCHEMA = pa.schema([("icao", pa.string()), ("reg", pa.string()), ("type", pa.string()), ("mil", pa.bool_()),
                    ("ts", pa.int64()), ("lat", pa.float64()), ("lon", pa.float64()), ("alt", pa.int32()),
                    ("gs", pa.float32()), ("track", pa.float32())])
LAT0, LAT1, LON0, LON1 = BUFFER


def _num(v, f):
    return None if v is None or isinstance(v, str) else f(v)


def _parse(path: str):
    """Cleaning rules: drop points without position, outside the stored area, or with impossible values."""
    d = read_trace(path)
    if not d:
        return None
    icao, reg, typ, mil, base = d.get("icao"), d.get("r"), d.get("t"), bool((d.get("dbFlags") or 0) & 1), d.get("timestamp", 0)
    cols = [[] for _ in SCHEMA]
    for p in d.get("trace", []):
        if len(p) < 6 or p[1] is None or p[2] is None or not (LAT0 <= p[1] <= LAT1 and LON0 <= p[2] <= LON1):
            continue
        alt = 0 if p[3] == "ground" else _num(p[3], int)
        if alt is not None and not (-1500 <= alt <= 60000):
            continue
        for c, v in zip(cols, (icao, reg, typ, mil, int(base + p[0]), float(p[1]), float(p[2]), alt,
                               _num(p[4], float), _num(p[5], float))):
            c.append(v)
    if not cols[0]:
        return None
    return pa.Table.from_arrays([pa.array(c, type=f.type) for c, f in zip(cols, SCHEMA)], schema=SCHEMA)


def regions_file() -> Path | None:
    g = geo_dir()
    if not g.is_dir():
        subprocess.run(["git", "clone", "-q", "--depth", "1", "https://github.com/ginseng666/GeoJSON-TopoJSON-Austria", str(g)])
    cand = [p for p in g.glob("2021/**/*.json") if "laender" in p.name.lower() and "topo" not in str(p).lower()]
    return min(cand, key=lambda p: p.stat().st_size) if cand else None


def _guard(day: str, fn, *a, **k):
    """Run a pipeline step; on failure show the real error (type + message) in the progress display."""
    try:
        return fn(*a, **k)
    except Exception as e:
        stage = (progress.read(day) or {}).get("stage", "download")
        progress.report(day, stage, None, f"{type(e).__name__}: {str(e).strip().splitlines()[0][:300] if str(e).strip() else ''}", status="failed")
        raise


def build_positions(day: str, log=print) -> str:
    return _guard(day, _build_positions, day, log)


def _build_positions(day: str, log=print) -> str:
    import shutil
    shutil.rmtree(DATA / "gold" / day, ignore_errors=True)   # cached views of this day are outdated now
    progress.report(day, "download", 0, "")
    raw = raw_day_dir(day)
    files = trace_files(raw)
    log(f"{len(files)} trace files")
    parts = []
    with Pool(max(1, (os.cpu_count() or 2) - 1)) as pool:
        for i, t in enumerate(pool.imap_unordered(_parse, files, chunksize=64)):
            if t is not None:
                parts.append(t)
            if i % 2000 == 0:
                progress.report(day, "parse", 100 * i / max(1, len(files)), f"{i:,} / {len(files):,} files · {len(parts):,} aircraft")
    tbl = pa.concat_tables(parts).sort_by([("icao", "ascending"), ("ts", "ascending")])
    log(f"{tbl.num_rows} positions, {len(parts)} aircraft")
    stage = DATA / "staging"
    stage.mkdir(parents=True, exist_ok=True)
    tmp = stage / f"positions_{day}.parquet"
    pq.write_table(tbl, tmp, compression="zstd")
    con = storage.connect()
    progress.report(day, "enrich", None, f"{tbl.num_rows:,} positions")
    select = f"SELECT *, NULL::VARCHAR AS bl FROM '{tmp}'"
    try:  # enrichment: Bundesland per position (DuckDB spatial, point-in-polygon)
        con.sql("INSTALL spatial; LOAD spatial")
        f = regions_file()
        cols = [r[0] for r in con.sql(f"DESCRIBE SELECT * FROM ST_Read('{f}')").fetchall()]
        name = "name" if "name" in cols else next(c for c in cols if c != "geom")
        con.sql(f"CREATE TEMP TABLE reg AS SELECT \"{name}\"::VARCHAR AS bl, geom FROM ST_Read('{f}')")
        select = (f"SELECT p.*, r.bl FROM '{tmp}' p LEFT JOIN reg r ON ST_Contains(r.geom, ST_Point(p.lon, p.lat)) "
                  f"ORDER BY icao, ts")
    except Exception as e:
        log(f"Bundesland enrichment skipped: {e!r}")
    progress.report(day, "write", None, storage.MODE)
    target = storage.write(con, "positions", day, select)
    tmp.unlink()
    log(f"written {target}")
    return target


def build_flights(day: str) -> str:
    return _guard(day, _build_flights, day)


def _build_flights(day: str) -> str:
    """Flight segmentation: a new segment starts after more than GAP seconds without signal."""
    progress.report(day, "flights", None, "segmentation")
    con = storage.connect()
    select = f"""
          WITH d AS (SELECT *, ts - lag(ts) OVER w AS gap, lag(lat) OVER w AS plat, lag(lon) OVER w AS plon
                     FROM {storage.src("positions", day)} WINDOW w AS (PARTITION BY icao ORDER BY ts)),
               s AS (SELECT *, sum(CASE WHEN gap IS NULL OR gap > {GAP} THEN 1 ELSE 0 END) OVER (PARTITION BY icao ORDER BY ts) AS seg FROM d)
          SELECT icao, seg, any_value(reg) AS reg, any_value(type) AS type, bool_or(mil) AS mil,
                 min(ts) AS t_start, max(ts) AS t_end, count(*) AS points, max(alt) AS max_alt,
                 round(sum(CASE WHEN gap <= {GAP} THEN 2*6371*asin(sqrt(pow(sin(radians(lat-plat)/2),2)
                   + cos(radians(plat))*cos(radians(lat))*pow(sin(radians(lon-plon)/2),2))) END), 1) AS km
          FROM s GROUP BY icao, seg ORDER BY t_start"""
    return storage.write(con, "flights", day, select)
