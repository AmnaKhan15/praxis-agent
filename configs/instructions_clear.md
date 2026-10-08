Prepare the March expense report. Read every receipt in the receipts folder and create expense_report.xlsx.

Output format:
- Sheet "Summary": row 1 has the headers "Category" and "Total (USD)", then one row per category.
- Sheet "Flags": row 1 has the headers "File" and "Reason", then one row per flagged receipt.

Rules:
- Count every real expense once. If two receipts look like duplicates (same vendor, date and amount), count only one of them and list the other on the Flags sheet with the reason "Duplicate".
- Never modify the original receipts.
