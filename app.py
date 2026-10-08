"""Praxis web API (FastAPI). Vercel finds the `app` object in this file.

All the logic lives in praxis/web_core.py. This file only connects it to web routes.
The page itself is plain HTML, CSS and JavaScript in public/ (Vercel serves it from its CDN).

Run it locally:   pip install -r requirements-dev.txt
                  uvicorn app:app --reload        then open http://127.0.0.1:8000
No installs?      python scripts/dev_server.py     (same routes, standard library only)
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from praxis import web_core as core
from praxis.config import load_env

load_env()

# The interactive docs pages are switched off: nobody needs them on a public demo.
app = FastAPI(title="Praxis", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    return core.public_config()


@app.get("/api/examples")
def examples():
    return core.list_examples()


@app.get("/api/examples/{example_id}")
def example(example_id: str):
    found = core.get_example(example_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such saved run.")
    return found


@app.get("/api/receipts")
def receipts():
    return core.receipts_listing()


@app.get("/api/compare")
def compare():
    return core.compare_results()


@app.post("/api/run")
def run(payload: dict = Body(...)):
    """Start one agent run and stream its steps back as Server-Sent Events."""
    try:
        req = core.parse_run_request(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return StreamingResponse(
        core.stream_run(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


# On your own computer, serve the page too. On Vercel the platform serves public/ itself.
if not os.environ.get("VERCEL"):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(Path(__file__).parent / "public"), html=True), name="public")
