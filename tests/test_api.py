"""The FastAPI wiring. Skipped automatically when FastAPI is not installed."""

import json
import unittest

try:
    from fastapi.testclient import TestClient
    import app as app_module
    HAVE = True
except Exception:  # FastAPI/httpx not installed (for example in a bare sandbox)
    HAVE = False


@unittest.skipUnless(HAVE, "fastapi and httpx are not installed")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from praxis import web_core

        web_core.DEMO_STEP_DELAY = 0.0
        cls.client = TestClient(app_module.app)

    def test_health_and_config(self):
        self.assertEqual(self.client.get("/api/health").json(), {"ok": True})
        self.assertIn("providers", self.client.get("/api/config").json())

    def test_receipts_and_examples(self):
        self.assertEqual(len(self.client.get("/api/receipts").json()), 24)
        examples = self.client.get("/api/examples").json()
        self.assertEqual(len(examples), 4)
        self.assertEqual(self.client.get(f"/api/examples/{examples[0]['id']}").status_code, 200)
        self.assertEqual(self.client.get("/api/examples/..%2Fsecret").status_code, 404)

    def test_bad_run_request_is_400(self):
        self.assertEqual(self.client.post("/api/run", json={"provider": "nope"}).status_code, 400)

    def test_demo_run_streams_events(self):
        response = self.client.post("/api/run", json={"setup": "instructions"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        events = [b for b in response.text.split("\n\n") if b.startswith("event:")]
        self.assertTrue(events[0].startswith("event: start"))
        self.assertTrue(events[-1].startswith("event: result"))
        self.assertEqual(json.loads(events[-1].split("data: ", 1)[1])["record"]["check"]["score"], 7)

    def test_docs_pages_are_off(self):
        # A missing page is a plain 404 (FastAPI's 404 body is a small JSON message,
        # so we check the status and that no docs content came back).
        for path in ("/docs", "/redoc", "/openapi.json"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404)
            self.assertNotIn("swagger", response.text.lower())
            self.assertNotIn("openapi", response.text.lower())


if __name__ == "__main__":
    unittest.main()
