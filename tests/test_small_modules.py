import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from praxis import caps, cli
from praxis.config import SETUPS, build_config, get_setup, lever_texts, load_env, tool_lists
from praxis.viewmodel import (activity_rows, compare_rows, hint_rows, latest_plan, model_label,
                                  percent, plan_progress, score_text, short_args)


class CapsTests(unittest.TestCase):
    def test_counts_runs_and_enforces_the_limit(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"DAILY_RUN_CAP": "2"}):
            path = Path(tmp, "usage.json")
            self.assertEqual(caps.runs_left(path), 2)
            caps.record_run(path)
            caps.record_run(path)
            self.assertEqual((caps.runs_today(path), caps.runs_left(path)), (2, 0))

    def test_a_new_day_resets_the_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "usage.json")
            path.write_text(json.dumps({"date": "1999-01-01", "count": 99}))
            self.assertEqual(caps.runs_today(path), 0)

    def test_corrupt_file_and_bad_setting_are_safe(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"DAILY_RUN_CAP": "lots"}):
            path = Path(tmp, "usage.json")
            path.write_text("not json")
            self.assertEqual(caps.runs_today(path), 0)
            self.assertEqual(caps.daily_cap(), 20)


class ConfigTests(unittest.TestCase):
    def test_four_setups_each_add_one_lever(self):
        flags = [(s.context, s.workspace, s.instructions) for s in SETUPS]
        self.assertEqual(flags, [(False, False, False), (True, False, False), (True, True, False), (True, True, True)])

    def test_unknown_setup_name(self):
        with self.assertRaises(ValueError):
            get_setup("nope")
        self.assertEqual(get_setup("workspace").label, "+ context + tool")

    def test_lever_files_are_present_and_the_tool_lever_is_add_sheet(self):
        self.assertTrue(all(lever_texts().values()))
        tools = tool_lists()
        self.assertEqual(set(tools["full"]) - set(tools["default"]), {"add_sheet"})

    def test_config_switches(self):
        config = build_config(False, False, False)
        self.assertEqual(config.context_text, "")
        self.assertNotIn("add_sheet", config.tools)

    def test_env_file_never_overrides_real_environment_variables(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            (fake_root / ".env").write_text('# comment\nGEMINI_API_KEY="from-file"\nOTHER=\nBROKEN LINE\n')
            with mock.patch("praxis.config.ROOT", fake_root), mock.patch.dict(os.environ, {"GEMINI_API_KEY": "real"}, clear=True):
                load_env()
                self.assertEqual(os.environ["GEMINI_API_KEY"], "real")
            with mock.patch("praxis.config.ROOT", fake_root), mock.patch.dict(os.environ, {}, clear=True):
                load_env()
                self.assertEqual(os.environ["GEMINI_API_KEY"], "from-file")
                self.assertNotIn("OTHER", os.environ)


class ViewModelTests(unittest.TestCase):
    STEPS = [
        {"n": 1, "type": "plan", "items": [{"text": "a", "status": "done"}, {"text": "b", "status": "doing"}]},
        {"n": 2, "type": "assistant", "text": "thinking"},
        {"n": 3, "type": "tool", "name": "write_rows", "args": {"sheet": "Summary", "start_row": 1, "rows": [[1], [2]]}, "observation": "Wrote 2 row(s)", "ok": True},
        {"n": 4, "type": "tool", "name": "add_sheet", "args": {"name": "Flags"}, "observation": "ERROR: not available", "ok": False},
        {"n": 5, "type": "finish", "summary": "done"},
        {"n": 6, "type": "error", "message": "stopped"},
    ]

    def test_plan_helpers(self):
        plan = latest_plan(self.STEPS)
        self.assertEqual(plan_progress(plan), (1, 2))
        self.assertEqual(latest_plan([]), [])

    def test_activity_rows(self):
        rows = activity_rows(self.STEPS)
        self.assertEqual([r["kind"] for r in rows], ["plan", "think", "tool", "tool", "finish", "error"])
        self.assertEqual(rows[2]["title"], "write_rows  Summary, row 1, 2 row(s)")
        self.assertFalse(rows[3]["ok"])
        self.assertEqual(rows[0]["detail"], "1 of 2 steps done")

    def test_small_formatters(self):
        self.assertEqual(score_text({"score": 5, "total": 7}), "5 / 7")
        self.assertEqual(percent({"score": 7, "total": 7}), 100)
        self.assertEqual(percent({"score": 0, "total": 0}), 0)
        self.assertEqual(short_args("write_cell", {"sheet": "S", "cell": "B2", "value": 5}), "S!B2 = 5")
        self.assertEqual(hint_rows([{"lever": "context", "title": "t", "evidence": "e"}])[0]["lever"], "Context")

    def test_demo_is_always_labelled(self):
        self.assertIn("DEMO", model_label({"provider": "demo", "model": "scripted-demo", "demo": True}))
        self.assertNotIn("DEMO", model_label({"provider": "gemini", "model": "m", "demo": False}))

    def test_compare_rows(self):
        results = {"rows": [{"label": "Goal only", "avg_score": 3.0, "total": 7, "avg_tool_calls": 26, "avg_tokens": 0, "errored_runs": 0}]}
        self.assertEqual(compare_rows(results)[0]["Average score"], 3.0)


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_demo_run_prints_the_demo_warning_and_the_score(self):
        code, text = self.run_cli("run", "--provider", "demo", "--setup", "instructions", "--no-save")
        self.assertEqual(code, 0)
        self.assertIn("DEMO MODEL", text)
        self.assertIn("Score: 7 / 7", text)

    def test_missing_key_is_a_friendly_message_not_a_traceback(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("praxis.cli.load_env"):
            code, text = self.run_cli("run", "--provider", "gemini", "--no-save")
        self.assertEqual(code, 2)
        self.assertIn("GEMINI_API_KEY", text)

    def test_bad_setup_name_is_rejected(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.build_parser().parse_args(["run", "--setup", "nope"])


if __name__ == "__main__":
    unittest.main()
