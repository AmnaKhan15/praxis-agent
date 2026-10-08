"""One complete run: fresh workspace -> agent -> checker -> diagnosis -> saved log."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .agent import run_agent
from .checker import check_workspace
from .config import GOAL, LOGS_DIR, SETUPS, build_config
from .diagnose import diagnose
from .receipts import load_answer_key
from .runlog import new_run_id, save_run
from .tools import Workspace


def label_for(context: bool, workspace: bool, instructions: bool) -> str:
    for setup in SETUPS:
        if (setup.context, setup.workspace, setup.instructions) == (context, workspace, instructions):
            return setup.label
    return "Custom levers"


def execute_run(
    client,
    context: bool,
    workspace: bool,
    instructions: bool,
    overrides: dict[str, str] | None = None,
    goal: str = GOAL,
    on_event: Callable[[dict], None] | None = None,
    save: bool = True,
    logs_dir: Path = LOGS_DIR,
    max_steps: int = 30,
    run_id: str | None = None,
    report_sink: list | None = None,
) -> dict:
    """Run the agent once in a brand-new sandbox and return the full record."""
    config = build_config(context, workspace, instructions, overrides)
    sandbox = Workspace.create()
    try:
        record = run_agent(client, config, sandbox, goal=goal, max_steps=max_steps, on_event=on_event)
        result = check_workspace(sandbox.root, load_answer_key())
        record.update(
            {
                "run_id": run_id or new_run_id(),
                "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "provider": client.provider,
                "model": client.model,
                "demo": bool(getattr(client, "is_demo", False)),
                "setup": {
                    "label": label_for(context, workspace, instructions),
                    "context": context,
                    "workspace": workspace,
                    "instructions": instructions,
                },
                "check": result.to_dict(),
                "hints": [h.to_dict() for h in diagnose(result, record["steps"])],
            }
        )
        if save:
            save_run(record, sandbox.report_path, logs_dir)
        if report_sink is not None and sandbox.report_path.exists():
            report_sink.append(sandbox.report_path.read_bytes())  # the web API sends the file back
        return record
    finally:
        sandbox.cleanup()
