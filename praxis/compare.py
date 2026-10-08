"""Run every setup several times and save a results table.

This is the experiment behind the README table: same agent, same data, one lever
added at a time. Averages over several runs matter because models vary run to run.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import RESULTS_DIR, SETUPS, Setup
from .pipeline import execute_run


def run_matrix(
    client_factory: Callable[[], object],
    runs_per_setup: int,
    setups: list[Setup] = SETUPS,
    progress: Callable[[str], None] | None = None,
    save_logs: bool = False,
) -> dict:
    """Run each setup `runs_per_setup` times. `client_factory` builds a fresh client per run."""
    rows, provider, model, demo = [], "", "", False
    for setup in setups:
        scores, steps, tokens, errored, total = [], [], [], 0, 7
        for index in range(runs_per_setup):
            client = client_factory()
            provider, model, demo = client.provider, client.model, bool(getattr(client, "is_demo", False))
            record = execute_run(client, setup.context, setup.workspace, setup.instructions, save=save_logs)
            scores.append(record["check"]["score"])
            total = record["check"]["total"]
            steps.append(sum(1 for s in record["steps"] if s["type"] == "tool"))
            tokens.append(record["tokens_in"] + record["tokens_out"])
            errored += 1 if record["error"] else 0
            if progress:
                progress(f"{setup.label}: run {index + 1}/{runs_per_setup} scored {scores[-1]}/{total}")
        count = len(scores)
        rows.append(
            {
                "setup": setup.name,
                "label": setup.label,
                "scores": scores,
                "avg_score": round(sum(scores) / count, 2),
                "total": total,
                "avg_tool_calls": round(sum(steps) / count, 1),
                "avg_tokens": round(sum(tokens) / count),
                "errored_runs": errored,
            }
        )
    return {
        "provider": provider,
        "model": model,
        "demo": demo,
        "runs_per_setup": runs_per_setup,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": rows,
    }


def save_results(results: dict, results_dir: Path = RESULTS_DIR, name: str | None = None) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    if name is None:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{results['provider']}_{results['model']}")
        name = f"compare_{safe}.json"
    path = results_dir / name
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return path


def load_results(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def list_result_files(results_dir: Path = RESULTS_DIR) -> list[Path]:
    return sorted(results_dir.glob("*.json")) if results_dir.exists() else []
