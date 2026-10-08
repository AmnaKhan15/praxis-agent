"""The run log must be useful and must never contain secrets or receipt content."""

import json
import unittest

from praxis import observe, web_core as core
from praxis.demo_model import DemoClient
from praxis.pipeline import execute_run


def sample_record():
    return execute_run(DemoClient(), True, True, True, save=False)


class SummaryTests(unittest.TestCase):
    def test_summary_has_the_useful_numbers(self):
        s = observe.run_summary(sample_record(), "demo")
        self.assertEqual((s["event"], s["score"], s["total"], s["failed_checks"]), ("run", 7, 7, []))
        self.assertGreater(s["tool_calls"], 20)
        self.assertEqual(s["stop_reason"], "finished")

    def test_failed_checks_are_listed_by_id(self):
        record = execute_run(DemoClient(), False, False, False, save=False)
        s = observe.run_summary(record, "demo")
        self.assertIn("euro", s["failed_checks"])

    def test_summary_never_contains_receipt_text_or_agent_output(self):
        blob = json.dumps(observe.run_summary(sample_record(), "demo"))
        for forbidden in ("receipt_01", "Summary", "Vendor", "observation", "args"):
            self.assertNotIn(forbidden, blob)

    def test_keys_are_redacted_from_errors(self):
        record = sample_record()
        record["error"] = "The provider rejected the request: bad key visitor-secret-12345 in header"
        s = observe.run_summary(record, "visitor", ("visitor-secret-12345",))
        self.assertNotIn("visitor-secret", json.dumps(s))
        self.assertIn("[redacted]", s["error"])

    def test_long_errors_are_cut(self):
        record = sample_record()
        record["error"] = "x" * 1000
        self.assertEqual(len(observe.run_summary(record, "host")["error"]), observe.MAX_ERROR_CHARS)


class StreamLoggingTests(unittest.TestCase):
    def run_stream(self, payload, factory):
        with self.assertLogs("praxis.run", level="INFO") as captured:
            list(core.stream_run(core.parse_run_request(payload), client_factory=factory))
        return [json.loads(record.getMessage()) for record in captured.records]

    def test_a_run_writes_exactly_one_json_line(self):
        lines = self.run_stream({"setup": "instructions"}, lambda _r: DemoClient(delay=0.0))
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["event"], lines[0]["key_source"], lines[0]["score"]), ("run", "demo", 7))

    def test_a_failed_start_is_logged_without_the_key(self):
        from praxis.llm import LLMError

        def refuse(_r):
            raise LLMError("rejected key visitor-key-abcdef123")

        lines = self.run_stream({"provider": "gemini", "api_key": "visitor-key-abcdef123"}, refuse)
        self.assertEqual(lines[0]["event"], "run_failed")
        self.assertEqual(lines[0]["key_source"], "visitor")
        self.assertNotIn("visitor-key", json.dumps(lines))

    def test_a_crash_logs_only_the_error_type(self):
        class Boom(DemoClient):
            def chat(self, *a, **k):
                raise RuntimeError("secret-details-SHOULD-NOT-APPEAR")

        lines = self.run_stream({"setup": "baseline"}, lambda _r: Boom(delay=0.0))
        self.assertEqual(lines[0]["reason"], "crash: RuntimeError")
        self.assertNotIn("SHOULD-NOT-APPEAR", json.dumps(lines))


if __name__ == "__main__":
    unittest.main()
