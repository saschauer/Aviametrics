"""Repository: the ONLY module that knows the storage engine (DuckDB on Parquet).
Swapping the engine (e.g. ClickHouse) means re-implementing these functions – the API and app stay unchanged."""
import hashlib
import threading

from aviametrics import storage
from aviametrics.config import BBOX, GAP

_local = threading.local()
LAT0, LAT1, LON0, LON1 = BBOX
IN_AT = f"lat BETWEEN {LAT0} AND {LAT1} AND lon BETWEEN {LON0} AND {LON1}"   # stored area (rectangle incl. border buffer)
AT = "bl IS NOT NULL"   # inside Austria's national border (Bundesland assigned by point-in-polygon in the pipeline)
HAV = ("2*6371*asin(sqrt(pow(sin(radians(lat-plat)/2),2)+cos(radians(plat))*cos(radians(lat))"
       "*pow(sin(radians(lon-plon)/2),2)))")


def con():
    if not hasattr(_local, "c"):
        _local.c = storage.connect()
    return _local.c


def days() -> list[str]:
    return storage.days(con())


def _days(day) -> list[str]:
    return day if isinstance(day, list) else [day]


def _p(day):
    """day: one date string or a list of dates (period)."""
    return storage.src_days("positions", _days(day))


def _f(day):
    return storage.src_days("flights", _days(day))


def _has_flights(day) -> bool:
    return all(storage.has(con(), "flights", d) for d in _days(day))


def kpis(day: str) -> dict:
    n_pos, n_ac = storage.one(con(), f"SELECT count(*), count(DISTINCT icao) FROM {_p(day)} WHERE {AT}")
    km = storage.one(con(), f"""SELECT sum({HAV}) FROM (SELECT bl, lat, lon, lag(lat) OVER w plat, lag(lon) OVER w plon, ts - lag(ts) OVER w gap
                       FROM {_p(day)} WINDOW w AS (PARTITION BY icao ORDER BY ts)) WHERE gap <= {GAP} AND {AT}""")[0]
    segs = storage.one(con(), f"SELECT count(*) FROM {_f(day)}")[0] if _has_flights(day) else None
    return {"positions": n_pos, "aircraft": n_ac, "flights": segs, "km": round(km or 0)}


def hourly(day, utc_offset_h: int = 1) -> list[dict]:
    """Aircraft per hour of day (local time); for a period: average per day."""
    n = len(_days(day))
    return storage.to_records(con().sql(f"""SELECT ((ts + {utc_offset_h * 3600}) % 86400) // 3600 AS hour,
                                    round(count(DISTINCT (icao, ts // 86400)) / {n}, 1) AS aircraft
                         FROM {_p(day)} WHERE {AT} GROUP BY 1 ORDER BY 1"""))


def types(day: str, limit: int = 12) -> list[dict]:
    return storage.to_records(con().sql(f"""SELECT coalesce(type, '?') AS type, count(DISTINCT icao) AS aircraft FROM {_p(day)}
                         WHERE {AT} AND NOT mil GROUP BY 1 ORDER BY 2 DESC LIMIT {limit}"""))


def regions(day: str) -> list[dict]:
    return storage.to_records(con().sql(f"""SELECT bl AS region, count(DISTINCT icao) AS aircraft, round(sum({HAV})) AS km FROM (
                           SELECT bl, icao, lat, lon, lag(lat) OVER w plat, lag(lon) OVER w plon, ts - lag(ts) OVER w gap
                           FROM {_p(day)} WINDOW w AS (PARTITION BY icao ORDER BY ts))
                         WHERE bl IS NOT NULL AND gap <= {GAP} GROUP BY 1 ORDER BY 3 DESC"""))


def facts(day: str) -> dict:
    out = {}
    if _has_flights(day):
        r = storage.one(con(), f"SELECT coalesce(type,'?'), km, t_end - t_start FROM {_f(day)} WHERE NOT mil ORDER BY km DESC LIMIT 1")
        if r:
            out["longest_flight"] = {"type": r[0], "km": r[1], "minutes": round(r[2] / 60)}
    r = storage.one(con(), f"SELECT ts // 60 AS m, count(DISTINCT icao) n FROM {_p(day)} WHERE {AT} GROUP BY 1 ORDER BY 2 DESC LIMIT 1")
    if r:
        out["busiest_minute"] = {"utc_minute_of_day": int(r[0] % 1440), "aircraft": r[1]}
    r = storage.one(con(), f"SELECT coalesce(type,'?'), max(alt) FROM {_p(day)} WHERE {AT} AND NOT mil GROUP BY 1 ORDER BY 2 DESC LIMIT 1")
    if r:
        out["highest"] = {"type": r[0], "alt_ft": r[1]}
    return out


# ------------------------------------------------------------------ precomputed views ("gold" layer, cached on disk)
def _gold(day: str, name: str, build):
    """Serve a view from DATA/gold/<day>/<name>.json.gz; compute and store it on first use.
    The pipeline deletes DATA/gold/<day> whenever the day is (re)imported."""
    import gzip
    import json
    from aviametrics.config import DATA
    f = DATA / "gold" / day / f"{name}.json.gz"
    if f.exists():
        return json.loads(gzip.decompress(f.read_bytes()))
    data = build()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode(), 5))
    tmp.replace(f)
    return data


def trips(day: str, step_s: int = 60) -> dict:
    """Downsampled airborne trajectories (seconds since local midnight); colour only needs the max altitude."""
    def build():
        t0 = storage.one(con(), f"SELECT min(ts) - (min(ts) + 3600) % 86400 FROM {_p(day)}")[0]
        rows = con().sql(f"""SELECT bool_or(mil) AS mil, list([lon, lat] ORDER BY ts) AS path,
                                    list(ts - {t0} ORDER BY ts) AS t, max(coalesce(alt, 0)) AS a
                             FROM (SELECT * FROM {_p(day)}
                                   WHERE alt > 0 AND coalesce(gs, 0) >= 40       -- airborne only
                                   QUALIFY row_number() OVER (PARTITION BY icao, ts // {step_s} ORDER BY ts) = 1)
                             GROUP BY icao HAVING count(*) > 2""").fetchall()
        return {"t0": t0, "trips": [{"m": int(r[0]), "p": [[round(x, 3), round(y, 3)] for x, y in r[1]],
                                     "t": [int(v) for v in r[2]], "a": int(r[3])} for r in rows]}
    return _gold(day, f"trips_{step_s}", build)


def trips_range(days_wanted: list[str], step_s: int = 60) -> dict:
    """Several days on one timeline: day i is shifted by i*86400 s; days without data stay empty."""
    have, out, info = set(days()), [], []
    for i, d in enumerate(days_wanted):
        info.append({"date": d, "has": d in have})
        if d in have:
            for tr in trips(d, step_s)["trips"]:
                out.append({**tr, "t": [v + i * 86400 for v in tr["t"]]})
    return {"days": info, "span": 86400 * len(days_wanted), "trips": out}


def positions(day: str, start: int | None = None, end: int | None = None, bbox: list[float] | None = None):
    """Arrow table of positions – the plugin data access."""
    w = [AT if bbox is None else f"lat BETWEEN {bbox[0]} AND {bbox[1]} AND lon BETWEEN {bbox[2]} AND {bbox[3]}"]
    if start:
        w.append(f"ts >= {int(start)}")
    if end:
        w.append(f"ts <= {int(end)}")
    return storage.to_arrow(con().sql(f"SELECT * FROM {_p(day)} WHERE {' AND '.join(w)} ORDER BY icao, ts"))


def flights(day: str):
    return storage.to_arrow(con().sql(f"SELECT * FROM {_f(day)}"))


# ------------------------------------------------------------------ data quality
STATIONARY = """SELECT icao FROM {src} GROUP BY icao
                HAVING count(*) > 500 AND stddev_pop(lat) < 0.01 AND stddev_pop(lon) < 0.01"""


def quality(day: str) -> dict:
    """Plausibility checks for one day – basis for the cleaning rules (and the thesis)."""
    p = _p(day)
    r = storage.one(con(), f"""SELECT count(*), count(DISTINCT icao),
            count(*) FILTER (WHERE alt <= 0), count(*) FILTER (WHERE alt IS NULL),
            count(*) FILTER (WHERE alt > 50000), count(*) FILTER (WHERE gs > 700),
            count(*) FILTER (WHERE type IS NULL OR type = ''), count(*) FILTER (WHERE mil),
            count(*) - count(DISTINCT (icao, ts)) FROM {p}""")
    n = max(r[0], 1)
    per_ac = storage.one(con(), f"""SELECT count(*) FILTER (WHERE c < 5), median(c), max(c)
                                    FROM (SELECT icao, count(*) c FROM {p} GROUP BY icao)""")
    stationary = storage.to_records(con().sql(f"""
        SELECT icao, any_value(type) AS type, count(*) AS positions, round(avg(lat), 4) AS lat, round(avg(lon), 4) AS lon,
               max(alt) AS max_alt FROM {p} GROUP BY icao
        HAVING count(*) > 500 AND stddev_pop(lat) < 0.01 AND stddev_pop(lon) < 0.01 ORDER BY positions DESC LIMIT 8"""))
    st_n = sum(x["positions"] for x in stationary)
    return {"positions": r[0], "aircraft": r[1],
            "checks": [
                {"check": "ground", "count": r[2], "pct": round(100 * r[2] / n, 1)},
                {"check": "no_altitude", "count": r[3], "pct": round(100 * r[3] / n, 1)},
                {"check": "alt_over_50000ft", "count": r[4], "pct": round(100 * r[4] / n, 2)},
                {"check": "speed_over_700kt", "count": r[5], "pct": round(100 * r[5] / n, 2)},
                {"check": "no_type", "count": r[6], "pct": round(100 * r[6] / n, 1)},
                {"check": "military", "count": r[7], "pct": round(100 * r[7] / n, 1)},
                {"check": "duplicates", "count": r[8], "pct": round(100 * r[8] / n, 2)},
                {"check": "stationary_transmitters", "count": st_n, "pct": round(100 * st_n / n, 1)},
                {"check": "aircraft_under_5_points", "count": per_ac[0], "pct": round(100 * per_ac[0] / max(r[1], 1), 1)},
            ],
            "points_per_aircraft_median": per_ac[1], "points_per_aircraft_max": per_ac[2], "stationary": stationary}


# ------------------------------------------------------------------ masking (concept of Isaac's RBAC)
def mask(value):
    return "•••" + hashlib.sha1(str(value).encode()).hexdigest()[:4] if value else value


def heat(day: str, n: int = 250000, area: str = "at") -> list:
    """Airborne traffic only: ground positions and stationary transmitters would dominate the density."""
    return _gold(day, f"heat_{area}_{n}", lambda: _heat(day, n, area))


def _heat(day: str, n: int, area: str) -> list:
    rows = con().sql(f"""SELECT lon, lat, alt FROM (SELECT lon, lat, coalesce(alt, 0) AS alt FROM {_p(day)}
                         WHERE {AT if area == "at" else IN_AT} AND alt > 0 AND coalesce(gs, 0) >= 40
                           AND icao NOT IN (SELECT icao FROM ({STATIONARY.format(src=_p(day))})))
                         USING SAMPLE {int(n)} ROWS""").fetchall()
    return [[round(a, 4), round(b, 4), c] for a, b, c in rows]


# ------------------------------------------------------------------ live helpers
_RINGS = None


def _rings():
    """All polygon rings of the Bundesländer (lon/lat) from the Statistik Austria GeoJSON, loaded once."""
    global _RINGS
    if _RINGS is None:
        import json
        import numpy as np
        from aviametrics.config import geo_dir
        cand = [p for p in geo_dir().glob("2021/**/*.json") if "laender" in p.name.lower() and "topo" not in str(p).lower()]
        rings = []
        if cand:
            g = json.loads(min(cand, key=lambda p: p.stat().st_size).read_text())
            for f in g["features"]:
                geom = f["geometry"]
                polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
                rings += [np.asarray(r, dtype=float)[:, :2] for poly in polys for r in poly]
        _RINGS = rings
    return _RINGS


def in_austria(lons: list, lats: list) -> set[int]:
    """Indices of points inside Austria's national border: ray-casting point-in-polygon (even-odd rule
    over all rings of all Bundesländer, so the Vienna hole in Lower Austria is handled correctly)."""
    import numpy as np
    x, y = np.asarray(lons, dtype=float), np.asarray(lats, dtype=float)
    cand = np.where((y >= LAT0) & (y <= LAT1) & (x >= LON0) & (x <= LON1))[0]
    rings = _rings()
    if not rings or len(cand) == 0:
        return set(cand.tolist()) if not rings else set()
    px, py = x[cand][:, None], y[cand][:, None]
    inside = np.zeros(len(cand), dtype=bool)
    for r in rings:
        xi, yi = r[:, 0][None, :], r[:, 1][None, :]
        xj, yj = np.roll(r[:, 0], 1)[None, :], np.roll(r[:, 1], 1)[None, :]
        cross = ((yi > py) != (yj > py)) & (px < (xj - xi) * (py - yi) / np.where(yj - yi == 0, 1e-12, yj - yi) + xi)
        inside ^= (cross.sum(axis=1) % 2 == 1)
    return set(cand[inside].tolist())
