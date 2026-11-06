"""Aviametrics API (plugin system v1). Docs: http://localhost:8000/docs"""
import os
import re
import time
import subprocess
from datetime import date
from typing import Literal

import pyarrow as pa
import pyarrow.compute as pc
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Response

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from aviametrics.config import BBOX, DATA, HOST_HOME, ROOT, to_container
from aviametrics.sources.adsblol import read_trace
from aviametrics import progress
from aviametrics.query import repository as repo
from aviametrics.sources.adsblol import live_snapshot

app = FastAPI(title="Aviametrics API", version="0.1.0",
              description="Plugin interface of Aviametrics (showcase). Role header `X-Role: visitor|analyst` "
                          "demonstrates data masking (visitor: military aircraft and registrations masked).")
Role = Literal["visitor", "analyst"]
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"], allow_methods=["GET"])


def _arrow_or_json(tbl: pa.Table, fmt: str):
    if fmt == "arrow":
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, tbl.schema) as w:
            w.write_table(tbl)
        return Response(sink.getvalue().to_pybytes(), media_type="application/vnd.apache.arrow.stream")
    return tbl.to_pylist()


def _mask_table(tbl: pa.Table, role: str) -> pa.Table:
    if role == "analyst" or tbl.num_rows == 0:
        return tbl
    mil = tbl.column("mil").to_pylist()
    for col in ("icao", "reg"):
        if col in tbl.column_names:
            vals = [repo.mask(v) if (m or col == "reg") else v for v, m in zip(tbl.column(col).to_pylist(), mil)]
            tbl = tbl.set_column(tbl.column_names.index(col), col, pa.array(vals, pa.string()))
    if "type" in tbl.column_names:
        t = [("MIL" if m else v) for v, m in zip(tbl.column("type").to_pylist(), mil)]
        tbl = tbl.set_column(tbl.column_names.index("type"), "type", pa.array(t, pa.string()))
    return tbl


def _day(day: str) -> str:
    if day not in repo.days():
        raise HTTPException(404, f"day {day} not available – load it via POST /v1/days/{day}")
    return day


@app.get("/v1/health")
def health():
    return {"status": "ok", "days": repo.days()}


@app.get("/v1/live", summary="Current aircraft around Austria (fallback chain of live sources)")
def live(x_role: Role = Header("visitor")):
    snap = live_snapshot()
    out = []
    for a in snap["ac"]:
        if a.get("lat") is None or a.get("lon") is None:
            continue
        mil = bool((a.get("dbFlags") or 0) & 1)
        alt = a.get("alt_baro")
        rec = {"icao": a.get("hex"), "flight": (a.get("flight") or "").strip(), "reg": a.get("r"), "type": a.get("t"),
               "lat": a["lat"], "lon": a["lon"], "alt": alt if isinstance(alt, (int, float)) else 0,
               "gs": a.get("gs"), "track": a.get("track"), "mil": mil}
        if x_role != "analyst":
            rec["reg"] = repo.mask(rec["reg"])
            if mil:
                rec.update(icao=repo.mask(rec["icao"]), flight="MIL", type="MIL")
        out.append(rec)
    try:
        inside = repo.in_austria([r["lon"] for r in out], [r["lat"] for r in out])
    except Exception as e:  # never silently: log and fall back to the bounding box
        import logging
        logging.getLogger("uvicorn.error").exception("Austria polygon test failed: %s", e)
        la0, la1, lo0, lo1 = BBOX
        inside = {i for i, r in enumerate(out) if la0 <= r["lat"] <= la1 and lo0 <= r["lon"] <= lo1}
    for i, r in enumerate(out):
        r["in_at"] = i in inside
    return {"source": snap["source"], "mode": snap["mode"], "aircraft": out, "bbox_core": BBOX,
            "latency_ms": snap.get("latency_ms"), "bytes": snap.get("bytes"), "fetched_at": snap.get("fetched_at")}


@app.get("/v1/days", summary="Days available in storage")
def days():
    return repo.days()


_jobs: dict = {}


import threading
_queue_lock = threading.Lock()   # one pipeline run at a time – further days wait in the queue


def _run_pipeline(day: str, source: str | None = None, run: str = ""):
    with _queue_lock:
        _run_pipeline_locked(day, source, run)


def _run_pipeline_locked(day: str, source: str | None = None, run: str = ""):
    log = DATA / "logs" / f"{day}_{run}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "DAGSTER_HOME": os.environ.get("DAGSTER_HOME", str(DATA / "dagster_home")), "AVIA_RUN_ID": run}
    progress.report(day, "download", 0, "", run=run)
    if source:  # import an existing extracted day instead of downloading
        src = to_container(source)
        env.update(AVIA_IMPORT_DIR=str(src.parent), AVIA_IMPORT_NAME=src.name, AVIA_IMPORT_DATE=day)
    os.makedirs(env["DAGSTER_HOME"], exist_ok=True)
    with open(log, "w") as fh:
        r = subprocess.run(["dagster", "asset", "materialize", "-m", "aviametrics.pipeline.definitions",
                            "--select", "*", "--partition", day], stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT, env=env)
    _jobs[day] = "done" if r.returncode == 0 else "failed"
    cur = progress.read(day, run) or {}
    if r.returncode == 0:
        progress.report(day, "done", 100, "ok", status="done", run=run)
    elif cur.get("status") != "failed":   # the pipeline did not report its own error: take the most specific log line
        lines = [l for l in log.read_text().splitlines() if l.strip()]
        err = next((l for l in reversed(lines) if re.search(r"\w+(Error|Exception):", l) and "Materialization" not in l),
                   lines[-1] if lines else "unknown error")
        progress.report(day, cur.get("stage", "download"), None, err.strip()[-300:], status="failed", run=run)


@app.post("/v1/days/{day}", summary="Load a day: runs the Dagster pipeline (download or import → positions → flights)")
def load_day(day: date, bg: BackgroundTasks, source: str | None = None):
    d = day.isoformat()
    if _jobs.get(d) == "running":
        return {"day": d, "status": "running"}
    _jobs[d] = "running"
    run = time.strftime("%Y%m%d-%H%M%S")
    progress.report(d, "download", 0, "queued", status="queued", run=run)
    bg.add_task(_run_pipeline, d, source, run)
    return {"day": d, "status": "started"}


@app.get("/v1/days/{day}/status")
def day_status(day: str):
    log = DATA / "logs" / f"{day}.log"
    tail = log.read_text().strip().splitlines()[-1][-160:] if log.exists() and log.stat().st_size else ""
    return {"day": day, "status": "ready" if day in repo.days() else _jobs.get(day, "unknown"), "log": tail}


@app.get("/v1/stats/{day}", summary="Key figures, hourly traffic, aircraft types, Bundesländer, fun facts")
def stats(day: str):
    d = _day(day)
    return {"kpis": repo.kpis(d), "hourly": repo.hourly(d), "types": repo.types(d), "regions": repo.regions(d), "facts": repo.facts(d)}


@app.get("/v1/trips/{day}", summary="Downsampled trajectories for animation")
def trips(day: str, step_s: int = 30, x_role: Role = Header("visitor")):
    data = repo.trips(_day(day), step_s)
    return data


@app.get("/v1/positions/{day}", summary="Positions (plugin data access) as JSON or Arrow IPC")
def positions(day: str, start: int | None = None, end: int | None = None, fmt: Literal["json", "arrow"] = "arrow",
              x_role: Role = Header("visitor")):
    return _arrow_or_json(_mask_table(repo.positions(_day(day), start, end), x_role), fmt)


@app.get("/v1/flights/{day}", summary="Flight segments (gap > 10 min = new flight) as JSON or Arrow IPC")
def flights(day: str, fmt: Literal["json", "arrow"] = "json", x_role: Role = Header("visitor")):
    return _arrow_or_json(_mask_table(repo.flights(_day(day)), x_role), fmt)


# ------------------------------------------------------------------ data manager (settings + folder auto-detection)
SETTINGS = DATA / "settings.json"


class Settings(BaseModel):
    folders: list[str] = []


def _settings() -> Settings:
    try:
        return Settings(**json.loads(SETTINGS.read_text()))
    except Exception:
        return Settings()


@app.get("/v1/settings")
def get_settings():
    return {**_settings().model_dump(), "data_dir": os.environ.get("AVIA_DATA_DIR_HOST", str(DATA)), "host_home": HOST_HOME}


@app.put("/v1/settings")
def put_settings(s: Settings):
    SETTINGS.write_text(json.dumps(s.model_dump(), indent=1))
    return s


import re as _re
TAR_RE = _re.compile(r"v(\d{4})\.(\d{2})\.(\d{2})-planes-readsb-[\w-]+\.tar\.aa$")
MIN_TRACES = 20000


def _inspect(d: Path, host: str) -> list[dict]:
    """Recognise the two accepted inputs in folder d: adsb.lol archive parts (.tar.aa/.ab) or an extracted day (traces/)."""
    out, loaded = [], set(repo.days())
    for f in sorted(d.glob("*.tar.aa")):
        m = TAR_RE.match(f.name)
        if m:
            day = "-".join(m.groups())
            parts = sorted(d.glob(f.name[:-2] + "a?"))
            out.append({"folder": host, "day": day, "kind": "archive", "loaded": day in loaded,
                        "valid": len(parts) >= 2, "note": f"{len(parts)} parts, {sum(p.stat().st_size for p in parts) / 1e9:.1f} GB"})
    if (d / "traces").is_dir():
        files = list((d / "traces").glob("*/trace_full_*.json"))
        tr = read_trace(str(files[0])) if files else None
        ok = bool(tr and "icao" in tr and "trace" in tr and "timestamp" in tr)
        day = datetime.fromtimestamp(tr["timestamp"], timezone.utc).date().isoformat() if ok else None
        note = f"{len(files):,} trace files"
        if ok and len(files) < MIN_TRACES:
            note += " – incomplete?"
        out.append({"folder": host, "day": day, "kind": "extracted", "loaded": day in loaded,
                    "valid": ok, "note": note if ok else "traces/ found, but files are not adsb.lol/readsb traces"})
    return out


@app.get("/v1/scan_path", summary="Scan one folder (and sub-folders up to 3 levels) for adsb.lol days")
def scan_path(path: str, max_depth: int = 3):
    home = HOST_HOME or os.path.expanduser("~")
    host = home + path[1:] if path.startswith("~") else path
    root = to_container(host)
    if not root.is_dir():
        return [{"folder": path, "error": "folder not found"}]
    found, stack = [], [(root, 0)]
    while stack:
        d, depth = stack.pop()
        found += _inspect(d, host.rstrip("/") + str(d)[len(str(root)):])
        if depth < max_depth and not (d / "traces").is_dir():
            try:
                stack += [(c, depth + 1) for c in d.iterdir() if c.is_dir() and not c.name.startswith(".")
                          and c.name not in {"node_modules", ".venv", "venv", "aviametrics-data", "traces", "heatmap"}]
            except PermissionError:
                pass
    return sorted(found, key=lambda r: r.get("day") or "")


@app.get("/v1/browse", summary="List sub-folders for the folder picker (read-only, inside the user's home)")
def browse(path: str = "~"):
    home = HOST_HOME or os.path.expanduser("~")
    host = os.path.expanduser(path) if not HOST_HOME else (home + path[1:] if path.startswith("~") else path)
    if not host.startswith(home):
        host = home
    p = to_container(host)
    try:
        subs = sorted(c.name for c in p.iterdir() if c.is_dir() and not c.name.startswith("."))
    except Exception:
        subs = []
    rel = "~" + host[len(home):]
    return {"path": rel or "~", "parent": "~" + os.path.dirname(host)[len(home):] if host != home else None,
            "folders": subs, "is_adsblol_day": (p / "traces").is_dir() or any(p.glob("*.tar.aa"))}


@app.get("/v1/jobs", summary="Progress of pipeline runs (newest first)")
def jobs():
    out = []
    for f in sorted((DATA / "logs").glob("*.progress.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]:
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            pass
    return {"stages": progress.STAGES, "jobs": out}


@app.get("/v1/heat/{day}", summary="Sampled positions for density maps")
def heat(day: str, n: int = 250000):
    return repo.heat(_day(day), n)


@app.get("/v1/pick_folder", summary="Open the native folder dialog on the user's computer (via the host helper)")
def pick_folder(start: str = "~"):
    import httpx
    url, token = os.environ.get("AVIA_PICKER_URL", ""), os.environ.get("AVIA_PICKER_TOKEN", "")
    if not url or not token:
        return {"error": "folder dialog helper not running (start with ./start.sh; install zenity)"}
    try:
        return httpx.get(f"{url}/pick", params={"token": token, "start": start}, timeout=600).json()
    except Exception as e:
        return {"error": f"folder dialog helper not reachable: {e}"}
