import pytest

from sds_extractor.parse import find_section
from sds_extractor.rules import extract_hazard_codes, extract_page_identifier, normalize_date


def test_hazard_codes_glued_to_text_are_found():
    # pypdf returns "H225Licht ..." without a space for some layouts; an earlier
    # version of the pattern (with a word boundary) silently missed these.
    assert extract_hazard_codes("H225Licht ontvlambare\nH319Veroorzaakt") == ["H225", "H319"]


def test_hazard_codes_ignore_p_codes_and_longer_numbers():
    text = "P210 Verwijderd houden. H2250 x. EUH066 Herhaalde. H300+H310 Fataal. EUH066"
    assert extract_hazard_codes(text) == ["EUH066", "H300", "H310"]


def test_hazard_code_letter_suffix_is_kept_but_glued_words_are_not():
    text = "H361f Wordt. H360FD Kan. H350i Kan. H361fWordt. H300Fatal if swallowed. H226Flammable. H225Licht"
    assert extract_hazard_codes(text) == ["H361f", "H360FD", "H350i", "H300", "H226", "H225"]


def test_page_identifier_needs_to_repeat_on_the_next_pages():
    line = "6305943 - BIS CONTACT KIT TR BD 100ML*6 NLFR"
    assert extract_page_identifier([line + "\nx", "y\n" + line]) == "BIS CONTACT KIT TR BD 100ML*6 NLFR"
    assert extract_page_identifier(["1234 - only once\nx", "y"]) is None
    assert extract_page_identifier(["no identifier here"]) is None


def test_section_2_2_stops_before_component_codes_in_section_3():
    text = "· 2.2 Etiketteringselementen\nH225 ...\n· 2.3 Andere gevaren\n· 3.2 Mengsels\nCarc. 2, H351\n"
    section = find_section(text, "2.2", ["2.3", "3.1", "3.2"])
    assert extract_hazard_codes(section) == ["H225"]


def test_missing_section_end_returns_none_instead_of_reading_on():
    assert find_section("2.2 Label elements\nH225\n(no further headings)", "2.2", ["2.3"]) is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("15.07.2026", "15/07/2026"),
        ("21-7-2026", "21/07/2026"),
        ("1/2/2026", "01/02/2026"),
        ("2026-04-20", "20/04/2026"),
        ("31.02.2026", None),  # not a real date
        ("July 2026", None),
    ],
)
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected
