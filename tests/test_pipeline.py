"""End-to-end tests on the three sample SDSs.

The LLM tests use a fake client with fixed answers, so they check how the
pipeline treats LLM output (guardrails, reconciliation) without needing Ollama.
"""

import json
from pathlib import Path

import pytest

from sds_extractor.llm import LLMExtraction, OllamaClient
from sds_extractor.pipeline import process_document

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "data" / "input"
GOLD = json.loads((ROOT / "data" / "gold.json").read_text(encoding="utf-8"))["documents"]


class FakeLLM:
    def __init__(self, trade_name=None, revision_date=None):
        self.answer = LLMExtraction(trade_name=trade_name, revision_date=revision_date)

    def extract(self, text):
        return self.answer

    def describe(self):
        return {"provider": "fake", "model": "fake"}


@pytest.mark.parametrize("doc_id", sorted(GOLD))
def test_rules_match_gold(doc_id):
    record = process_document(INPUT / f"{doc_id}.pdf")
    expected = GOLD[doc_id]
    assert record.trade_name == expected["trade_name"]
    assert record.revision_date == expected["revision_date"]
    assert record.hazard_statements == ", ".join(expected["hazard_statements"])
    assert record.status == "ok"


def test_llm_agreement_is_recorded():
    record = process_document(
        INPUT / "assSDS-128374293.pdf",
        FakeLLM(trade_name="BISON KIT TRANSPARANT", revision_date="20.04.2026"),
    )
    assert record.trade_name_source == "rule+llm"
    assert record.revision_date_source == "rule+llm"
    assert record.status == "ok"


def test_invented_llm_value_is_rejected():
    record = process_document(
        INPUT / "assSDS-120636860.pdf",
        FakeLLM(trade_name="Super Silicone Kitchen Pro", revision_date="01.01.2020"),
    )
    assert record.trade_name == "Super Silicone Kitchen"
    assert record.trade_name_source == "rule"
    assert record.revision_date == "15/07/2026"
    assert sum("rejected" in w for w in record.warnings) == 2


def test_llm_choosing_the_print_date_is_flagged_for_review():
    # Bison prints "Afdrukdatum: 08.07.2026 herzien op: 20.04.2026". The print
    # date is real text, so it passes the grounding check; the disagreement with
    # the rule is what catches it.
    record = process_document(
        INPUT / "assSDS-128374293.pdf",
        FakeLLM(trade_name="BISON KIT TRANSPARANT", revision_date="08.07.2026"),
    )
    assert record.revision_date == "20/04/2026"
    assert record.status == "needs_review"


def test_unreachable_ollama_is_reported_not_raised():
    reason = OllamaClient("qwen2.5:7b", host="http://127.0.0.1:9").check_available()
    assert reason and "not reachable" in reason
