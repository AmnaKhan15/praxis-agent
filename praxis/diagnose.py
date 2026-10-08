"""Turn failed checks and tool errors into "which lever should I change?".

This is the "read the trajectory, find where it went wrong" step from the course.
The rules are deliberately simple so you can read and explain every one of them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .checker import CheckResult


@dataclass
class Hint:
    lever: str  # context | workspace | instructions | other
    title: str
    evidence: str

    def to_dict(self) -> dict:
        return asdict(self)


def _failed(result: CheckResult) -> set[str]:
    return {c.id for c in result.checks if not c.passed}


def _find_tool_problem(steps: list[dict]) -> tuple[int, str] | None:
    """The first time the agent tried a tool or sheet that was not available."""
    for step in steps:
        if step.get("type") != "tool" or step.get("ok", True):
            continue
        text = step.get("observation", "")
        if "is not available" in text or ("Sheet '" in text and "not found" in text):
            return step["n"], text
    return None


def diagnose(result: CheckResult, steps: list[dict]) -> list[Hint]:
    failed = _failed(result)
    if not failed:
        return []
    hints: list[Hint] = []
    tool_problem = _find_tool_problem(steps)

    if "report" in failed:
        hints.append(Hint("instructions", "No usable report was produced",
                          "Read the trajectory to see where the agent stopped, then make the job and output clearer."))
    if "euro" in failed:
        hints.append(Hint("context", "The euro receipt was not converted",
                          "The agent had no exchange rate to use. Add the rate to the context."))
    if "policy" in failed or "dup_flag" in failed:
        if tool_problem:
            step_no, text = tool_problem
            hints.append(Hint("workspace", "The agent needed a tool it was not given",
                              f"Step {step_no}: {text}"))
        elif "policy" in failed:
            hints.append(Hint("context", "Over-policy meals were not flagged correctly",
                              "The agent may not know the meal policy. Add it to the context."))
    if "dup_total" in failed or "dup_flag" in failed:
        hints.append(Hint("instructions", "The duplicate receipt was not handled",
                          "Nothing told the agent how to treat duplicates. Say so in the instructions."))
    if "plain" in failed:
        hints.append(Hint("other", "Some plain totals are wrong",
                          "The agent misread receipts. Ask it to re-check its numbers, or try a stronger model."))
    if "untouched" in failed:
        hints.append(Hint("other", "Original receipts were changed",
                          "A guardrail failed. This should never happen; check the tools."))

    seen, unique = set(), []
    for hint in hints:
        if (hint.lever, hint.title) not in seen:
            seen.add((hint.lever, hint.title))
            unique.append(hint)
    return unique
