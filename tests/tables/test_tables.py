"""Tables on real TNAU rice and wheat pages. Needs the full conversion and its units
(gitignored); skipped when they are missing."""

import pytest

from kg.convert import output_dir
from kg.registry import ROOT, read_entry
from kg.segment import UNITS_DIR
from kg.tables import run
from kg.tables.check import PageChecker, _bottom_left
from kg.tables.stitch import ws

ENTRY = read_entry("source:tnau_agriculture_2020")
DOCLING = output_dir(ENTRY)
UNITS = UNITS_DIR / "tnau_agriculture_2020" / "units.jsonl"
pytestmark = pytest.mark.skipif(not ((DOCLING / "document.json").exists() and UNITS.exists()),
                                reason="needs data/docling and data/units for the TNAU guide")


@pytest.fixture(scope="module")
def result():
    return run(ENTRY, DOCLING, UNITS, ("RICE", "WHEAT"))


def table(result, first_ref):
    return next(t for t in result["tables"] if t.refs[0] == first_ref)


def variety(result, vid):
    return next(v for v in result["varieties"] if v.id == vid)


def test_etl_table_stitches_into_one_table_with_all_8_pests(result):
    etl = table(result, "#/tables/53")
    assert etl.refs == ["#/tables/53", "#/tables/54"] and etl.header == ["Pest", "ETL"]
    assert [row[0]["text"] for row in etl.rows] == [
        "Stem borer", "Leaffolder", "Gall midge", "Whorl maggot", "Thrips", "Brown planthopper",
        "Green leafhopper", "Earhead bug"]
    bph = next(row for row in etl.rows if row[0]["text"] == "Brown planthopper")
    assert bph[1]["part_ref"] == "#/tables/54" and bph[1]["text"].startswith("1 hopper/ tiller")


def test_rice_variety_value_matches_the_printed_page(result):
    co51 = variety(result, "variety:co_51")
    cell = co51.cells["avg_yield"]
    assert (co51.avg_yield_kg_ha, co51.raw["avg_yield_kg_ha"]) == (6641, "6641")
    assert (cell["table_ref"], cell["pdf_page"], cell["printed_page"]) == ("#/tables/9", 17, "5")
    part = table(result, "#/tables/9").parts[0]
    box = next(c["bbox"] for c in part.cells if (c["row"], c["col"]) == (cell["row"], cell["col"]))
    page = PageChecker(ROOT / ENTRY.file).page(17)
    l, b, r, t = _bottom_left(box, page["height"])
    words = [w for x, y, w in sorted(page["words"], key=lambda v: (-round(v[1]), v[0]))
             if l - 1 <= x <= r + 1 and b - 1 <= y <= t + 1]
    assert ws(" ".join(words)) == "6641"                      # exactly what the page prints


def test_zone_season_table_stitches_five_parts(result):
    assert table(result, "#/tables/4").refs == ["#/tables/%d" % n for n in range(4, 9)]


def test_header_flagged_data_row_is_kept_as_data(result):
    assert table(result, "#/tables/9").refs == ["#/tables/9", "#/tables/10"]
    assert "Auricle: Pale Green" in variety(result, "variety:co_51").traits
    assert table(result, "#/tables/11").header[0] == "PARTICULARS"      # a new table, not a continuation


def test_merged_cells_collapse_but_genuine_repeats_stay(result):
    rows = table(result, "#/tables/9").rows
    grain = next(r for r in rows if r[0]["text"] == "Grain size (mm)")
    assert len(grain) == 1 and grain[0]["col_span"] == 4
    husk = next(r for r in rows if r[0]["text"] == "Husk colour")
    assert [c["text"] for c in husk[1:]] == ["Straw", "Straw", "Straw"]


def test_damaged_tables_go_to_review_not_into_records(result):
    details = [r["detail"] for r in result["review"]]
    assert any("variety name cell spans 2 columns: 'Imp. White Ponni ADT (R) 46'" in d for d in details)
    merged = [r for r in result["review"] if r["check"] == "merged across a ruling"]
    assert any(r["docling"] == "4500 6656" for r in merged)
    assert not [v for v in result["varieties"] if "ponni" in v.id]


def test_unmapped_labels_go_to_review(result):
    assert any(r["detail"].startswith("unmapped row label") for r in result["review"])


def test_every_variety_is_needs_review_and_gets_its_approved_chapters_crop(result):
    assert result["varieties"] and all(v.review_status == "needs_review" for v in result["varieties"])
    crops = {v.id: v.crop_id for v in result["varieties"]}
    assert crops["variety:co_51"] == "crop:rice" and crops["variety:cow_w_1"] == "crop:wheat"
    assert None not in crops.values()                                       # rice and wheat approved
    assert not [r for r in result["review"] if r["detail"].startswith("crop_id pending")]
    assert len({v.id for v in result["varieties"]}) == len(result["varieties"])


def test_crop_waits_for_chapter_approval(result):
    from kg.tables.varieties import pivot
    t = table(result, "#/tables/9")
    proposed = next(c for c in ENTRY.chapters if c.title == "RICE").model_copy(update={"status": "proposed"})
    records, _ = pivot(t, ENTRY, proposed, "short")
    assert all(v.crop_id is None for v in records)


def test_cow_box_varieties_are_pivoted_and_flagged(result):
    for vid in ("variety:cow_w_1", "variety:cow_w_2"):
        assert variety(result, vid).evidence[0].pdf_page == 134
        assert any(r.get("variety_id") == vid and r["detail"] ==
                   "Docling reading order: content of 'I. SEASON AND VARIETY' placed before the chapter "
                   "heading (corrected by an approved reading-order fix)" for r in result["review"])
    assert any("Variety : COW(W)1" in (c["text"] or "") for c in result["cow_box_context"])


def test_possible_duplicates_are_reported_never_merged(result):
    pairs = {(d["a"], d["b"]) for d in result["duplicates"]}
    assert ("COW (W) 2", "TNAU Samba Wheat COW 2") in pairs
    assert "variety:cow_w_2" in {v.id for v in result["varieties"]}


def test_page_split_rows_are_merged_and_sent_to_review(result):
    strategies = table(result, "#/tables/55")
    merged = {(m["part_ref"], m["into"]) for m in strategies.merged_rows}
    assert merged == {("#/tables/57", "#/tables/56 row 4"), ("#/tables/58", "#/tables/57 row 4")}
    hispa = next(r for r in strategies.rows if r[0]["text"].startswith("Hispa"))
    assert hispa[1]["text"].endswith("Malathion 5% DP 25 kg Malathion 50%EC 1150 ml")
    wbph = next(r for r in strategies.rows if r[0]["text"].startswith("White backed planthopper"))
    assert wbph[1]["text"].endswith("Imidacloprid 17.8% SL 100-125 ml")
    assert not any(r[0]["text"].startswith(("Malathion", "Fipronil")) for r in strategies.rows)
    review = {(r["table_ref"], r["check"]) for r in result["review"]}
    assert {("#/tables/57", "row continued across page break"),
            ("#/tables/58", "row continued across page break")} <= review
    assert variety(result, "variety:adt_r_48").traits.count("Seed source: Seed centre, TNAU, Coimbatore-3") == 1


def test_duration_reference_comes_from_the_book(result):
    assert result["duration_reference"]["values"] == {"short": 105, "medium": 135, "long": 150}
