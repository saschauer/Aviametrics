"""Repository: the ONLY module that knows the storage engine (DuckDB on Parquet).
Swapping the engine (e.g. ClickHouse) means re-implementing these functions – the API and app stay unchanged."""
import hashlib
import threading

from aviametrics import storage
from aviametrics.config import BBOX, GAP

_local = threading.local()
LAT0, LAT1, LON0, LON1 = BBOX
IN_AT = f"lat BETWEEN {LAT0} AND {LAT1} AND lon BETWEEN {LON0} AND {LON1}"
HAV = ("2*6371*asin(sqrt(pow(sin(radians(lat-plat)/2),2)+cos(radians(plat))*cos(radians(lat))"
       "*pow(sin(radians(lon-plon)/2),2)))")


def con():
    if not hasattr(_local, "c"):
        _local.c = storage.connect()
    return _local.c


def days() -> list[str]:
    return storage.days(con())


def _p(day):
    return storage.src("positions", day)


def _f(day):
    return storage.src("flights", day)


def kpis(day: str) -> dict:
    n_pos, n_ac = con().execute(f"SELECT count(*), count(DISTINCT icao) FROM {_p(day)} WHERE {IN_AT}").fetchone()
    km = con().execute(f"""SELECT sum({HAV}) FROM (SELECT lat, lon, lag(lat) OVER w plat, lag(lon) OVER w plon, ts - lag(ts) OVER w gap
                       FROM {_p(day)} WINDOW w AS (PARTITION BY icao ORDER BY ts)) WHERE gap <= {GAP} AND {IN_AT}""").fetchone()[0]
    segs = con().execute(f"SELECT count(*) FROM {_f(day)}").fetchone()[0] if storage.has(con(), "flights", day) else None
    return {"positions": n_pos, "aircraft": n_ac, "flights": segs, "km": round(km or 0)}


def hourly(day: str, utc_offset_h: int = 1) -> list[dict]:
    return storage.to_records(con().sql(f"""SELECT ((ts + {utc_offset_h * 3600}) % 86400) // 3600 AS hour, count(DISTINCT icao) AS aircraft
                         FROM {_p(day)} WHERE {IN_AT} GROUP BY 1 ORDER BY 1"""))


def types(day: str, limit: int = 12) -> list[dict]:
    return storage.to_records(con().sql(f"""SELECT coalesce(type, '?') AS type, count(DISTINCT icao) AS aircraft FROM {_p(day)}
                         WHERE {IN_AT} AND NOT mil GROUP BY 1 ORDER BY 2 DESC LIMIT {limit}"""))


def regions(day: str) -> list[dict]:
    return storage.to_records(con().sql(f"""SELECT bl AS region, count(DISTINCT icao) AS aircraft, round(sum({HAV})) AS km FROM (
                           SELECT bl, icao, lat, lon, lag(lat) OVER w plat, lag(lon) OVER w plon, ts - lag(ts) OVER w gap
                           FROM {_p(day)} WINDOW w AS (PARTITION BY icao ORDER BY ts))
                         WHERE bl IS NOT NULL AND gap <= {GAP} GROUP BY 1 ORDER BY 3 DESC"""))


def facts(day: str) -> dict:
    out = {}
    if storage.has(con(), "flights", day):
        r = con().execute(f"SELECT coalesce(type,'?'), km, t_end - t_start FROM {_f(day)} WHERE NOT mil ORDER BY km DESC LIMIT 1").fetchone()
        if r:
            out["longest_flight"] = {"type": r[0], "km": r[1], "minutes": round(r[2] / 60)}
    r = con().execute(f"SELECT ts // 60 AS m, count(DISTINCT icao) n FROM {_p(day)} WHERE {IN_AT} GROUP BY 1 ORDER BY 2 DESC LIMIT 1").fetchone()
    if r:
        out["busiest_minute"] = {"utc_minute_of_day": int(r[0] % 1440), "aircraft": r[1]}
    r = con().execute(f"SELECT coalesce(type,'?'), max(alt) FROM {_p(day)} WHERE {IN_AT} AND NOT mil GROUP BY 1 ORDER BY 2 DESC LIMIT 1").fetchone()
    if r:
        out["highest"] = {"type": r[0], "alt_ft": r[1]}
    return out


def trips(day: str, step_s: int = 30) -> dict:
    """Downsampled trajectories for the time-travel animation (seconds since local midnight)."""
    t0 = con().execute(f"SELECT min(ts) - (min(ts) + 3600) % 86400 FROM {_p(day)}").fetchone()[0]
    rows = con().sql(f"""SELECT icao, bool_or(mil) AS mil, list([lon, lat] ORDER BY ts) AS path,
                                list(ts - {t0} ORDER BY ts) AS t, list(coalesce(alt, 0) ORDER BY ts) AS alt
                         FROM (SELECT * FROM {_p(day)} QUALIFY row_number() OVER (PARTITION BY icao, ts // {step_s} ORDER BY ts) = 1)
                         GROUP BY icao HAVING count(*) > 2""").fetchall()
    return {"t0": t0, "trips": [{"mil": r[1], "path": [[round(x, 4), round(y, 4)] for x, y in r[2]], "t": list(r[3]),
                                 "alt": list(r[4])} for r in rows]}


def positions(day: str, start: int | None = None, end: int | None = None, bbox: list[float] | None = None):
    """Arrow table of positions – the plugin data access."""
    w = [IN_AT if bbox is None else f"lat BETWEEN {bbox[0]} AND {bbox[1]} AND lon BETWEEN {bbox[2]} AND {bbox[3]}"]
    if start:
        w.append(f"ts >= {int(start)}")
    if end:
        w.append(f"ts <= {int(end)}")
    return storage.to_arrow(con().sql(f"SELECT * FROM {_p(day)} WHERE {' AND '.join(w)} ORDER BY icao, ts"))


def flights(day: str):
    return storage.to_arrow(con().sql(f"SELECT * FROM {_f(day)}"))


# ------------------------------------------------------------------ masking (concept of Isaac's RBAC)
def mask(value):
    return "•••" + hashlib.sha1(str(value).encode()).hexdigest()[:4] if value else value
