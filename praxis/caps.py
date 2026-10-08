"""A daily limit on live runs that spend the host's own API key.

A public demo with a free-tier key can be drained in minutes, so the web app counts
runs per day and falls back to replay mode when the limit is reached. Visitors who
paste their own key are not counted. The counter lives in a small file, so it resets
if the host wipes its disk (fine for a demo).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import DATA_DIR

USAGE_FILE = DATA_DIR / "usage.json"


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get("DAILY_RUN_CAP", "20")))
    except ValueError:
        return 20


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def runs_today(path: Path = USAGE_FILE) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return int(data.get("count", 0)) if data.get("date") == _today() else 0


def runs_left(path: Path = USAGE_FILE) -> int:
    return max(0, daily_cap() - runs_today(path))


def record_run(path: Path = USAGE_FILE) -> int:
    """Count one more run today and return the new total."""
    count = runs_today(path) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": _today(), "count": count}), encoding="utf-8")
    return count
