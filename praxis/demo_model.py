"""A SCRIPTED stand-in for an AI model. It is NOT an AI and its scores are NOT results.

Why it exists: so the whole project (agent loop, sandbox, checker, UI, tests) can run
with no API key and no cost. It follows fixed rules based on what it is shown:
  * it only converts euros if the context contains an exchange rate,
  * it only flags meals over the limit if the context states the policy,
  * it only handles duplicates if the instructions mention them,
  * it tries to add a "Flags" sheet and fails if the add_sheet tool is not offered.

That makes the four setups behave differently in a predictable way, which is what we
need to test the harness. Real measurements must come from a real model.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

from .llm import LLMReply

CATEGORIES = ["Meals", "Office", "Other", "Software", "Travel"]
PLAN_TEXT = [
    "Look at the receipts folder",
    "Read every receipt",
    "Total each category (convert currencies)",
    "Build the Summary sheet",
    "Flag anything that needs attention",
]


def parse_receipt(text: str) -> dict | None:
    """Read one receipt in any of the four layouts. Returns None if it cannot be read."""
    text = text.strip()
    vendor = date = category = None
    amount = None
    currency = "USD"
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if lines and lines[0].lower().startswith("vendor,date"):  # csv layout
        parts = [p.strip() for p in lines[1].split(",")]
        vendor, date, category, amount, currency = parts[0], parts[1], parts[2], float(parts[3]), parts[4]
    elif text.startswith("Paid"):  # sentence layout
        match = re.match(r"Paid\s*([$€])([\d.,]+) to (.+?) on (.+?)\. Category: (\w+)\.", text)
        if not match:
            return None
        symbol, number, vendor, date, category = match.groups()
        amount, currency = float(number.replace(",", "")), "EUR" if symbol == "€" else "USD"
    elif lines and lines[0].startswith("***"):  # "*** RECEIPT ***" layout
        vendor = lines[1]
        for line in lines[2:]:
            if line.startswith("Date:"):
                date = line.split(":", 1)[1].strip()
            elif line.startswith("Category:"):
                category = line.split(":", 1)[1].strip()
            elif line.startswith("Total:"):
                raw = line.split(":", 1)[1].strip()
                amount, currency = float(re.sub(r"[^\d.]", "", raw)), "EUR" if "€" in raw else "USD"
    else:  # "Key: value" layout
        fields = {}
        for line in lines:
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip().lower()] = value.strip()
        vendor, date, category = fields.get("vendor"), fields.get("date"), fields.get("category")
        if "amount" in fields:
            number, _, code = fields["amount"].partition(" ")
            amount, currency = float(number), (code or "USD").upper()

    if not (vendor and date and category and amount is not None):
        return None
    return {"vendor": vendor, "date": _iso(date), "category": category, "amount": amount, "currency": currency}


def _iso(value: str) -> str:
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return value


class DemoClient:
    """Same interface as a real LLM client: chat(system, messages, tools) -> LLMReply."""

    provider = "demo"
    model = "scripted-demo"
    is_demo = True

    def __init__(self, delay: float = 0.0):
        self.delay = delay  # a small pause so a live UI run is easy to watch

    # ---- reading what the agent was shown ---------------------------------
    @staticmethod
    def _settings(system: str, tools: list[dict]) -> dict:
        rate = re.search(r"1\s*EUR\s*=\s*([0-9.]+)\s*USD", system)
        limit = re.search(r"over\s+(\d+)\s*USD", system)
        return {
            "eur_rate": float(rate.group(1)) if rate else None,
            "meal_limit": float(limit.group(1)) if limit else None,
            "dedupe": "duplicate" in system.lower(),
            "can_add_sheet": any(t["name"] == "add_sheet" for t in tools),
        }

    @staticmethod
    def _history(messages: list[dict]) -> dict:
        """Collect what has happened so far from the conversation."""
        calls_by_id: dict[str, dict] = {}
        for message in messages:
            for call in message.get("tool_calls", []) if message["role"] == "assistant" else []:
                calls_by_id[call["id"]] = call
        listing, files, add_sheet_ok = None, {}, None
        summary_written = flags_written = add_sheet_tried = False
        for call in calls_by_id.values():
            if call["name"] == "write_rows":
                summary_written |= call["args"].get("sheet") == "Summary"
                flags_written |= call["args"].get("sheet") == "Flags"
            if call["name"] == "add_sheet":
                add_sheet_tried = True
        for message in messages:
            if message["role"] != "tool":
                continue
            for result in message["results"]:
                call = calls_by_id.get(result["id"], {})
                if call.get("name") == "list_files":
                    listing = re.findall(r"receipts/(receipt_\d+\.\w+)", result["content"])
                elif call.get("name") == "read_file":
                    files[call["args"]["path"].split("/")[-1]] = result["content"]
                elif call.get("name") == "add_sheet":
                    add_sheet_ok = result.get("ok", False)
        return {
            "turn": sum(1 for m in messages if m["role"] == "assistant"),
            "listing": listing,
            "files": files,
            "summary_written": summary_written,
            "flags_written": flags_written,
            "add_sheet_tried": add_sheet_tried,
            "add_sheet_ok": add_sheet_ok,
        }

    # ---- the "thinking": turn raw receipts into report rows ----------------
    @staticmethod
    def _build_report(files: dict[str, str], cfg: dict) -> tuple[list[list], list[list]]:
        totals = {name: 0.0 for name in CATEGORIES}
        flags: list[list] = []
        seen: dict[tuple, str] = {}
        for name in sorted(files):
            receipt = parse_receipt(files[name])
            if receipt is None:
                continue
            key = (receipt["vendor"].lower(), receipt["date"], round(receipt["amount"], 2), receipt["currency"])
            if cfg["dedupe"] and key in seen:
                flags.append([name, f"Duplicate of {seen[key]}"])
                continue
            seen[key] = name
            amount = receipt["amount"]
            if receipt["currency"] == "EUR" and cfg["eur_rate"]:
                amount = round(amount * cfg["eur_rate"], 2)
            totals[receipt["category"]] = totals.get(receipt["category"], 0.0) + amount
            if cfg["meal_limit"] and receipt["category"] == "Meals" and amount > cfg["meal_limit"]:
                flags.append([name, f"Meal over {int(cfg['meal_limit'])} USD, needs manager approval"])
        summary = [["Category", "Total (USD)"]] + [[c, round(v, 2)] for c, v in sorted(totals.items())]
        return summary, ([["File", "Reason"]] + flags) if flags else []

    @staticmethod
    def _plan(*statuses: str) -> dict:
        return {"steps": [{"text": t, "status": s} for t, s in zip(PLAN_TEXT, statuses)]}

    # ---- the main entry point ----------------------------------------------
    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> LLMReply:
        if self.delay:
            time.sleep(self.delay)
        cfg, past = self._settings(system, tools), self._history(messages)
        turn = past["turn"]

        def call(name: str, args: dict, i: int = 0) -> dict:
            return {"id": f"demo_{turn}_{i}", "name": name, "args": args}

        # 1. Start: make a plan and look at the folder.
        if past["listing"] is None:
            return LLMReply(
                "I will start by looking at what is in the receipts folder.",
                [call("update_plan", self._plan("doing", "todo", "todo", "todo", "todo"), 0),
                 call("list_files", {"path": "receipts"}, 1)],
            )

        # 2. Read every receipt, a few at a time.
        unread = [name for name in past["listing"] if name not in past["files"]]
        if unread:
            batch = unread[:8]
            calls = [call("read_file", {"path": f"receipts/{name}"}, i) for i, name in enumerate(batch)]
            if len(batch) == len(past["listing"]):  # very first batch: show progress
                calls.insert(0, call("update_plan", self._plan("done", "doing", "todo", "todo", "todo"), 99))
            return LLMReply(f"Reading receipts ({len(past['files']) + len(batch)} of {len(past['listing'])}).", calls)

        summary, flags = self._build_report(past["files"], cfg)

        # 3. Write the Summary sheet (and try to prepare the Flags sheet).
        if not past["summary_written"]:
            calls = [
                call("update_plan", self._plan("done", "done", "done", "doing", "todo"), 0),
                call("write_rows", {"sheet": "Summary", "start_row": 1, "rows": summary}, 1),
            ]
            if flags:
                calls.append(call("add_sheet", {"name": "Flags"}, 2))  # fails if the tool is not offered
            return LLMReply("I have read everything. Writing the Summary sheet now.", calls)

        # 4. Write the Flags sheet if it exists.
        if flags and past["add_sheet_ok"] and not past["flags_written"]:
            return LLMReply(
                "Now listing the receipts that need attention.",
                [call("update_plan", self._plan("done", "done", "done", "done", "doing"), 0),
                 call("write_rows", {"sheet": "Flags", "start_row": 1, "rows": flags}, 1)],
            )

        # 5. Finish.
        note = "" if not flags or past["add_sheet_ok"] else " I could not create a Flags sheet, so nothing was flagged."
        return LLMReply(
            "Everything I can do is done.",
            [call("update_plan", self._plan("done", "done", "done", "done", "done"), 0),
             call("finish", {"summary": "The expense report is ready." + note}, 1)],
        )
