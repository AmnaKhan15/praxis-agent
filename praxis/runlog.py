"""Saving and loading runs (the trajectory, the checks and the finished report)."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import LOGS_DIR


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:4]}"


def save_run(record: dict, report_path: Path | None = None, logs_dir: Path = LOGS_DIR) -> Path:
    """Write the run as JSON, and keep a copy of the finished report next to it."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    if report_path and Path(report_path).exists():
        report_name = f"{record['run_id']}_expense_report.xlsx"
        shutil.copy(report_path, logs_dir / report_name)
        record["report_file"] = report_name
    path = logs_dir / f"{record['run_id']}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_run(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def list_runs(logs_dir: Path = LOGS_DIR) -> list[Path]:
    """All saved runs, newest first (example runs sort by name)."""
    if not logs_dir.exists():
        return []
    return sorted(logs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def report_bytes(record: dict, logs_dir: Path = LOGS_DIR) -> bytes | None:
    """The finished spreadsheet of a saved run, if one was kept."""
    name = record.get("report_file")
    path = logs_dir / name if name else None
    return path.read_bytes() if path and path.exists() else None
