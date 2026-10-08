import tempfile
import unittest
from pathlib import Path

from praxis import compare
from praxis.agent import build_system_prompt, normalize_plan, run_agent, tool_specs
from praxis.config import SETUPS, build_config
from praxis.demo_model import DemoClient
from praxis.llm import LLMError
from praxis.pipeline import execute_run
from praxis.runlog import list_runs, load_run, report_bytes
from praxis.tools import Workspace
from helpers import StubClient, call, reply


def run_with(client, **config_flags):
    flags = {"context": False, "workspace": False, "instructions": False, **config_flags}
    workspace = Workspace.create()
    try:
        return run_agent(client, build_config(**flags), workspace)
    finally:
        workspace.cleanup()


class SetupProgressionTests(unittest.TestCase):
    """The harness should turn each lever into a measurable change (using the scripted model)."""

    def test_scores_improve_one_lever_at_a_time(self):
        scores = []
        for setup in SETUPS:
            record = execute_run(DemoClient(), setup.context, setup.workspace, setup.instructions, save=False)
            scores.append(record["check"]["score"])
        self.assertEqual(scores, [3, 4, 5, 7])

    def test_the_demo_model_is_labelled_as_demo_in_the_record(self):
        record = execute_run(DemoClient(), False, False, False, save=False)
        self.assertTrue(record["demo"])
        self.assertEqual((record["tokens_in"], record["tokens_out"]), (0, 0))

    def test_record_contains_the_trajectory_checks_and_hints(self):
        record = execute_run(DemoClient(), False, False, False, save=False)
        kinds = {s["type"] for s in record["steps"]}
        self.assertTrue({"plan", "tool", "finish"} <= kinds)
        self.assertEqual(record["check"]["total"], 7)
        self.assertTrue(record["hints"])

    def test_context_only_run_points_at_the_missing_tool(self):
        record = execute_run(DemoClient(), True, False, False, save=False)
        self.assertIn("workspace", {h["lever"] for h in record["hints"]})
        failed_tools = [s for s in record["steps"] if s["type"] == "tool" and not s["ok"]]
        self.assertEqual(failed_tools[0]["name"], "add_sheet")

    def test_full_setup_passes_everything_and_needs_no_changes(self):
        record = execute_run(DemoClient(), True, True, True, save=False)
        self.assertEqual(record["check"]["score"], 7)
        self.assertEqual(record["hints"], [])

    def test_runs_are_independent(self):
        first = execute_run(DemoClient(), True, True, True, save=False)
        second = execute_run(DemoClient(), False, False, False, save=False)
        self.assertEqual((first["check"]["score"], second["check"]["score"]), (7, 3))


class PromptTests(unittest.TestCase):
    def test_levers_change_what_the_agent_is_shown(self):
        base = build_config(False, False, False)
        full = build_config(True, True, True)
        self.assertNotIn("1.10", build_system_prompt(base))
        self.assertIn("1 EUR = 1.10 USD", build_system_prompt(full))
        self.assertNotIn("add_sheet", [t["name"] for t in tool_specs(base)])
        self.assertIn("add_sheet", [t["name"] for t in tool_specs(full)])
        self.assertIn("Duplicate", build_system_prompt(full))

    def test_base_prompt_does_not_leak_any_lever_content(self):
        text = build_system_prompt(build_config(False, False, False)).lower()
        self.assertNotIn("duplicate", text)
        self.assertNotIn("eur", text)
        self.assertNotIn("manager approval", text)

    def test_edited_lever_text_is_used(self):
        config = build_config(True, False, False, overrides={"context": "Rate: 1 EUR = 1.50 USD."})
        self.assertIn("1.50", build_system_prompt(config))


class LoopBehaviourTests(unittest.TestCase):
    def test_unknown_tool_is_reported_and_the_run_continues(self):
        client = StubClient([
            reply(calls=[call("delete_everything", {})]),
            reply(calls=[call("finish", {"summary": "done"})]),
        ])
        record = run_with(client)
        tool_step = next(s for s in record["steps"] if s["type"] == "tool")
        self.assertFalse(tool_step["ok"])
        self.assertIn("not available", tool_step["observation"])
        self.assertTrue(record["finished"])

    def test_model_error_stops_the_run_with_a_clear_message(self):
        record = run_with(StubClient([LLMError("Rate limit reached.")]))
        self.assertEqual((record["stop_reason"], record["error"]), ("error", "Rate limit reached."))
        self.assertFalse(record["finished"])

    def test_plain_text_answers_get_one_nudge_then_stop(self):
        client = StubClient([reply("I think I am done."), reply("Really done.")])
        record = run_with(client)
        self.assertEqual(record["stop_reason"], "no_tool_calls")
        nudge = client.seen[1][1][-1]
        self.assertEqual(nudge["role"], "user")
        self.assertIn("call finish", nudge["content"])

    def test_step_limit_prevents_endless_loops(self):
        client = StubClient([reply(calls=[call("list_files", {"path": "."}, f"c{i}")]) for i in range(5)])
        workspace = Workspace.create()
        self.addCleanup(workspace.cleanup)
        record = run_agent(client, build_config(False, False, False), workspace, max_steps=3)
        self.assertEqual(record["stop_reason"], "max_steps")
        self.assertEqual(len(client.seen), 3)

    def test_tool_results_are_fed_back_to_the_model(self):
        client = StubClient([
            reply(calls=[call("list_files", {"path": "receipts"})]),
            reply(calls=[call("finish", {"summary": "ok"})]),
        ])
        run_with(client)
        last_messages = client.seen[1][1]
        self.assertEqual(last_messages[-1]["role"], "tool")
        self.assertIn("receipt_01", last_messages[-1]["results"][0]["content"])

    def test_tokens_are_added_up(self):
        client = StubClient([reply(calls=[call("list_files", {"path": "."})]), reply(calls=[call("finish", {"summary": "x"})])])
        record = run_with(client)
        self.assertEqual((record["tokens_in"], record["tokens_out"]), (20, 10))

    def test_plan_is_normalised_from_sloppy_shapes(self):
        plan = normalize_plan({"steps": ["read", {"text": "write", "status": "DONE"}, {"text": "x", "status": "weird"}, {}]})
        self.assertEqual([p["status"] for p in plan], ["todo", "done", "todo"])
        self.assertEqual(normalize_plan(["a", "b"])[1]["text"], "b")
        self.assertEqual(normalize_plan(None), [])

    def test_events_stream_while_the_agent_works(self):
        seen = []
        workspace = Workspace.create()
        self.addCleanup(workspace.cleanup)
        run_agent(DemoClient(), build_config(True, True, True), workspace, on_event=seen.append)
        self.assertEqual([s["n"] for s in seen], list(range(1, len(seen) + 1)))
        self.assertEqual(seen[-1]["type"], "finish")


class SavingAndComparingTests(unittest.TestCase):
    def test_saved_run_round_trips_and_keeps_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = execute_run(DemoClient(), True, True, True, logs_dir=Path(tmp))
            files = list_runs(Path(tmp))
            self.assertEqual(len(files), 1)
            loaded = load_run(files[0])
            self.assertEqual(loaded["check"]["score"], 7)
            self.assertTrue(report_bytes(loaded, Path(tmp)))
            self.assertTrue(loaded["demo"])
            self.assertNotIn("api_key", str(loaded).lower())
            self.assertEqual(record["run_id"], loaded["run_id"])

    def test_compare_matrix_and_saving(self):
        results = compare.run_matrix(DemoClient, runs_per_setup=2)
        self.assertTrue(results["demo"])
        self.assertEqual([row["avg_score"] for row in results["rows"]], [3.0, 4.0, 5.0, 7.0])
        self.assertEqual(results["rows"][0]["scores"], [3, 3])
        with tempfile.TemporaryDirectory() as tmp:
            path = compare.save_results(results, Path(tmp))
            self.assertEqual(compare.load_results(path)["rows"][3]["avg_score"], 7.0)
            self.assertEqual(compare.list_result_files(Path(tmp)), [path])

    def test_errored_runs_are_counted_in_the_results(self):
        class Failing(StubClient):
            def __init__(self):
                super().__init__([LLMError("boom")])

        results = compare.run_matrix(Failing, runs_per_setup=1, setups=SETUPS[:1])
        self.assertEqual(results["rows"][0]["errored_runs"], 1)


if __name__ == "__main__":
    unittest.main()
