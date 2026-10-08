"""Shared helpers for the tests."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from praxis.llm import LLMReply


def build_report(path: Path, key: dict, *, travel=None, office=None, flags="correct", extra_meal_flag=False):
    """Write a spreadsheet the way a perfect agent would, with optional mistakes."""
    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    summary.append(["Category", "Total (USD)"])
    for category, value in key["totals"].items():
        if category == "Travel" and travel is not None:
            value = travel
        if category == "Office" and office is not None:
            value = office
        summary.append([category, value])
    if flags is not None:
        sheet = wb.create_sheet("Flags")
        sheet.append(["File", "Reason"])
        if flags == "correct":
            for name in key["over_policy_files"]:
                sheet.append([name, "Meal over 75 USD"])
            sheet.append([key["duplicate_copy"], f"Duplicate of {key['duplicate_original']}"])
        if extra_meal_flag:
            sheet.append(["receipt_07.csv", "Meal over 75 USD"])
    wb.save(path)


class StubClient:
    """A fake brain that replays a fixed list of replies (or raises an error)."""

    provider = "stub"
    model = "stub-model"
    is_demo = False

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []  # every (system, messages, tools) the agent sent

    def chat(self, system, messages, tools):
        self.seen.append((system, [dict(m) for m in messages], tools))
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def call(name, args, call_id="c1"):
    return {"id": call_id, "name": name, "args": args}


def reply(text="", calls=None, tokens_in=10, tokens_out=5):
    return LLMReply(text=text, tool_calls=calls or [], tokens_in=tokens_in, tokens_out=tokens_out)
