"""One structured log line per run, so you can see how the agent behaves over time.

Each line is a single JSON object written to the server's output. On Vercel it shows up in the
project's Logs tab, where it can be searched and filtered.

What is logged: the run id, provider, model, setup, score, which checks failed, step and token counts,
how long it took, how it ended.
What is NEVER logged: API keys, receipt text, what the agent wrote, or the visitor's edited lever text.
"""

from __future__ import annotations

import json
import logging
import sys

logger = logging.getLogger("praxis.run")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

MAX_ERROR_CHARS = 200


def _clean(text: str | None, secrets: tuple[str, ...] = ()) -> str | None:
    """Shorten an error message and make sure no key can slip into the log."""
    if not text:
        return None
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text.replace("\n", " ")[:MAX_ERROR_CHARS]


def run_summary(record: dict, key_source: str, secrets: tuple[str, ...] = ()) -> dict:
    """The safe, numbers-only summary of a finished run."""
    steps = record.get("steps", [])
    tools = [s for s in steps if s.get("type") == "tool"]
    check = record["check"]
    return {
        "event": "run",
        "run_id": record.get("run_id"),
        "provider": record.get("provider"),
        "model": record.get("model"),
        "demo": bool(record.get("demo")),
        "key_source": key_source,  # "demo", "host" or "visitor", never the key itself
        "setup": record["setup"]["label"],
        "score": check["score"],
        "total": check["total"],
        "failed_checks": [c["id"] for c in check["checks"] if not c["passed"]],
        "tool_calls": len(tools),
        "tool_errors": sum(1 for s in tools if not s.get("ok")),
        "tokens_in": record.get("tokens_in", 0),
        "tokens_out": record.get("tokens_out", 0),
        "seconds": record.get("seconds"),
        "stop_reason": record.get("stop_reason"),
        "finished": bool(record.get("finished")),
        "error": _clean(record.get("error"), secrets),
    }


def log_run(record: dict, key_source: str, secrets: tuple[str, ...] = ()) -> dict:
    summary = run_summary(record, key_source, secrets)
    logger.info(json.dumps(summary, ensure_ascii=False))
    return summary


def log_failure(provider: str, key_source: str, reason: str, secrets: tuple[str, ...] = ()) -> dict:
    """A run that never produced a record (no key, daily cap reached, crash)."""
    summary = {"event": "run_failed", "provider": provider, "key_source": key_source, "reason": _clean(reason, secrets)}
    logger.info(json.dumps(summary, ensure_ascii=False))
    return summary
