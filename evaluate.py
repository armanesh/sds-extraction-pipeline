"""Compare a run's results.json with the hand-checked answers in data/gold.json.

Usage: python evaluate.py runs/<run_id>/results.json

Trade name and revision date are scored as exact matches. Hazard statements are
a set of codes, so they get precision (were the codes we reported correct?) and
recall (did we find every code?). For safety data, low recall is the worst
error: a missed code is a hazard the fire department would not know about.
The table is printed and saved as evaluation.md next to results.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

GOLD = Path(__file__).parent / "data" / "gold.json"


def _codes(value: str | None) -> set[str]:
    return {c.strip() for c in (value or "").split(",") if c.strip()}


def _ratio(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator}" if denominator else "n/a"


def evaluate(results_path: Path) -> str:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))["documents"]
    results = {r["document_id"]: r for r in json.loads(results_path.read_text(encoding="utf-8"))}

    lines = [
        f"Evaluation of `{results_path.parent.name}` against `data/gold.json`",
        "",
        "| document | trade name | revision date | hazard precision | hazard recall | status |",
        "|---|---|---|---|---|---|",
    ]
    totals = {"name": 0, "date": 0, "tp": 0, "pred": 0, "true": 0}
    for doc_id, expected in gold.items():
        got = results.get(doc_id, {})
        name_ok = got.get("trade_name") == expected["trade_name"]
        date_ok = got.get("revision_date") == expected["revision_date"]
        predicted, true = _codes(got.get("hazard_statements")), set(expected["hazard_statements"])
        tp = len(predicted & true)
        totals["name"] += name_ok
        totals["date"] += date_ok
        totals["tp"] += tp
        totals["pred"] += len(predicted)
        totals["true"] += len(true)
        lines.append(
            f"| {doc_id} | {'✓' if name_ok else '✗'} | {'✓' if date_ok else '✗'} "
            f"| {_ratio(tp, len(predicted))} | {_ratio(tp, len(true))} | {got.get('status', 'missing')} |"
        )
    n = len(gold)
    lines.append(
        f"| **total** | {totals['name']}/{n} | {totals['date']}/{n} "
        f"| {_ratio(totals['tp'], totals['pred'])} | {_ratio(totals['tp'], totals['true'])} | |"
    )
    lines += ["", f"Only {n} documents: this checks correctness on the samples, it is not an accuracy estimate."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = Path(sys.argv[1])
    report = evaluate(path)
    (path.parent / "evaluation.md").write_text(report, encoding="utf-8")
    sys.stdout.reconfigure(errors="replace")
    print(report)
