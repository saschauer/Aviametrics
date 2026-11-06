"""Pipeline progress reporting: one small JSON file per day in DATA/logs, read by the API and shown live in the app."""
import json
import os
import time

from aviametrics.config import DATA

STAGES = ["download", "extract", "parse", "enrich", "write", "flights", "done"]


def path(day: str):
    return DATA / "logs" / f"{day}.progress.json"


def read(day: str) -> dict | None:
    try:
        return json.loads(path(day).read_text())
    except Exception:
        return None


def report(day: str, stage: str, pct: float | None = None, msg: str = "", status: str = "running"):
    p = path(day)
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = read(day) or {"day": day, "started": time.time(), "done_stages": []}
    if cur.get("stage") and cur["stage"] != stage and cur["stage"] not in cur["done_stages"]:
        cur["done_stages"].append(cur["stage"])
    cur.update(stage=stage, pct=pct, msg=msg, status=status, updated=time.time())
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur))
    os.replace(tmp, p)
