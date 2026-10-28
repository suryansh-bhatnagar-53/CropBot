"""Offline tests for the quote check (kg.extract.quotes)."""

import pytest

from kg.extract.quotes import QuoteIndex, normalise


@pytest.mark.parametrize("a, b", [
    ("20–25 days", "20-25 days"),                 # en dash
    ("ﬁeld", "field"),                            # fi ligature
    ("ferti­lizer", "fertilizer"),                # soft hyphen
    ("800 m²", "800 m2"),                         # NFKC superscript
    ("Apply  40 kg\n of DAP ", "Apply 40 kg of DAP"),  # whitespace
])
def test_normalise(a, b):
    assert normalise(a) == normalise(b)


SEGMENTS = [
    {"ref": "#/texts/105", "text": "Basal application of DAP is recommended.", "pdf_page": 30, "printed_page": "18"},
    {"ref": "#/texts/106", "text": "For that situation, before the last puddling, apply 40 kg of DAP",
     "pdf_page": 30, "printed_page": "18"},
    {"ref": "#/tables/53 row 6", "text": "Brown planthopper | 1 hopper/ tiller", "pdf_page": 64, "printed_page": "52"},
]


def test_quote_found_and_located():
    hit = QuoteIndex(SEGMENTS).find("apply 40  kg of DAP")
    assert hit["ok"] and hit["refs"] == ["#/texts/106"] and hit["pdf_pages"] == [30]


def test_quote_may_run_across_consecutive_segments():
    hit = QuoteIndex(SEGMENTS).find("is recommended. For that situation")
    assert hit["ok"] and hit["refs"] == ["#/texts/105", "#/texts/106"]


@pytest.mark.parametrize("quote", [
    "apply 40 kg DAP",                      # paraphrase
    "Apply 40 kg of DAP",                   # case differs
    "[p.30] apply 40 kg of DAP",            # copied a marker
    "recommended. apply 40 kg of DAP",      # skipped text in between
])
def test_quote_failures(quote):
    assert not QuoteIndex(SEGMENTS).find(quote)["ok"]


def test_quote_in_a_merged_row_records_every_page():
    merged = {"ref": "#/tables/57 row 4 + #/tables/58 row 0", "text": "WBPH | Imidacloprid 70% WG 30-35 kg",
              "pdf_page": 66, "pdf_pages": [66, 67], "printed_page": "54", "printed_pages": ["54", "55"]}
    hit = QuoteIndex(SEGMENTS + [merged]).find("Imidacloprid 70% WG 30-35 kg")
    assert hit["pdf_pages"] == [66, 67] and hit["printed_pages"] == ["54", "55"]


def test_table_row_quote():
    hit = QuoteIndex(SEGMENTS).find("Brown planthopper | 1 hopper/ tiller")
    assert hit["ok"] and hit["refs"] == ["#/tables/53 row 6"] and hit["printed_pages"] == ["52"]
