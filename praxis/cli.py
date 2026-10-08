"""Command line: run the agent, compare setups, list saved runs.

    python -m praxis run --provider demo --setup baseline
    python -m praxis compare --provider gemini --runs 5
"""

from __future__ import annotations

import argparse
import sys

from . import receipts
from .compare import run_matrix, save_results
from .config import SETUPS, get_setup, load_env
from .demo_model import DemoClient
from .llm import LIVE_PROVIDERS, LLMError, default_model, make_client
from .pipeline import execute_run
from .runlog import list_runs, load_run
from .viewmodel import PLAN_ICON, LEVER_NAME, model_label, score_text, short_args

COLOR = sys.stdout.isatty()


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def green(t): return paint(t, "32")
def red(t): return paint(t, "31")
def dim(t): return paint(t, "2")
def bold(t): return paint(t, "1")
def cyan(t): return paint(t, "36")


def print_event(step: dict) -> None:
    """Show each step as it happens, with the plan as a live checklist."""
    kind = step["type"]
    if kind == "plan":
        print(bold("\n  Plan"))
        for item in step["items"]:
            icon = PLAN_ICON[item["status"]]
            line = f"   {icon} {item['text']}"
            print(green(line) if item["status"] == "done" else cyan(line) if item["status"] == "doing" else dim(line))
        print()
    elif kind == "assistant":
        print(dim(f"  {step['text']}"))
    elif kind == "tool":
        mark = green("ok ") if step["ok"] else red("ERR")
        print(f"  step {step['n']:>2}  {mark}  {step['name']}  {dim(short_args(step['name'], step['args']))}")
        if not step["ok"]:
            print(red(f"           {step['observation']}"))
    elif kind == "finish":
        print(green(f"\n  Finished: {step['summary']}"))
    elif kind == "error":
        print(red(f"\n  Stopped: {step['message']}"))


def print_scorecard(record: dict) -> None:
    check = record["check"]
    print(bold("\n  Checker (opens the real file)"))
    for item in check["checks"]:
        mark = green("PASS") if item["passed"] else red("FAIL")
        print(f"   {mark}  {item['title']}")
        if not item["passed"]:
            print(dim(f"          {item['detail']}"))
    print(bold(f"\n  Score: {score_text(check)}"))
    if record["hints"]:
        print(bold("\n  What to change next"))
        for hint in record["hints"]:
            print(f"   [{LEVER_NAME.get(hint['lever'], hint['lever'])}] {hint['title']}")
            print(dim(f"       {hint['evidence']}"))


def cmd_make_data(_args) -> int:
    receipts.write_all()
    print(f"Wrote {len(receipts.RECEIPTS)} receipts to {receipts.RECEIPTS_SRC} and the answer key.")
    return 0


def _client(args):
    if args.provider == "demo":
        return DemoClient(delay=getattr(args, "delay", 0.0))
    return make_client(args.provider, model=args.model)


def cmd_run(args) -> int:
    setup = get_setup(args.setup)
    try:
        client = _client(args)
    except LLMError as exc:
        print(red(f"Cannot start: {exc}"))
        return 2
    print(bold("\nPraxis"), dim(f"· {model_label({'provider': client.provider, 'model': client.model, 'demo': client.is_demo})}"))
    if client.is_demo:
        print(red("  DEMO MODEL: scripted, not an AI. Its scores are not results."))
    print(dim(f"  Setup: {setup.label}  (context={setup.context}, tool={setup.workspace}, instructions={setup.instructions})"))
    record = execute_run(client, setup.context, setup.workspace, setup.instructions,
                         on_event=print_event, save=not args.no_save)
    print_scorecard(record)
    print(dim(f"\n  {record['seconds']}s, {record['tokens_in']} tokens in, {record['tokens_out']} tokens out"
              + ("" if args.no_save else f", saved as logs/{record['run_id']}.json")))
    return 0 if not record["error"] else 1


def cmd_compare(args) -> int:
    try:
        probe = _client(args)
    except LLMError as exc:
        print(red(f"Cannot start: {exc}"))
        return 2
    print(bold("\nComparing the four setups"), dim(f"· {args.runs} run(s) each · {model_label({'provider': probe.provider, 'model': probe.model, 'demo': probe.is_demo})}"))
    if probe.is_demo:
        print(red("  DEMO MODEL: scripted, not an AI. This table is NOT a result."))
    results = run_matrix(lambda: _client(args), args.runs, progress=lambda m: print(dim(f"  {m}")), save_logs=args.save_logs)
    print(bold(f"\n  {'Setup':<36}{'Avg score':>10}{'Tool calls':>12}{'Tokens':>10}{'Errors':>8}"))
    for row in results["rows"]:
        print(f"  {row['label']:<36}{row['avg_score']:>6}/{row['total']:<3}{row['avg_tool_calls']:>12}{row['avg_tokens']:>10}{row['errored_runs']:>8}")
    path = save_results(results, name=args.out)
    print(dim(f"\n  Saved to {path}"))
    return 0


def cmd_make_examples(_args) -> int:
    """Save one scripted-demo run per setup, so the web app has something to show with no key."""
    from .compare import save_results

    for setup in SETUPS:
        execute_run(DemoClient(), setup.context, setup.workspace, setup.instructions,
                    run_id=f"example_demo_{setup.name}")
        print(f"Saved logs/example_demo_{setup.name}.json")
    results = run_matrix(DemoClient, 1)
    print(f"Saved {save_results(results, name='example_demo_compare.json')}")
    print(red("These are DEMO runs from the scripted model. They are not results."))
    return 0


def cmd_list(_args) -> int:
    runs = list_runs()
    if not runs:
        print("No saved runs yet.")
    for path in runs:
        record = load_run(path)
        print(f"{path.stem:<28} {record['setup']['label']:<34} {score_text(record['check']):>7}  {model_label(record)}")
    return 0


def cmd_show(args) -> int:
    from pathlib import Path

    from .config import LOGS_DIR

    path = Path(args.run)
    if not path.exists():
        path = LOGS_DIR / f"{args.run}.json"
    record = load_run(path)
    print(bold(f"\nRun {record['run_id']}"), dim(f"· {model_label(record)} · {record['setup']['label']}"))
    for step in record["steps"]:
        print_event(step)
    print_scorecard(record)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="praxis", description="Praxis: give an AI agent a goal, watch it work, check the result.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("make-data", help="regenerate the receipts and the answer key").set_defaults(func=cmd_make_data)

    providers = ["demo", *LIVE_PROVIDERS]
    run = sub.add_parser("run", help="run the agent once")
    run.add_argument("--provider", choices=providers, default="demo")
    run.add_argument("--model", help="override the model name")
    run.add_argument("--setup", choices=[s.name for s in SETUPS], default="baseline")
    run.add_argument("--no-save", action="store_true", help="do not write a log file")
    run.add_argument("--delay", type=float, default=0.0, help="demo model only: pause per step so it is easy to watch")
    run.set_defaults(func=cmd_run)

    compare = sub.add_parser("compare", help="run all four setups several times")
    compare.add_argument("--provider", choices=providers, default="demo")
    compare.add_argument("--model", help="override the model name")
    compare.add_argument("--runs", type=int, default=3, help="runs per setup")
    compare.add_argument("--save-logs", action="store_true", help="also save every individual run")
    compare.add_argument("--out", help="file name for the results (inside results/)")
    compare.set_defaults(func=cmd_compare, delay=0.0)

    sub.add_parser("make-examples", help="save scripted-demo example runs for the web app").set_defaults(func=cmd_make_examples)
    sub.add_parser("list", help="list saved runs").set_defaults(func=cmd_list)
    show = sub.add_parser("show", help="replay a saved run in the terminal")
    show.add_argument("run", help="run id or path to a log file")
    show.set_defaults(func=cmd_show)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_env()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
