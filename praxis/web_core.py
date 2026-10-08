"""Everything the web API does, written without any web framework.

`app.py` (FastAPI) and `scripts/dev_server.py` (standard library) are thin wrappers around
these functions, so the real logic can be unit tested with no extra installs.

Safety rules, in one place:
- Only the built-in receipts and goal are ever used (no uploads, no free-text goal).
- A visitor's API key is used for that one run. It is never stored or logged.
- Runs on the host's own key are counted against a daily cap (best effort on serverless hosts).
- Nothing is written to the project folder: runs are not saved, the report is sent back.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import re
import tempfile
import threading
from pathlib import Path
from typing import Callable, Iterator

from . import caps
from .compare import list_result_files, load_results
from .config import GOAL, LOGS_DIR, RECEIPTS_SRC, SETUPS, lever_texts
from .demo_model import DemoClient
from . import observe
from .llm import PROVIDERS, LLMError, default_model, make_client, server_key_available
from .pipeline import execute_run, label_for
from .runlog import load_run

OVERRIDE_KEYS = ("context", "instructions_clear")
MAX_TEXT = 4000
KEY_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{8,200}$")
EXAMPLE_ID = re.compile(r"^example_[a-z0-9_]+$")
KEEPALIVE_SECONDS = 8
DEMO_STEP_DELAY = 0.25  # so the scripted demo is pleasant to watch


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def sse(event: str, data) -> str:
    """One Server-Sent Event, ready to write to the response."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def usage_path() -> Path:
    """Where the daily counter lives. Serverless hosts only allow writes to the temp folder."""
    if os.environ.get("VERCEL"):
        return Path(tempfile.gettempdir()) / "praxis_usage.json"
    return caps.USAGE_FILE


def _b64(data: bytes | None) -> str | None:
    return base64.b64encode(data).decode("ascii") if data else None


# ---------------------------------------------------------------------------
# Read-only data for the page
# ---------------------------------------------------------------------------
def public_config() -> dict:
    providers = [
        {
            "id": pid,
            "label": info["label"],
            "default_model": default_model(pid),
            "server_key": server_key_available(pid),
        }
        for pid, info in PROVIDERS.items()
    ]
    host_has_key = any(p["server_key"] for p in providers)
    return {
        "goal": GOAL,
        "providers": providers,
        "setups": [
            {"name": s.name, "label": s.label, "context": s.context, "workspace": s.workspace, "instructions": s.instructions}
            for s in SETUPS
        ],
        "levers": {"context": lever_texts()["context"], "instructions_clear": lever_texts()["instructions_clear"]},
        "runs_left": caps.runs_left(usage_path()) if host_has_key else None,
        "daily_cap": caps.daily_cap() if host_has_key else None,
    }


def list_examples(logs_dir: Path = LOGS_DIR) -> list[dict]:
    out = []
    for setup in SETUPS:
        path = logs_dir / f"example_demo_{setup.name}.json"
        if path.exists():
            record = load_run(path)
            out.append({
                "id": path.stem,
                "label": record["setup"]["label"],
                "score": record["check"]["score"],
                "total": record["check"]["total"],
                "demo": bool(record.get("demo")),
            })
    return out


def get_example(example_id: str, logs_dir: Path = LOGS_DIR) -> dict | None:
    """A saved run for replay. The id is checked against a strict pattern first."""
    if not EXAMPLE_ID.match(example_id or ""):
        return None
    path = logs_dir / f"{example_id}.json"
    if not path.exists():
        return None
    record = load_run(path)
    report = logs_dir / f"{example_id}_expense_report.xlsx"
    return {"record": record, "report_b64": _b64(report.read_bytes() if report.exists() else None)}


def receipts_listing(src: Path = RECEIPTS_SRC) -> list[dict]:
    if not src.exists():
        return []
    return [{"name": p.name, "text": p.read_text(encoding="utf-8")} for p in sorted(src.iterdir()) if p.is_file()]


def compare_results() -> list[dict]:
    return [{"name": p.name, "results": load_results(p)} for p in list_result_files()]


# ---------------------------------------------------------------------------
# Running the agent
# ---------------------------------------------------------------------------
def parse_run_request(payload: dict) -> dict:
    """Check what the browser sent. Raises ValueError with a plain message."""
    if not isinstance(payload, dict):
        raise ValueError("The request must be a JSON object.")
    provider = str(payload.get("provider") or "demo").lower()
    if provider != "demo" and provider not in PROVIDERS:
        raise ValueError(f"Unknown provider '{provider}'.")

    if payload.get("setup"):
        names = {s.name: s for s in SETUPS}
        if payload["setup"] not in names:
            raise ValueError("Unknown setup.")
        chosen = names[payload["setup"]]
        flags = (chosen.context, chosen.workspace, chosen.instructions)
    else:
        flags = tuple(bool(payload.get(k)) for k in ("context", "workspace", "instructions"))

    model = payload.get("model")
    if model is not None:
        model = str(model).strip()
        if len(model) > 80 or not re.match(r"^[A-Za-z0-9._:/\-]*$", model):
            raise ValueError("That model name looks wrong.")
        model = model or None

    api_key = payload.get("api_key")
    if api_key:
        api_key = str(api_key).strip()
        if not KEY_PATTERN.match(api_key):
            raise ValueError("That API key has characters a key should not have.")
    else:
        api_key = None

    overrides = {}
    for key, value in (payload.get("overrides") or {}).items():
        if key not in OVERRIDE_KEYS:
            raise ValueError(f"Cannot change '{key}'.")
        if not isinstance(value, str) or len(value) > MAX_TEXT:
            raise ValueError(f"The text for '{key}' is too long.")
        overrides[key] = value

    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "context": flags[0],
        "workspace": flags[1],
        "instructions": flags[2],
        "overrides": overrides,
    }


def pick_client(req: dict, path: Path | None = None):
    """Choose the brain for this run and count it if it spends the host's key."""
    path = path or usage_path()
    if req["provider"] == "demo":
        return DemoClient(delay=DEMO_STEP_DELAY)
    if req["api_key"]:
        return make_client(req["provider"], api_key=req["api_key"], model=req["model"])
    if server_key_available(req["provider"]):
        if caps.runs_left(path) <= 0:
            raise LLMError("The host's daily limit is used up. Paste your own key, or replay a saved run.")
        caps.record_run(path)
        return make_client(req["provider"], model=req["model"])
    raise LLMError("Paste an API key to run live. A free Gemini key: aistudio.google.com/apikey")


def stream_run(req: dict, client_factory: Callable[[dict], object] = pick_client) -> Iterator[str]:
    """Run the agent in a worker thread and yield its steps as Server-Sent Events."""
    key_source = "demo" if req["provider"] == "demo" else ("visitor" if req["api_key"] else "host")
    secrets = (req["api_key"] or "",)
    try:
        client = client_factory(req)
    except LLMError as exc:
        observe.log_failure(req["provider"], key_source, str(exc), secrets)
        yield sse("error", {"message": str(exc)})
        return

    events: queue.Queue = queue.Queue()
    sink: list[bytes] = []

    def work() -> None:
        try:
            record = execute_run(
                client, req["context"], req["workspace"], req["instructions"],
                overrides=req["overrides"] or None,
                on_event=lambda step: events.put(("step", step)),
                save=False, report_sink=sink,
            )
            observe.log_run(record, key_source, secrets)
            events.put(("result", {"record": record, "report_b64": _b64(sink[0] if sink else None)}))
        except LLMError as exc:
            observe.log_failure(req["provider"], key_source, str(exc), secrets)
            events.put(("error", {"message": str(exc)}))
        except Exception as exc:  # never leak internals (or keys) to the visitor
            observe.log_failure(req["provider"], key_source, f"crash: {type(exc).__name__}", secrets)
            events.put(("error", {"message": "Something went wrong inside the run. Try again."}))
        finally:
            events.put(("end", None))

    yield sse("start", {
        "provider": client.provider,
        "model": client.model,
        "demo": bool(getattr(client, "is_demo", False)),
        "setup": label_for(req["context"], req["workspace"], req["instructions"]),
    })
    threading.Thread(target=work, daemon=True).start()
    while True:
        try:
            kind, data = events.get(timeout=KEEPALIVE_SECONDS)
        except queue.Empty:
            yield ": keepalive\n\n"  # keeps the connection open during slow model calls
            continue
        if kind == "end":
            return
        yield sse(kind, data)
