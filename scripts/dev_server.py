"""Zero-install preview server: the same routes as app.py, built on Python's standard library.

    python scripts/dev_server.py        then open http://127.0.0.1:8000

Use it to try the page without installing FastAPI. It calls exactly the same functions
(praxis/web_core.py), so what you see here is what the FastAPI app serves.
"""

from __future__ import annotations

import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from praxis import web_core as core  # noqa: E402
from praxis.config import load_env  # noqa: E402

PUBLIC = ROOT / "public"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # keep the terminal quiet (and never print request bodies)
        pass

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        routes = {
            "/api/health": lambda: {"ok": True},
            "/api/config": core.public_config,
            "/api/examples": core.list_examples,
            "/api/receipts": core.receipts_listing,
            "/api/compare": core.compare_results,
        }
        if path in routes:
            return self._json(routes[path]())
        if path.startswith("/api/examples/"):
            found = core.get_example(path.rsplit("/", 1)[-1])
            return self._json(found, 200) if found else self._json({"detail": "No such saved run."}, 404)
        target = (PUBLIC / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if PUBLIC not in target.parents or not target.is_file():
            return self._json({"detail": "Not found"}, 404)
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urlparse(self.path).path != "/api/run":
            return self._json({"detail": "Not found"}, 404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            req = core.parse_run_request(json.loads(self.rfile.read(min(length, 100_000)) or b"{}"))
        except (ValueError, json.JSONDecodeError) as exc:
            return self._json({"detail": str(exc)}, 400)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for chunk in core.stream_run(req):
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def main(port: int = 8000) -> None:
    load_env()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Praxis preview on http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
