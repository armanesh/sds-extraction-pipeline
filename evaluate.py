"""Compare a run's results.json with the hand-checked answers in data/gold.json.

Usage: python evaluate.py runs/<run_id>/results.json

Trade name and revision date are scored as exact matches. Hazard statements are
a set of codes, so they get precision (were the codes we reported correct?) and
recall (did we find every code?). For safety data, low recall is the worst
error: a missed code is a hazard the fire department would not know about.

For runs with --llm, the LLM's own proposals (before guardrails and
reconciliation) are scored as well, to show what the LLM achieves on its own.
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


def _mark(ok: bool | None) -> str:
    return "—" if ok is None else ("✓" if ok else "✗")


def evaluate(results_path: Path) -> str:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))["documents"]
    results = json.loads(results_path.read_text(encoding="utf-8"))
    scored = [r for r in results if r["document_id"] in gold]
    llm_used = any(r.get("llm_trade_name") or r.get("llm_revision_date") for r in scored)

    lines = [
        f"Evaluation of `{results_path.parent.name}` against `data/gold.json`",
        "",
        "| document | trade name | revision date | hazard precision | hazard recall | status | LLM alone: name | LLM alone: date |",
        "|---|---|---|---|---|---|---|---|",
    ]
    t = {"name": 0, "date": 0, "tp": 0, "pred": 0, "true": 0, "llm_name": 0, "llm_date": 0}
    for got in scored:
        expected = gold[got["document_id"]]
        name_ok = got.get("trade_name") == expected["trade_name"]
        date_ok = got.get("revision_date") == expected["revision_date"]
        predicted, true = _codes(got.get("hazard_statements")), set(expected["hazard_statements"])
        tp = len(predicted & true)
        llm_name_ok = got.get("llm_trade_name") == expected["trade_name"] if llm_used else None
        llm_date_ok = got.get("llm_revision_date") == expected["revision_date"] if llm_used else None
        t["name"] += name_ok
        t["date"] += date_ok
        t["tp"] += tp
        t["pred"] += len(predicted)
        t["true"] += len(true)
        t["llm_name"] += bool(llm_name_ok)
        t["llm_date"] += bool(llm_date_ok)
        lines.append(
            f"| {got['document_id']} | {_mark(name_ok)} | {_mark(date_ok)} "
            f"| {_ratio(tp, len(predicted))} | {_ratio(tp, len(true))} | {got.get('status')} "
            f"| {_mark(llm_name_ok)} | {_mark(llm_date_ok)} |"
        )
    n = len(scored)
    llm_totals = f"{t['llm_name']}/{n} | {t['llm_date']}/{n}" if llm_used else "— | —"
    lines.append(
        f"| **total** | {t['name']}/{n} | {t['date']}/{n} "
        f"| {_ratio(t['tp'], t['pred'])} | {_ratio(t['tp'], t['true'])} | | {llm_totals} |"
    )
    unscored = len(results) - n
    lines += ["", f"{n} document(s) scored" + (f", {unscored} without expected values" if unscored else "")
              + ": a correctness check on the samples, not an accuracy estimate."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = Path(sys.argv[1])
    report = evaluate(path)
    (path.parent / "evaluation.md").write_text(report, encoding="utf-8")
    sys.stdout.reconfigure(errors="replace")
    print(report)
