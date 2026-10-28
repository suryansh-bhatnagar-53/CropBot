"""Verified page transcriptions (kg.transcribe): the committed DFPD p. 6 file (approved by the user on
2026-10-23), the approval gate, and what an approved transcription changes downstream (segmentation, tables,
quote checks, SourceSpans). Every other status is simulated on a copy in a temporary folder."""

import datetime as dt
import json
import re

import pytest
from pydantic import ValidationError

from kg.convert import output_dir
from kg.registry import read_entry
from kg.schema.core import SourceSpan
from kg.transcribe import (TranscriptionError, body_sha256, for_source, parse_body, read, rehash, source_dir)

ENTRY = read_entry("source:dfpd_uniform_spec_kms_2026_27")
P006 = source_dir(ENTRY) / "p006.md"
TODAY = dt.date(2026, 10, 23)
DOCLING = output_dir(ENTRY)
needs_conversion = pytest.mark.skipif(not (DOCLING / "document.json").exists(),
                                      reason="needs the DFPD conversion in data/docling/")


def copy_with(tmp_path, status="approved", checked_by="TEST REVIEWER", checked_at="2026-10-22", edit_body=None):
    """A copy of the committed p006.md with these header values (and an optional text replacement)."""
    d = tmp_path / "tr"
    d.mkdir(parents=True)
    text = P006.read_text(encoding="utf-8")
    for key, value in (("status", status), ("checked_by", checked_by), ("checked_at", checked_at)):
        text = re.sub(r'(?m)^%s = ".*"$' % key, '%s = "%s"' % (key, value), text, count=1)
    if edit_body:
        text = text.replace(*edit_body)
    (d / "p006.md").write_text(text, encoding="utf-8", newline="\n")
    return d


def approved_copy(tmp_path, **kw):
    return copy_with(tmp_path, "approved", **kw)


# --- the committed transcription ---------------------------------------------------------------------------

def test_the_committed_p006_is_approved_hashed_and_as_printed():
    t = read(P006)
    h = t.header
    assert (h.source_id, h.pdf_page, h.pdf_sha256, h.rendered_dpi) == (ENTRY.id, 6, ENTRY.sha256, 300)
    assert (h.status, h.checked_at, h.transcribed_by) == ("approved", "2026-10-23", "Claude Code from rendered page")
    assert h.checked_by.strip()                                    # approved by the user, 2026-10-23
    assert h.body_sha256 == body_sha256(t.body)
    kinds = [b["kind"] for b in t.blocks]
    assert kinds == ["heading", "text", "heading", "table", "text", "subheading", "text", "text", "text", "text"]
    assert t.blocks[0]["text"] == "UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY (KHARIF MARKETING SEASON 2026-2027)"
    table = t.blocks[3]
    assert table["header"] == ["S .No", "Refractions", "Maximum Limit (%)"]           # one limit column
    assert table["rows"] == [["1.", "Foreign matter", ""], ["", "a) Inorganic", "1.0"], ["", "b) Organic", "1.0"],
                             ["2.", "Damaged, discoloured, sprouted and weevilled grains", "5.0*"],
                             ["3.", "Immature, Shrunken and shrivelled grains", "3.0"],
                             ["4.", "Admixture of lower class", "6.0"], ["5.", "Moisture content", "17.0"]]
    assert t.blocks[4]["text"] == "* Damaged, sprouted and weevilled grains should not exceed 4%."
    assert "[illegible]" not in t.body


def test_the_committed_p006_is_used():
    assert list(for_source(ENTRY, today=TODAY)["approved"]) == [6]


# --- the approval gate --------------------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["proposed", "rejected"])
def test_a_proposed_or_rejected_transcription_is_never_used(tmp_path, status):
    found = for_source(ENTRY, copy_with(tmp_path, status, "", ""), today=TODAY)
    assert found["approved"] == {} and [(t.page, s) for t, s, _ in found["other"]] == [(6, status)]


@pytest.mark.parametrize("kw, problem", [
    ({"checked_by": ""}, "approved without checked_by"),
    ({"checked_at": ""}, "approved without a valid checked_at"),
    ({"checked_at": "2026-10-24"}, "is in the future"),
    ({"edit_body": ("17.0", "18.0")}, "the body changed after body_sha256 was stored"),
    ({"edit_body": ('pdf_sha256 = "19e8', 'pdf_sha256 = "29e8')}, "pdf_sha256 does not match"),
    ({"edit_body": ('source_id = "source:dfpd', 'source_id = "source:xdfpd')}, "is not source:dfpd"),
])
def test_an_approved_transcription_that_fails_a_check_stops_everything(tmp_path, kw, problem):
    with pytest.raises(TranscriptionError) as e:
        for_source(ENTRY, approved_copy(tmp_path, **kw), today=TODAY)
    assert any(problem in p for p in e.value.problems)


def test_the_file_name_must_match_the_page(tmp_path):
    d = approved_copy(tmp_path)
    (d / "p006.md").rename(d / "p007.md")
    with pytest.raises(TranscriptionError, match="file name must be p006.md"):
        for_source(ENTRY, d, today=TODAY)


def test_rehash_after_an_edit_sets_it_back_to_proposed(tmp_path):
    d = approved_copy(tmp_path, edit_body=("17.0", "18.0"))
    h = rehash(d / "p006.md")
    assert (h.status, h.checked_by, h.checked_at) == ("proposed", "", "")
    t = read(d / "p006.md")
    assert h.body_sha256 == body_sha256(t.body) and "18.0" in t.body
    assert for_source(ENTRY, d, today=TODAY)["approved"] == {}


@pytest.mark.parametrize("body, problem", [
    ("| a | b |\n| c | d |\n", "rule as its second line"),
    ("| a | b |\n|---|---|\n| c |\n", "do not have 2 cells"),
    ("# One\nTwo\n", "a heading is one line"),
    ("text\n| a |\n", "mixes table lines and text"),
])
def test_body_format_errors(body, problem):
    with pytest.raises(TranscriptionError) as e:
        parse_body(body)
    assert any(problem in p for p in e.value.problems)


# --- downstream: segmentation, tables, quotes, spans --------------------------------------------------------

@needs_conversion
def test_segmentation_uses_the_converter_until_approval_then_the_transcription(tmp_path):
    from kg.segment.report import segment
    before, rep = segment(ENTRY, DOCLING, copy_with(tmp_path / "proposed", "proposed", "", ""))
    assert not any(i["ref"].startswith("tr:") for u in before for i in u["items"])
    assert rep["transcribed_pages"] == [] and rep["transcriptions_not_used"][0]["status"] == "proposed"

    after, rep = segment(ENTRY, DOCLING, approved_copy(tmp_path))
    [page] = rep["transcribed_pages"]
    assert (page["pdf_page"], page["checked_by"]) == (6, "TEST REVIEWER") and page["converter_items_dropped"] > 0
    p6 = [i for u in after for i in u["items"] if i["pdf_page"] == 6]
    assert p6 and all(i["ref"].startswith("tr:p006#/") and i["transcription"].endswith("p006.md") for i in p6)
    others = lambda units: [(i["ref"], i.get("text")) for u in units for i in u["items"] if i["pdf_page"] != 6]
    assert others(after) == others(before)                            # every other page is untouched
    paddy = [u for u in after if u["chapter"]["number"] == "1"]
    assert [u["section_path"] for u in paddy] == [
        "UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY",
        "UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY > SCHEDULE OF SPECIFICATION"]
    schedule = paddy[1]
    assert schedule["table_refs"] == ["tr:p006#/tables/0"]
    notes = [i for i in schedule["items"] if i["kind"] == "text" and i["subheading"] == "N. B."]
    assert [i["text"][:3] for i in notes] == ["1. ", "2. ", "3. ", "***"]   # N. B. stays with its table
    assert not any(x["chapter"].startswith("UNIFORM SPECIFICATION OF ALL VARIETIES")
                   for x in rep["chapter_heading_not_found"])


@needs_conversion
def test_tables_take_the_transcription_and_quotes_are_checked_against_it(tmp_path):
    from kg.extract import check_answer, render_unit
    from kg.segment.report import segment
    from kg.tables import run, table_record
    d = approved_copy(tmp_path)
    units, _ = segment(ENTRY, DOCLING, d)
    units_path = tmp_path / "units.jsonl"
    units_path.write_text("\n".join(json.dumps({k: v for k, v in u.items() if not k.startswith("_")},
                                               ensure_ascii=False) for u in units), encoding="utf-8")
    res = run(ENTRY, DOCLING, units_path, ("UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY",), d)
    [t] = res["tables"]
    rec = table_record(t)
    assert rec["table_refs"] == ["tr:p006#/tables/0"] and rec["header"] == ["S .No", "Refractions", "Maximum Limit (%)"]
    assert [c["text"] for c in rec["rows"][-1]] == ["5.", "Moisture content", "17.0"]
    assert [r["check"] for r in res["review"]] == ["transcription"]
    unit = next(u for u in units if u["table_refs"] == ["tr:p006#/tables/0"])
    text, segments = render_unit(ENTRY, unit, {"tr:p006#/tables/0": rec})
    assert "[tr:p006#/tables/0 row 7] 5. | Moisture content | 17.0" in text     # row 0 is the header
    answer = {"facts": [], "not_extracted": [{"quote": "5. | Moisture content | 17.0", "reason": "test"},
                                             {"quote": "Moisture content | 18.0", "reason": "test"}]}
    checked = check_answer(json.dumps(answer), segments)
    found = [n["quote_check"]["ok"] for n in checked["not_extracted"]]
    assert found == [True, False]                                    # 18.0 is not in the transcription


def test_spans_name_the_transcription_only_with_manual_transcription():
    base = {"id": "span:x", "source_id": ENTRY.id, "pdf_page": 6, "section_path": "s", "quote": "q"}
    sha = "a" * 64
    ok = SourceSpan.model_validate({**base, "extraction_method": "manual_transcription", "table_ref": "tr:p006#/tables/0",
                                    "table_row": 6, "transcription": "transcriptions/x/p006.md",
                                    "transcription_sha256": sha})
    assert ok.table_ref == "tr:p006#/tables/0"
    for bad in ({"extraction_method": "manual_transcription"},
                {"extraction_method": "ocr", "transcription": "t", "transcription_sha256": sha},
                {"extraction_method": "table_parse", "table_ref": "tr:p006#/tables/0"}):
        with pytest.raises(ValidationError):
            SourceSpan.model_validate({**base, **bad})


def test_evidence_records_the_transcription_file_and_hash(tmp_path):
    from kg.normalize import transcription_of
    d = approved_copy(tmp_path)
    t = read(d / "p006.md")
    unit = {"items": [{"ref": "tr:p006#/texts/1", "transcription": str(d / "p006.md")},
                      {"ref": "#/texts/40"}]}
    for refs in (["tr:p006#/texts/1"], ["tr:p006#/tables/0 row 6"]):        # a text line or a table row
        path, sha = transcription_of(unit, refs)
        assert path == str(d / "p006.md") and sha == t.header.body_sha256
    assert transcription_of(unit, ["#/texts/40"]) is None


def test_location_check_reads_transcription_rows():
    from kg.validate import _rows
    assert _rows(["tr:p006#/tables/0 row 6", "#/tables/56 row 4 + #/tables/57 row 0"]) == {
        ("tr:p006#/tables/0", 6), ("#/tables/56", 4), ("#/tables/57", 0)}
