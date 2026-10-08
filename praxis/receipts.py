"""Builds the 24 messy March receipts and the private answer key.

The receipts are written in four different layouts on purpose (real receipts
never look alike). Three traps are hidden in the data:
  * receipt_11 is in euros          -> needs the exchange rate (context lever)
  * receipt_21 copies receipt_18    -> needs a duplicate rule (instructions lever)
  * two meals are over 75 USD       -> needs the policy (context) plus a Flags sheet (tool lever)

The answer key is computed from the same table, so it can never drift out of sync.
It is only ever read by the checker, never copied into the agent's workspace.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .config import ANSWER_KEY, DATA_DIR, RECEIPTS_SRC

EUR_RATE = 1.10  # 1 EUR = 1.10 USD, stated only in configs/context.md
MEAL_LIMIT = 75.0  # "over 75 USD" means strictly more than 75

# (vendor, month-day in March 2026, category, amount, currency)
# The position in this list is the receipt number (1 to 24).
RECEIPTS: list[tuple[str, int, str, float, str]] = [
    ("Blue Door Cafe", 2, "Meals", 18.40, "USD"),  # 1
    ("Harbor Grill", 5, "Meals", 82.50, "USD"),  # 2  over policy
    ("Noodle Bar", 9, "Meals", 24.10, "USD"),  # 3
    ("Cedar & Co Catering", 12, "Meals", 140.00, "USD"),  # 4  over policy
    ("Daily Bean", 14, "Meals", 6.75, "USD"),  # 5
    ("Pita Place", 19, "Meals", 31.20, "USD"),  # 6
    ("Bistro Nord", 23, "Meals", 75.00, "USD"),  # 7  exactly 75, NOT over
    ("Sunrise Bakery", 27, "Meals", 12.90, "USD"),  # 8
    ("Metro Rail Pass", 3, "Travel", 54.00, "USD"),  # 9
    ("SkyJet Airlines", 10, "Travel", 312.80, "USD"),  # 10
    ("Berlin Hotel Am Park", 15, "Travel", 120.00, "EUR"),  # 11 euro trap
    ("City Cab", 16, "Travel", 28.50, "USD"),  # 12
    ("Park & Ride", 21, "Travel", 15.00, "USD"),  # 13
    ("CloudNotes Pro", 1, "Software", 49.00, "USD"),  # 14
    ("DevTools License", 6, "Software", 129.00, "USD"),  # 15
    ("DataSync Subscription", 18, "Software", 79.99, "USD"),  # 16
    ("ScreenCast Plan", 25, "Software", 19.00, "USD"),  # 17
    ("PaperWorks Supplies", 4, "Office", 63.25, "USD"),  # 18
    ("Desk & Chair Depot", 11, "Office", 214.90, "USD"),  # 19
    ("PrintHub", 13, "Office", 38.40, "USD"),  # 20
    ("PaperWorks Supplies", 4, "Office", 63.25, "USD"),  # 21 duplicate of 18
    ("Ink Station", 24, "Office", 44.10, "USD"),  # 22
    ("Courier Express", 8, "Other", 22.00, "USD"),  # 23
    ("Conference Parking", 20, "Other", 9.50, "USD"),  # 24
]

DUPLICATE_ORIGINAL = 18
DUPLICATE_COPY = 21
EURO_RECEIPT = 11
CATEGORIES = ["Meals", "Travel", "Software", "Office", "Other"]


def file_name(number: int) -> str:
    return f"receipt_{number:02d}.txt" if _style(number) != "C" else f"receipt_{number:02d}.csv"


def _style(number: int) -> str:
    """Layout letter A to D. The euro receipt is forced to layout A."""
    if number == EURO_RECEIPT:
        return "A"
    return "ABCD"[(number - 1) % 4]


def _render(number: int) -> str:
    vendor, day, category, amount, currency = RECEIPTS[number - 1]
    when = date(2026, 3, day)
    style = _style(number)
    if style == "A":
        return (
            f"Vendor: {vendor}\nDate: {when.isoformat()}\nCategory: {category}\n"
            f"Amount: {amount:.2f} {currency}\n"
        )
    if style == "B":
        return (
            f"*** RECEIPT ***\n{vendor}\nDate: {when.strftime('%m/%d/%Y')}\n"
            f"Category: {category}\nTotal: ${amount:.2f}\nThank you!\n"
        )
    if style == "C":
        return (
            "vendor,date,category,amount,currency\n"
            f"{vendor},{when.isoformat()},{category},{amount:.2f},{currency}\n"
        )
    return (
        f"Paid ${amount:.2f} to {vendor} on {when.strftime('%B')} {when.day}, {when.year}. "
        f"Category: {category}.\n"
    )


def usd_amount(number: int) -> float:
    """The amount of one receipt in USD (euros converted at the stated rate)."""
    _, _, _, amount, currency = RECEIPTS[number - 1]
    return round(amount * EUR_RATE, 2) if currency == "EUR" else amount


def build_answer_key() -> dict:
    """What a perfect report contains. Duplicates are counted once."""
    totals = {name: 0.0 for name in CATEGORIES}
    for number in range(1, len(RECEIPTS) + 1):
        if number == DUPLICATE_COPY:
            continue
        category = RECEIPTS[number - 1][2]
        totals[category] += usd_amount(number)
    over_policy = [
        file_name(n)
        for n in range(1, len(RECEIPTS) + 1)
        if RECEIPTS[n - 1][2] == "Meals" and usd_amount(n) > MEAL_LIMIT
    ]
    meals = [n for n in range(1, len(RECEIPTS) + 1) if RECEIPTS[n - 1][2] == "Meals"]
    return {
        "receipt_count": len(RECEIPTS),
        "eur_rate": EUR_RATE,
        "totals": {name: round(value, 2) for name, value in totals.items()},
        "over_policy_files": over_policy,
        "meal_files": [file_name(n) for n in meals],
        "duplicate_original": file_name(DUPLICATE_ORIGINAL),
        "duplicate_copy": file_name(DUPLICATE_COPY),
    }


def write_all(receipts_dir: Path = RECEIPTS_SRC, key_path: Path = ANSWER_KEY) -> None:
    """Write the receipts folder and the answer key to disk."""
    receipts_dir.mkdir(parents=True, exist_ok=True)
    for old in receipts_dir.glob("receipt_*"):
        old.unlink()
    for number in range(1, len(RECEIPTS) + 1):
        (receipts_dir / file_name(number)).write_text(_render(number), encoding="utf-8")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key_path.write_text(json.dumps(build_answer_key(), indent=2) + "\n", encoding="utf-8")


def load_answer_key(key_path: Path = ANSWER_KEY) -> dict:
    return json.loads(key_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    write_all()
    print(f"Wrote {len(RECEIPTS)} receipts to {RECEIPTS_SRC} and the answer key to {ANSWER_KEY}")
