"""Deterministic extraction rules (the baseline)."""

from __future__ import annotations

import re
from datetime import date

# Labels named in the assignment plus the Dutch variants used by the sample SDSs.
TRADE_NAME_LABELS = ["Handelsnaam", "Trade name", "Product name", "Productnaam"]
REVISION_DATE_LABELS = [
    "Datum herziening",
    "Herzien op",
    "Revisiedatum",
    "Revision date",
    "Date of revision",
]

# "H" or "EUH" followed by exactly three digits, plus the CLP letter suffix that
# some H-codes carry (H361f, H360FD, H350i). Dropping the suffix would change
# the meaning (H361f = fertility, H361d = unborn child), so it is kept.
# The code may be glued to the following word ("H225Licht" in some text
# extractions), so we only require that no letter/digit precedes it and no digit
# follows it. A suffix letter directly followed by a lowercase letter is part of
# a glued word, not a suffix ("H300Fatal" is H300, "H361fWordt" is H361f).
HAZARD_CODE = re.compile(
    r"(?<![A-Za-z0-9])(?:EUH\d{3}|H\d{3}(?:[FfDdi]{1,2}(?![a-z]))?)(?!\d)"
)

# Running header or footer printed on each page: "<article number> - <description>".
PAGE_IDENTIFIER = re.compile(r"^\s*(\d{4,})\s+-\s+(\S.*?)\s*$", re.MULTILINE)

_DATE_VALUE = r"(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{2}-\d{2})"


def _labels(labels: list[str]) -> str:
    return "|".join(re.escape(label) for label in labels)


def extract_trade_name(section_1_1: str) -> tuple[str | None, str | None]:
    """Return (trade name, matched line). Only the text on the label's line is
    taken; the next line may be an internal article code or the UFI."""
    pattern = rf"(?:{_labels(TRADE_NAME_LABELS)})\s*:\s*([^\n]+)"
    match = re.search(pattern, section_1_1, re.IGNORECASE)
    if not match:
        return None, None
    return match.group(1).strip(), match.group(0).strip()


def extract_revision_date_raw(text: str) -> tuple[str | None, str | None]:
    """Return (date as written, matched text) for the first revision-date label."""
    pattern = rf"(?:{_labels(REVISION_DATE_LABELS)})\s*:?\s*{_DATE_VALUE}"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None, None
    return match.group(1), match.group(0).strip()


def normalize_date(raw: str) -> str | None:
    """Convert a European day-first date (or ISO yyyy-mm-dd) to dd/mm/yyyy.

    Returns None for anything that is not a real calendar date.
    """
    raw = raw.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            year, month, day = (int(p) for p in raw.split("-"))
        else:
            parts = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", raw)
            if not parts:
                return None
            day, month, year = (int(p) for p in parts.groups())
        return date(year, month, day).strftime("%d/%m/%Y")
    except ValueError:
        return None


def extract_hazard_codes(section_2_2: str) -> list[str]:
    """All H/EUH codes in section 2.2, de-duplicated, in document order."""
    return list(dict.fromkeys(HAZARD_CODE.findall(section_2_2)))


def extract_page_identifier(pages: list[str]) -> str | None:
    """Description from a "<number> - <description>" line that repeats on the
    first pages (a running header or footer), or None.

    Some suppliers print their article description here. It can differ from the
    name in section 1.1, so the pipeline compares the two.
    """
    if not pages:
        return None
    for match in PAGE_IDENTIFIER.finditer(pages[0]):
        line = match.group(0).strip()
        if len(pages) == 1 or any(line in page for page in pages[1:3]):
            return match.group(2)
    return None
