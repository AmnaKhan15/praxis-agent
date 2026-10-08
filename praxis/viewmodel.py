"""Small pure helpers that turn run data into what the screen (or terminal) shows.

They contain no web-framework code on purpose, so they can be unit tested and reused by
both the web app and the command line.
"""

from __future__ import annotations

import json

PLAN_ICON = {"done": "✓", "doing": "●", "todo": "○"}
LEVER_NAME = {
    "context": "Context",
    "workspace": "Workspace",
    "instructions": "Instructions",
    "other": "Other",
}


def latest_plan(steps: list[dict]) -> list[dict]:
    """The most recent plan the agent showed, or an empty list."""
    for step in reversed(steps):
        if step.get("type") == "plan":
            return step["items"]
    return []


def plan_progress(plan: list[dict]) -> tuple[int, int]:
    return sum(1 for item in plan if item["status"] == "done"), len(plan)


def short_args(name: str, args) -> str:
    """A compact one-line description of a tool call."""
    if not isinstance(args, dict):
        return str(args)[:80]
    if name == "write_rows":
        return f"{args.get('sheet')}, row {args.get('start_row')}, {len(args.get('rows') or [])} row(s)"
    if name == "write_cell":
        return f"{args.get('sheet')}!{args.get('cell')} = {args.get('value')}"
    if name in ("read_file", "list_files"):
        return str(args.get("path", ""))
    if name == "add_sheet":
        return str(args.get("name", ""))
    text = json.dumps(args, ensure_ascii=False)
    return text if len(text) <= 80 else text[:77] + "..."


def activity_rows(steps: list[dict]) -> list[dict]:
    """One display row per step: {n, kind, title, detail, ok}."""
    rows = []
    for step in steps:
        kind = step["type"]
        if kind == "assistant":
            rows.append({"n": step["n"], "kind": "think", "title": step["text"], "detail": "", "ok": True})
        elif kind == "tool":
            first_line = step["observation"].splitlines()[0] if step["observation"] else ""
            rows.append({
                "n": step["n"], "kind": "tool",
                "title": f"{step['name']}  {short_args(step['name'], step['args'])}",
                "detail": first_line[:160], "ok": step["ok"],
            })
        elif kind == "plan":
            done, total = plan_progress(step["items"])
            rows.append({"n": step["n"], "kind": "plan", "title": "Plan updated", "detail": f"{done} of {total} steps done", "ok": True})
        elif kind == "finish":
            rows.append({"n": step["n"], "kind": "finish", "title": "Finished", "detail": step["summary"], "ok": True})
        elif kind == "error":
            rows.append({"n": step["n"], "kind": "error", "title": "Run stopped", "detail": step["message"], "ok": False})
    return rows


def score_text(check: dict) -> str:
    return f"{check['score']} / {check['total']}"


def percent(check: dict) -> int:
    return round(100 * check["score"] / check["total"]) if check["total"] else 0


def hint_rows(hints: list[dict]) -> list[dict]:
    return [
        {"lever": LEVER_NAME.get(h["lever"], h["lever"].title()), "title": h["title"], "evidence": h["evidence"]}
        for h in hints
    ]


def compare_rows(results: dict) -> list[dict]:
    """Rows for the comparison table and chart."""
    return [
        {
            "Setup": row["label"],
            "Average score": row["avg_score"],
            "Out of": row["total"],
            "Tool calls": row["avg_tool_calls"],
            "Tokens": row["avg_tokens"],
            "Errored runs": row["errored_runs"],
        }
        for row in results["rows"]
    ]


def model_label(record_or_results: dict) -> str:
    """Name of the brain, with a DEMO marker for the scripted stand-in."""
    name = f"{record_or_results.get('provider', '?')} / {record_or_results.get('model', '?')}"
    return f"DEMO (scripted, not an AI): {name}" if record_or_results.get("demo") else name
