"""Source adapters: adsb.lol daily archive + live APIs with a fallback chain (ABA: graded fallback strategy)."""
import glob
import gzip
import json
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import orjson

from aviametrics import progress
from aviametrics.config import CFG, DATA, IMPORT_DATE, IMPORT_DIR, IMPORT_NAME

UA = {"User-Agent": "aviametrics/0.1 (TGM diploma project)"}


# ------------------------------------------------------------------ archive
def raw_day_dir(day: str) -> Path:
    """Return a directory with the extracted trace files of `day` (import if available, else download)."""
    if IMPORT_DATE == day and (IMPORT_DIR / IMPORT_NAME).is_dir():
        src = IMPORT_DIR / IMPORT_NAME
        y, m, d = day.split("-")
        parts = sorted(src.glob(f"v{y}.{m}.{d}-planes-readsb-*.tar.a?"))
        if not parts:                       # already extracted day folder
            return src
        target = DATA / "raw" / day         # downloaded archive parts: extract them
        target.mkdir(parents=True, exist_ok=True)
        progress.report(day, "extract", None, f"{len(parts)} parts")
        subprocess.run(f"cat {' '.join(map(str, parts))} | tar -x -C {target}", shell=True, check=True)
        return target
    target = DATA / "raw" / day
    if target.is_dir() and any(target.rglob("trace_full_*.json")):
        return target
    y, m, d = day.split("-")
    tmp = DATA / "raw" / f"{day}.parts"
    tmp.mkdir(parents=True, exist_ok=True)
    parts = []
    with httpx.Client(headers=UA, follow_redirects=True, timeout=120) as c:
        for variant in CFG["sources"].get("archive_variants", ["prod-0"]):   # fallback: prod-0 → prod-1 → staging
            for part in ["aa", "ab", "ac", "ad"]:
                url = CFG["sources"]["archive"].format(year=y, month=m, day=d, part=part, variant=variant)
                out = tmp / f"part.{part}"
                with c.stream("GET", url) as r:
                    if r.status_code != 200:
                        break
                    total, got, last = int(r.headers.get("content-length", 0)), 0, 0.0
                    with open(out, "wb") as fh:
                        for chunk in r.iter_bytes(1 << 20):
                            fh.write(chunk)
                            got += len(chunk)
                            if time.time() - last > 1:
                                last = time.time()
                                progress.report(day, "download", 100 * got / total if total else None,
                                                f"{variant} · Teil/part {part}: {got / 1e9:.2f} / {total / 1e9:.2f} GB")
                parts.append(out)
            if parts:
                break
    if not parts:
        progress.report(day, "download", None, f"no adsb.lol archive found for {day}", status="failed")
        raise RuntimeError(f"no adsb.lol archive found for {day}")
    target.mkdir(parents=True, exist_ok=True)
    progress.report(day, "extract", None, f"{len(parts)} parts")
    subprocess.run(f"cat {' '.join(map(str, parts))} | tar -x -C {target}", shell=True, check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return target


def trace_files(raw_dir: Path) -> list[str]:
    return glob.glob(str(raw_dir / "**" / "trace_full_*.json"), recursive=True)


def read_trace(path: str) -> dict | None:
    try:
        raw = open(path, "rb").read()
        return orjson.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    except Exception:
        return None


# ------------------------------------------------------------------ live (fallback chain)
_cache: dict = {"t": 0.0, "data": None}


def live_snapshot() -> dict:
    """Try each live API in order; then the last good snapshot; then recorded replays. Returns {ac, source, mode}."""
    if _cache["data"] and time.time() - _cache["t"] < CFG["sources"]["live_cache_seconds"]:
        return _cache["data"]
    lat, lon = CFG["area"]["center"]
    for url in CFG["sources"]["live"]:
        u = url.format(lat=lat, lon=lon, radius=CFG["area"]["live_radius_nm"])
        try:
            t0 = time.perf_counter()
            r = httpx.get(u, headers=UA, timeout=6)
            r.raise_for_status()
            latency = round((time.perf_counter() - t0) * 1000)
            d = r.json()
            data = {"ac": d.get("ac") or d.get("aircraft") or [], "source": u.split("/")[2], "mode": "live",
                    "latency_ms": latency, "bytes": len(r.content), "fetched_at": time.time()}
            _cache.update(t=time.time(), data=data)
            return data
        except Exception:
            continue
    if _cache["data"]:
        return {**_cache["data"], "mode": "cache"}
    snaps = sorted(glob.glob(str(DATA / "replay" / "*.json")))
    if snaps:
        i = int(time.time() / 10) % len(snaps)
        d = json.load(open(snaps[i]))
        return {"ac": d.get("ac") or [], "source": "recording", "mode": "replay"}
    return {"ac": [], "source": "none", "mode": "offline"}
