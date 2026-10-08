"""Paths, the three "levers" (context, workspace, instructions) and setups.

The three levers come straight from the agent-directing framework:
  1. context      - facts the agent needs but cannot guess
  2. workspace    - the tools and files the agent can reach
  3. instructions - how clearly the job and the output are described

A "setup" is simply which of the three levers are switched on.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RECEIPTS_SRC = DATA_DIR / "receipts"
ANSWER_KEY = DATA_DIR / "answer_key.json"
CONFIGS_DIR = ROOT / "configs"
LOGS_DIR = ROOT / "logs"
RESULTS_DIR = ROOT / "results"

# The one job this project does.
GOAL = "Prepare the March expense report."


@dataclass(frozen=True)
class Setup:
    """Which levers are switched on for a run."""

    name: str
    label: str
    context: bool
    workspace: bool
    instructions: bool


# Each setup adds exactly one lever to the previous one, so the score
# difference between two neighbours tells you what that lever was worth.
SETUPS = [
    Setup("baseline", "Goal only", False, False, False),
    Setup("context", "+ context", True, False, False),
    Setup("workspace", "+ context + tool", True, True, False),
    Setup("instructions", "+ context + tool + instructions", True, True, True),
]


def get_setup(name: str) -> Setup:
    """Find a named setup (baseline, context, workspace, instructions)."""
    for setup in SETUPS:
        if setup.name == name:
            return setup
    names = ", ".join(s.name for s in SETUPS)
    raise ValueError(f"Unknown setup '{name}'. Choose one of: {names}")


@dataclass
class AgentConfig:
    """Everything that is put in front of the agent besides the goal."""

    context_text: str
    instructions_text: str
    tools: list[str]


def _read(name: str) -> str:
    return (CONFIGS_DIR / name).read_text(encoding="utf-8").strip()


def lever_texts() -> dict[str, str]:
    """The default text of each lever (the UI shows and lets you edit these)."""
    return {
        "context": _read("context.md"),
        "instructions_basic": _read("instructions_basic.md"),
        "instructions_clear": _read("instructions_clear.md"),
    }


def tool_lists() -> dict[str, list[str]]:
    """Tool names without and with the 'add_sheet' tool."""
    default = json.loads(_read("tools_default.json"))["tools"]
    full = json.loads(_read("tools_full.json"))["tools"]
    return {"default": default, "full": full}


def build_config(
    context: bool,
    workspace: bool,
    instructions: bool,
    overrides: dict[str, str] | None = None,
) -> AgentConfig:
    """Assemble the agent's configuration from the three lever switches.

    `overrides` lets the UI pass edited text, using the keys returned by
    lever_texts().
    """
    texts = {**lever_texts(), **(overrides or {})}
    tools = tool_lists()
    return AgentConfig(
        context_text=texts["context"] if context else "",
        instructions_text=(
            texts["instructions_clear"] if instructions else texts["instructions_basic"]
        ),
        tools=list(tools["full"] if workspace else tools["default"]),
    )


def config_for_setup(setup: Setup) -> AgentConfig:
    return build_config(setup.context, setup.workspace, setup.instructions)


def load_env() -> None:
    """Read a local .env file into the environment (no extra library needed).

    Real environment variables win, so host settings (such as Vercel environment variables) still work.
    """
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value and key not in os.environ:
            os.environ[key] = value
