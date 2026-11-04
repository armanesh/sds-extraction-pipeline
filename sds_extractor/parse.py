"""Turn a PDF into text and locate the SDS sections we need.

SDSs follow the 16-section structure required by REACH (EC 1907/2006), so
sections are found by their number ("1.1", "2.2"), which is the same in every
language, instead of by their translated headings.
"""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader


def read_pdf_pages(path: Path) -> list[str]:
    """Return the extracted text of each page (empty string for pages without text)."""
    reader = PdfReader(path)
    return [page.extract_text() or "" for page in reader.pages]


def _heading(number: str) -> re.Pattern[str]:
    # A line that starts with the section number, optionally preceded by a
    # bullet such as "·" and followed by an optional dot, e.g.
    # "· 2.2 Etiketteringselementen" or "2.2. Etiketteringselementen".
    # "2.2.1" does not match because the number must be followed by whitespace.
    return re.compile(rf"^\W*{re.escape(number)}\.?\s", re.MULTILINE)


def find_section(text: str, number: str, next_numbers: list[str]) -> str | None:
    """Return the text from heading `number` up to the first of `next_numbers`.

    Returns None if the section start, or every possible end, is missing, so the
    caller never silently reads past the section (e.g. into the ingredient list
    of section 3, which also contains H-codes).
    """
    start = _heading(number).search(text)
    if not start:
        return None
    rest = text[start.end():]
    ends = [m.start() for n in next_numbers if (m := _heading(n).search(rest))]
    if not ends:
        return None
    return text[start.start(): start.end() + min(ends)]


def header_text(pages: list[str], max_chars: int = 600) -> str:
    """Top of the first page, where the revision date is usually printed."""
    return pages[0][:max_chars] if pages else ""
