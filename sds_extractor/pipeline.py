"""Run the extraction over a folder of PDFs and write results, logs and run info.

Each run writes to its own folder, runs/<timestamp>_<mode>/, containing
results.json, results.csv, run.log and run_info.json, so a new run never
overwrites an earlier one.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import platform
import re
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import __version__
from .llm import PROMPT_VERSION, LLMClient, is_grounded
from .parse import find_section, header_text, read_pdf_pages
from .rules import (
    extract_hazard_codes,
    extract_page_identifier,
    extract_revision_date_raw,
    extract_trade_name,
    normalize_date,
)

log = logging.getLogger("sds_extractor")

Source = Literal["rule", "llm", "rule+llm"]
Status = Literal["ok", "needs_review", "error"]


class SDSRecord(BaseModel):
    """One output row per SDS document (the schema for MDM import)."""

    document_id: str
    source_file: str
    file_sha256: str
    trade_name: str | None = None
    trade_name_source: Source | None = None
    # Description printed in the page header/footer when it differs from the
    # trade name in section 1.1 (the page and the text layer can disagree).
    trade_name_as_displayed: str | None = None
    revision_date: str | None = Field(default=None, description="dd/mm/yyyy")
    revision_date_source: Source | None = None
    # "" means section 2.2 was found and lists no codes; None means it could not be read.
    hazard_statements: str | None = Field(default=None, description="comma-separated H/EUH codes")
    status: Status = "ok"
    warnings: list[str] = Field(default_factory=list)
    # What the LLM proposed before any check (date normalised when possible),
    # kept so the LLM can be evaluated on its own. None when no LLM was used.
    llm_trade_name: str | None = None
    llm_revision_date: str | None = None


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def reconcile(
    field: str, rule_value: str | None, llm_value: str | None, warnings: list[str]
) -> tuple[str | None, Source | None, bool]:
    """Combine the rule and LLM values. Returns (value, source, needs_review)."""
    if rule_value and llm_value:
        if _same(rule_value, llm_value):
            return rule_value, "rule+llm", False
        warnings.append(
            f"{field}: rule found {rule_value!r} but LLM found {llm_value!r}; kept the rule value"
        )
        return rule_value, "rule", True
    if rule_value:
        return rule_value, "rule", False
    if llm_value:
        return llm_value, "llm", False
    warnings.append(f"{field}: not found")
    return None, None, True


MAX_LLM_CHARS = 4000


def llm_context(text: str, pages: list[str], section_1_1: str) -> str:
    """Text sent to the LLM: the document header plus section 1.1.

    Normally that is everything from the start of the document to the end of
    section 1.1 (the header holds the revision date). If that is unexpectedly
    long, fall back to the top of page 1 plus section 1.1.
    """
    start = text.find(section_1_1)
    end = start + len(section_1_1) if start >= 0 else 0
    if 0 < end <= MAX_LLM_CHARS:
        return text[:end]
    return header_text(pages) + "\n\n" + section_1_1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_document(path: Path, llm: LLMClient | None = None) -> SDSRecord:
    doc = path.stem
    record = SDSRecord(document_id=doc, source_file=path.name, file_sha256=_sha256(path))
    warnings = record.warnings
    review = False

    try:
        pages = read_pdf_pages(path)
    except Exception as exc:  # corrupt or encrypted PDF
        log.error("[%s] could not read PDF: %s", doc, exc)
        warnings.append(f"could not read PDF: {exc}")
        record.status = "error"
        return record
    text = "\n".join(pages)
    if not text.strip():
        log.error("[%s] no extractable text (scanned PDF? OCR is not supported)", doc)
        warnings.append("no extractable text (scanned PDF?)")
        record.status = "error"
        return record
    log.debug("[%s] %d pages, %d characters", doc, len(pages), len(text))

    # --- Section 1.1 and header ---------------------------------------------
    section_1_1 = find_section(text, "1.1", ["1.2", "1.3"])
    if section_1_1 is None:
        warnings.append("section 1.1 not found; searched the first page instead")
        log.warning("[%s] section 1.1 not found; using first page", doc)
        section_1_1 = pages[0]

    rule_name, name_match = extract_trade_name(section_1_1)
    log.info("[%s] trade_name (rule): %s", doc, f"{rule_name!r} from {name_match!r}" if rule_name else "no label matched")

    raw_date, date_match = extract_revision_date_raw(text)
    rule_date = normalize_date(raw_date) if raw_date else None
    if raw_date and not rule_date:
        warnings.append(f"revision_date: {raw_date!r} is not a valid date")
        review = True
    log.info("[%s] revision_date (rule): %s", doc, f"{rule_date} from {date_match!r}" if rule_date else "no label matched")

    # --- Section 2.2: hazard statements (rules only) -------------------------
    section_2_2 = find_section(text, "2.2", ["2.3", "3.1", "3.2"])
    if section_2_2 is None:
        warnings.append("section 2.2 not found: hazard statements not extracted")
        log.error("[%s] section 2.2 (label elements) not found", doc)
        record.status = "error"
    else:
        codes = extract_hazard_codes(section_2_2)
        record.hazard_statements = ", ".join(codes)
        log.info("[%s] hazard_statements (section 2.2): %s", doc, record.hazard_statements or "none")
        if not codes:
            warnings.append("section 2.2 found but lists no H/EUH codes")

    # --- Optional LLM for the free-text fields -------------------------------
    llm_name = llm_date = None
    if llm is not None:
        llm_input = llm_context(text, pages, section_1_1)
        try:
            proposal = llm.extract(llm_input)
            log.info("[%s] LLM proposed: %s", doc, proposal.model_dump())
            record.llm_trade_name = proposal.trade_name
            if proposal.revision_date:
                record.llm_revision_date = normalize_date(proposal.revision_date) or proposal.revision_date
        except Exception as exc:
            proposal = None
            warnings.append(f"LLM call failed: {exc.__class__.__name__}: {exc}")
            log.warning("[%s] LLM call failed: %s", doc, exc)
        if proposal and proposal.trade_name:
            if is_grounded(proposal.trade_name, section_1_1):
                llm_name = proposal.trade_name.strip()
            else:
                warnings.append(f"trade_name: LLM value {proposal.trade_name!r} is not in section 1.1; rejected")
                log.warning("[%s] rejected ungrounded LLM trade_name %r", doc, proposal.trade_name)
        if proposal and proposal.revision_date:
            normalized = normalize_date(proposal.revision_date)
            if normalized and is_grounded(proposal.revision_date, llm_input):
                llm_date = normalized
            else:
                warnings.append(f"revision_date: LLM value {proposal.revision_date!r} is not a valid date in the text; rejected")
                log.warning("[%s] rejected LLM revision_date %r", doc, proposal.revision_date)

    record.trade_name, record.trade_name_source, flag_name = reconcile("trade_name", rule_name, llm_name, warnings)
    record.revision_date, record.revision_date_source, flag_date = reconcile("revision_date", rule_date, llm_date, warnings)

    # --- Page header vs section 1.1 ------------------------------------------
    displayed = extract_page_identifier(pages)
    if displayed and record.trade_name:
        a, b = " ".join(displayed.split()).casefold(), " ".join(record.trade_name.split()).casefold()
        if a not in b and b not in a:
            record.trade_name_as_displayed = displayed
            flag_name = True
            warnings.append(
                f"trade_name: section 1.1 reads {record.trade_name!r} but the page header/footer shows "
                f"{displayed!r}; the page may display a different name than the text layer. Confirm which is the master"
            )
            log.warning("[%s] trade name differs from page header/footer: %r vs %r", doc, record.trade_name, displayed)

    if record.status != "error" and (review or flag_name or flag_date):
        record.status = "needs_review"
    log.info("[%s] status=%s%s", doc, record.status, f" warnings={warnings}" if warnings else "")
    return record


def _package_versions() -> dict[str, str]:
    versions = {}
    for package in ("pypdf", "pydantic", "requests"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = "not installed"
    return versions


def _setup_logging(log_file: Path) -> list[logging.Handler]:
    log.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    for handler in (file_handler, console):
        handler.setFormatter(formatter)
        log.addHandler(handler)
    return [file_handler, console]


def write_results(records: list[SDSRecord], run_dir: Path) -> None:
    rows = [r.model_dump() for r in records]
    (run_dir / "results.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    # utf-8-sig so Excel shows characters such as "ë" correctly.
    with open(run_dir / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(SDSRecord.model_fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "warnings": "; ".join(row["warnings"])})


def run(
    input_dir: Path,
    out_root: Path,
    llm: LLMClient | None = None,
    llm_unavailable: str | None = None,
) -> Path:
    """Process every PDF in `input_dir`; return the folder the run was written to."""
    started = datetime.now(timezone.utc)
    mode = "rules"
    if llm is not None:
        mode = "llm-" + re.sub(r"[^A-Za-z0-9.-]+", "-", llm.describe().get("model", "model"))
    run_id = f"{started.astimezone():%Y%m%d-%H%M%S}_{mode}_{input_dir.resolve().name}"
    run_dir = out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    handlers = _setup_logging(run_dir / "run.log")

    try:
        pdfs = sorted(p for p in input_dir.iterdir() if p.suffix.lower() == ".pdf")
        log.info("run %s: %d PDF(s) in %s, mode=%s", run_id, len(pdfs), input_dir, mode)
        if llm_unavailable:
            log.warning("LLM requested but not used: %s. Continuing with rules only.", llm_unavailable)

        records = [process_document(pdf, llm) for pdf in pdfs]
        write_results(records, run_dir)

        status_counts = {s: sum(r.status == s for r in records) for s in ("ok", "needs_review", "error")}
        run_info = {
            "run_id": run_id,
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mode": mode,
            "input_dir": str(input_dir),
            "documents": [p.name for p in pdfs],
            "status_counts": status_counts,
            "pipeline_version": __version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "packages": _package_versions(),
            "llm": llm.describe() if llm is not None else None,
            "llm_unavailable_reason": llm_unavailable,
            "prompt_version": PROMPT_VERSION if llm is not None else None,
        }
        (run_dir / "run_info.json").write_text(json.dumps(run_info, indent=2) + "\n", encoding="utf-8")
        log.info("done: %s -> %s", status_counts, run_dir)
    finally:
        for handler in handlers:
            log.removeHandler(handler)
            handler.close()
    return run_dir
