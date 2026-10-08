"""The agent loop: the whole idea of an "agent" in about 100 lines.

    ask the model what to do  ->  run the tools it asks for  ->  show it the results  ->  repeat

The model has no memory between calls. Everything it knows is the system prompt
(instructions + context), the goal, and the conversation so far, which we resend
each time. That is why context, workspace and instructions decide the result.
"""

from __future__ import annotations

import time
from typing import Callable

from .config import GOAL, AgentConfig
from .llm import LLMError
from .tools import TOOL_SPECS, ToolError, Workspace

SYSTEM_TEMPLATE = """You are Praxis, an AI assistant that completes office jobs by calling tools inside a private, sandboxed workspace.

How to work:
- Start by calling update_plan with 4 to 6 short steps. Call it again as you make progress (status is todo, doing or done).
- You can only read and write files through the tools you were given. If a tool you need is not available, say so instead of pretending.
- Check your own work when you can, for example by reading the report back with read_file.
- When the job is completely finished, call finish with a one-sentence summary. Never claim something you did not actually do.

## Instructions
{instructions}

## Context
{context}
"""

# Two tools belong to the harness itself, not to the workspace.
HARNESS_TOOLS = [
    {
        "name": "update_plan",
        "description": "Show your plan as a checklist. Call at the start and whenever progress changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "description": "The full plan, replacing the previous one",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Short step description"},
                            "status": {"type": "string", "description": "todo, doing or done"},
                        },
                        "required": ["text", "status"],
                    },
                }
            },
            "required": ["steps"],
        },
    },
    {
        "name": "finish",
        "description": "Call this once the job is completely finished, with a one-sentence summary.",
        "parameters": {
            "type": "object",
            "properties": {"summary": {"type": "string", "description": "One sentence about what you did"}},
            "required": ["summary"],
        },
    },
]


def build_system_prompt(config: AgentConfig) -> str:
    return SYSTEM_TEMPLATE.format(
        instructions=config.instructions_text,
        context=config.context_text or "(none provided)",
    )


def tool_specs(config: AgentConfig) -> list[dict]:
    """The tools offered to the model: the allowed workspace tools plus the two harness tools."""
    workspace_tools = [{"name": n, **TOOL_SPECS[n]} for n in config.tools]
    return workspace_tools + HARNESS_TOOLS


def normalize_plan(raw) -> list[dict]:
    """Accept the plan in any reasonable shape and return [{'text', 'status'}]."""
    items = raw.get("steps") if isinstance(raw, dict) else raw
    plan = []
    for item in items or []:
        if isinstance(item, str):
            plan.append({"text": item, "status": "todo"})
        elif isinstance(item, dict) and item.get("text"):
            status = str(item.get("status", "todo")).lower()
            plan.append({"text": str(item["text"]), "status": status if status in ("todo", "doing", "done") else "todo"})
    return plan


def run_agent(
    client,
    config: AgentConfig,
    workspace: Workspace,
    goal: str = GOAL,
    max_steps: int = 30,
    on_event: Callable[[dict], None] | None = None,
) -> dict:
    """Run the agent until it finishes. Returns the full record, including every step (the trajectory)."""
    started = time.time()
    steps: list[dict] = []
    totals = {"tokens_in": 0, "tokens_out": 0}

    def emit(kind: str, **data) -> None:
        step = {"n": len(steps) + 1, "type": kind, **data}
        steps.append(step)
        if on_event:
            on_event(step)

    system = build_system_prompt(config)
    tools = tool_specs(config)
    messages: list[dict] = [{"role": "user", "content": goal}]
    finished, summary, error, stop_reason, nudged = False, "", None, "max_steps", False

    for _turn in range(max_steps):
        try:
            reply = client.chat(system, messages, tools)
        except LLMError as exc:
            error, stop_reason = str(exc), "error"
            emit("error", message=error)
            break
        totals["tokens_in"] += reply.tokens_in
        totals["tokens_out"] += reply.tokens_out
        if reply.text:
            emit("assistant", text=reply.text)

        if not reply.tool_calls:
            # Some weaker models answer in plain text. Nudge them once to keep using tools.
            if not nudged:
                nudged = True
                messages.append({"role": "assistant", "text": reply.text or "(no response)", "tool_calls": []})
                messages.append({"role": "user", "content": "Please continue by calling tools, and call finish when the job is done."})
                continue
            stop_reason = "no_tool_calls"
            break

        messages.append({"role": "assistant", "text": reply.text, "tool_calls": reply.tool_calls})
        results = []
        for call in reply.tool_calls:
            name, args = call["name"], call["args"]
            if name == "update_plan":
                emit("plan", items=normalize_plan(args))
                observation, ok = "Plan updated.", True
            elif name == "finish":
                summary = str(args.get("summary", "")) if isinstance(args, dict) else ""
                emit("finish", summary=summary)
                finished, observation, ok = True, "Finished.", True
            else:
                tool_started = time.time()
                try:
                    observation, ok = workspace.call(name, args, config.tools), True
                except ToolError as exc:
                    observation, ok = f"ERROR: {exc}", False
                except Exception as exc:  # a tool crashed: tell the agent instead of stopping the run
                    observation, ok = f"ERROR: tool crashed ({exc.__class__.__name__}).", False
                emit(
                    "tool",
                    name=name,
                    args=args,
                    observation=observation,
                    ok=ok,
                    ms=int((time.time() - tool_started) * 1000),
                )
            results.append({"id": call["id"], "name": name, "content": observation, "ok": ok})
        messages.append({"role": "tool", "results": results})
        if finished:
            stop_reason = "finished"
            break

    return {
        "goal": goal,
        "steps": steps,
        "finished": finished,
        "summary": summary,
        "stop_reason": stop_reason,
        "error": error,
        "tokens_in": totals["tokens_in"],
        "tokens_out": totals["tokens_out"],
        "seconds": round(time.time() - started, 2),
    }
