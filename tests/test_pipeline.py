"""End-to-end tests on the three sample SDSs.

The LLM tests use a fake client with fixed answers, so they check how the
pipeline treats LLM output (guardrails, reconciliation) without needing Ollama.
"""

import json
from pathlib import Path

import pytest

from sds_extractor.llm import LLMExtraction, OllamaClient
from sds_extractor.pipeline import process_document, reconcile

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "data" / "input"
EXTRA = ROOT / "data" / "extra"
GOLD = json.loads((ROOT / "data" / "gold.json").read_text(encoding="utf-8"))["documents"]


class FakeLLM:
    def __init__(self, trade_name=None, revision_date=None):
        self.answer = LLMExtraction(trade_name=trade_name, revision_date=revision_date)

    def extract(self, text):
        return self.answer

    def describe(self):
        return {"provider": "fake", "model": "fake"}


@pytest.mark.parametrize("doc_id", sorted(p.stem for p in INPUT.glob("*.pdf")))
def test_rules_match_gold(doc_id):
    record = process_document(INPUT / f"{doc_id}.pdf")
    expected = GOLD[doc_id]
    assert record.trade_name == expected["trade_name"]
    assert record.revision_date == expected["revision_date"]
    assert record.hazard_statements == ", ".join(expected["hazard_statements"])
    if "trade_name_as_displayed" in expected:
        # The page shows the article description over the name in the text layer.
        assert record.trade_name_as_displayed == expected["trade_name_as_displayed"]
        assert record.status == "needs_review"
        assert any("page header/footer" in w for w in record.warnings)
    else:
        assert record.trade_name_as_displayed is None
        assert record.status == "ok"


def test_llm_agreement_is_recorded():
    record = process_document(
        INPUT / "assSDS-128374293.pdf",
        FakeLLM(trade_name="BISON KIT TRANSPARANT", revision_date="20.04.2026"),
    )
    assert record.trade_name_source == "rule+llm"
    assert record.revision_date_source == "rule+llm"
    # Agreement does not clear the page-vs-text-layer conflict on the trade name.
    assert record.status == "needs_review"


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


def test_llm_proposals_are_kept_for_evaluation():
    record = process_document(
        INPUT / "assSDS-123006278.pdf",
        FakeLLM(trade_name="Kroon-Oil Fuel Optimix 2T", revision_date="21-7-2026"),
    )
    assert record.llm_trade_name == "Kroon-Oil Fuel Optimix 2T"
    assert record.llm_revision_date == "21/07/2026"


def test_llm_value_is_used_when_the_rules_find_nothing():
    # e.g. a label in a language the rules do not know
    warnings = []
    value, source, needs_review = reconcile("trade_name", None, "Sekundenkleber", warnings)
    assert (value, source, needs_review, warnings) == ("Sekundenkleber", "llm", False, [])


def test_llm_fills_fields_the_rules_cannot_read_in_a_german_sds():
    # The German SDS has no "name:" label and dates "Überarbeitet am", so the
    # rules find neither field; grounded LLM values are used instead.
    path = EXTRA / "de-liquimate-2k-power-kleber.pdf"
    rules_only = process_document(path)
    assert (rules_only.trade_name, rules_only.revision_date, rules_only.status) == (None, None, "needs_review")
    record = process_document(path, FakeLLM(trade_name="Liquimate 2K Power Kleber (A)", revision_date="25.10.2023"))
    assert (record.trade_name, record.trade_name_source) == ("Liquimate 2K Power Kleber (A)", "llm")
    assert (record.revision_date, record.revision_date_source, record.status) == ("25/10/2023", "llm", "ok")
