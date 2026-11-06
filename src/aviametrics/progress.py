"""Pipeline progress reporting: one small JSON file per day in DATA/logs, read by the API and shown live in the app."""
import json
import os
import time

from aviametrics.config import DATA

STAGES = ["download", "extract", "parse", "enrich", "write", "flights", "done"]


def path(day: str, run: str | None = None):
    run = run or os.environ.get("AVIA_RUN_ID", "")
    return DATA / "logs" / (f"{day}_{run}.progress.json" if run else f"{day}.progress.json")


def read(day: str, run: str | None = None) -> dict | None:
    try:
        return json.loads(path(day, run).read_text())
    except Exception:
        return None


def report(day: str, stage: str, pct: float | None = None, msg: str = "", status: str = "running", run: str | None = None):
    """Each pipeline run (attempt) has its own progress file, so earlier attempts stay in the history."""
    run = run or os.environ.get("AVIA_RUN_ID", "")
    p = path(day, run)
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = read(day, run) or {"day": day, "run": run, "started": time.time(), "done_stages": []}
    if cur.get("stage") and cur["stage"] != stage and cur["stage"] not in cur["done_stages"]:
        cur["done_stages"].append(cur["stage"])
    cur.update(stage=stage, pct=pct, msg=msg, status=status, updated=time.time())
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur))
    os.replace(tmp, p)
