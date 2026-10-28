"""Segmentation of real TNAU sections. Needs a conversion in data/docling/ (gitignored):
the full book if present, else the rice trial (PDF pp. 13-76). Skipped when neither exists."""

import json

import pytest

from kg.convert import output_dir
from kg.registry import read_entry
from kg.segment.report import segment

ENTRY = read_entry("source:tnau_agriculture_2020")
FULL, TRIAL = output_dir(ENTRY), output_dir(ENTRY, (13, 76))
DOCLING = next((d for d in (FULL, TRIAL) if (d / "document.json").exists()), None)
pytestmark = pytest.mark.skipif(DOCLING is None, reason="no TNAU conversion in data/docling/")
needs_full = pytest.mark.skipif(not (FULL / "document.json").exists(), reason="full conversion not present")


@pytest.fixture(scope="module")
def seg():
    return segment(ENTRY, DOCLING)


def unit_with(units, snippet, chapter="RICE"):
    """The one unit of `chapter` containing `snippet` (seed-production text repeats per crop)."""
    hits = [u for u in units if u["chapter"]["title"] == chapter
            and any(snippet in (i.get("text") or "") for i in u["items"])]
    assert len(hits) == 1, (snippet, [u["section_path"] for u in hits])
    return hits[0]


def test_wet_nursery_unit_has_the_20_cents_line_and_the_dap_bullets(seg):
    units, _ = seg
    unit = unit_with(units, "Select 20 cents (800 m")
    assert "1.1.1. Wet nursery" in unit["section_path"]
    for bullet in ("Basal application of DAP is recommended",
                   "For that situation, before the last puddling, apply 40 kg of DAP",
                   "If seedlings are to be pulled out after 25 days",
                   "For clayey soils where root snapping is a problem"):
        assert unit_with(units, bullet)["id"] == unit["id"], bullet


def test_etl_tables_land_in_the_main_field_pest_unit(seg):
    from docling_core.types.doc import DoclingDocument
    units, _ = seg
    doc = DoclingDocument.load_from_json(DOCLING / "document.json")
    etl = [t.self_ref for t in doc.tables if t.prov and t.prov[0].page_no in (63, 64)
           and t.data.grid and t.data.grid[0][0].text.strip() in ("Pest", "Gall midge")]
    assert len(etl) == 2                                   # p. 63 and its p. 64 continuation
    main_field = [u for u in units if u["section_path"].endswith("A) Pest management > ii) Main field")]
    assert len(main_field) == 1 and set(etl) <= set(main_field[0]["table_refs"])
    if DOCLING == TRIAL:
        assert etl == ["#/tables/50", "#/tables/51"]


def test_seed_production_is_a_major_section_not_inside_nematode_management(seg):
    units, report = seg
    seed = [u for u in units if u["section_path"].startswith("RICE > RICE - VARIETAL SEED PRODUCTION")]
    assert seed and all("Nematode" not in u["section_path"] for u in seed)
    assert {"heading": "RICE - VARIETAL SEED PRODUCTION", "decision": "major section"}.items() <= next(
        c for c in report["caps_decisions"] if c["heading"] == "RICE - VARIETAL SEED PRODUCTION").items()


def test_known_issue_1_fixed_seed_storage_has_its_sub_heading(seg):
    units, _ = seg
    unit = unit_with(units, "Store the seeds in 700 gauge polythene bag")
    item = next(i for i in unit["items"] if "700 gauge" in (i.get("text") or ""))
    assert item["subheading"] == "Storage" and "RICE - VARIETAL SEED PRODUCTION" in unit["section_path"]
    drying = next(i for i in unit["items"] if (i.get("text") or "").startswith("Dry the seeds to 12 - 13"))
    assert drying["subheading"] == "Drying"


def test_known_issue_2_grain_drying_lands_in_1_5_harvesting(seg):
    units, report = seg
    unit = unit_with(units, "Dry the grains to 12% moisture level for storage.")
    assert unit["section_path"].endswith("> 1.5. Harvesting")
    assert "1. TRANSPLANTED PUDDLED LOWLAND RICE" in unit["section_path"]
    assert not [x for x in report["heading_like_list_items"] if x["pdf_page"] == 39]
    assert not [g for g in report["numbering_gaps"] if g["under"].startswith("1. TRANSPLANTED")]


def test_restore_fixes_close_the_rice_gaps(seg):
    _, report = seg
    restored = {(f["pdf_page"], f["heading"]) for f in report["heading_fixes_applied"] if f["kind"] == "restore"}
    assert {(46, "3.9. Insect management: See Crop Protection Chapter"),
            (46, "3.10. Disease management: See Crop Protection Chapter"),
            (49, "4.10. Insect management: See Crop Protection Chapter"),
            (51, "5.12. Disease management: See Crop Protection Chapter")} <= restored
    assert not [g for g in report["numbering_gaps"] if g["chapter"] == "RICE"]
    assert not [x for x in report["heading_like_list_items"] if x["pdf_page"] in (46, 49, 51)]



def test_main_field_section_ends_on_p69(seg):
    _, report = seg
    check = next(c for c in report["scope_checks"] if c["heading"] == "ii) Main field")
    assert check["ok"] and check["section_pdf_pages"] == [63, 69]


def test_nursery_rule_matches_once_its_heading_fix_is_approved(seg):
    units, report = seg
    check = next(c for c in report["scope_checks"] if c["heading"] == "Nursery")
    assert check["ok"] and check["section_pdf_pages"] == [62, 63] and not report["failed"]
    nursery = unit_with(units, "An area of 800 sq.m. (20 cents) nursery")
    assert nursery["section_path"] == "RICE > CROP PROTECTION > A) Pest management > Nursery"
    assert any("nursery doses are for 800 m2" in r for r in nursery["default_scope"])
    proposed = ENTRY.model_copy(update={"heading_fix": [
        f.model_copy(update={"status": "proposed"}) if f.pdf_page == 62 else f for f in ENTRY.heading_fix]})
    _, report2 = segment(proposed, DOCLING)
    check2 = next(c for c in report2["scope_checks"] if c["heading"] == "Nursery")
    assert not check2["ok"] and check2["matches"] == 0       # fails loudly without the fix


SEED = "RICE > RICE - VARIETAL SEED PRODUCTION"
NPK = ["Short duration : NPK @ 120:40:40 kg / ha", "Medium duration", ": NPK @ 150:50:60 kg / ha",
       "Long duration", ": NPK @ 150:50:80 kg / ha"]


def _npk(units):
    unit = next(u for u in units if u["section_path"] == SEED)
    return [i["text"] for i in unit["items"] if i["kind"] == "text"
            and i.get("subheading") == "Fertilizer recommendation for different duration varieties"], unit


@needs_full
def test_seed_section_has_purpose_seed_and_npk_lines_in_printed_order(seg):
    units, report = seg
    check = next(c for c in report["scope_checks"] if c["heading"] == "RICE - VARIETAL SEED PRODUCTION")
    assert check["ok"] and check["status"] == "approved" and check["section_pdf_pages"] == [73, 75]
    texts, unit = _npk(units)
    assert texts == NPK and not report["failed"]
    assert unit["purposes"] == [{"id": "purpose:seed", "origin": "section"}]
    assert unit["regions"] == [{"id": "state:33", "origin": "source"}]        # purposes only: regions unchanged
    assert all(u["purposes"] == [] for u in units if not u["section_path"].startswith(SEED))


@needs_full
def test_without_the_approvals_the_docling_order_and_no_purpose_return():
    proposed = ENTRY.model_copy(update={
        "section_scope": [s.model_copy(update={"status": "proposed"}) for s in ENTRY.section_scope],
        "reading_order_fix": [f.model_copy(update={"status": "proposed"}) if f.pdf_page == 74 else f
                              for f in ENTRY.reading_order_fix]})
    units, _ = segment(proposed, FULL)
    texts, unit = _npk(units)
    assert unit["purposes"] == [] and texts[1:3] == ["Medium duration", "Long duration"]


def test_units_are_serialisable_and_carry_provenance(seg):
    units, _ = seg
    for u in units:
        json.dumps({k: v for k, v in u.items() if not k.startswith("_")})
        assert u["regions"] and u["source_id"] == ENTRY.id
        assert all(i["pdf_page"] for i in u["items"] if i["kind"] != "subheading")


@needs_full
def test_wheat_chapter_tree(seg):
    units, report = seg
    wheat = [u["section_path"] for u in units if u["chapter"]["title"] == "WHEAT"]
    steps = ["1. FIELD PREPARATION", "2. APPLICATION OF FYM OR COMPOST", "3. SEED TREATMENT WITH FUNGICIDES",
             "4. FORMING BEDS AND CHANNEL", "5. APPLICATION OF FERTILIZERS", "6. SOWING", "7. WEED MANAGEMENT",
             "8. WATER MANAGEMENT", "9. TOP DRESSING", "10. HARVESTING"]
    managed = [p.split(" > ")[-1] for p in wheat if p.startswith("WHEAT > CROP MANAGEMENT > ")]
    assert managed == steps                                     # in book order, no gaps
    assert "WHEAT > CROP PROTECTION" in wheat
    # the approved reading-order fix puts the COW(W)1 block inside "I. SEASON AND VARIETY"
    season = next(p for p in wheat if p.endswith("> I. SEASON AND VARIETY"))
    assert season + " > 2. Morphological Description of COW(W) 1" in wheat
    assert unit_with(units, "Variety : COW(W)1", "WHEAT")["section_path"] == season
    assert ("WHEAT", 134) not in {(x["chapter"], x["pdf_page"]) for x in report["before_chapter_heading"]}
    # the book prints no "1." before "2. Morphological Description": acknowledged, not open
    assert not [g for g in report["numbering_gaps"] if g["chapter"] == "WHEAT"]
    assert [(g["chapter"], g["under"], g["missing"], g["pdf_page"]) for g in report["acknowledged_gaps"]] == [
        ("WHEAT", "I. SEASON AND VARIETY", ["1"], 134)]
    assert report["stale_acknowledged_gaps"] == []


def wheat_p134(units):
    return [(u["kind"], u["section_path"]) for u in units
            if u["chapter"]["title"] == "WHEAT" and u["pdf_pages"][0] == 134]


@needs_full
def test_crop_improvement_fix_puts_season_under_it(seg):
    units, report = seg
    assert wheat_p134(units) == [
        ("leaf", "WHEAT > CLIMATE REQUIREMENT"),
        ("intro", "WHEAT > CROP IMPROVEMENT > I. SEASON AND VARIETY"),
        ("leaf", "WHEAT > CROP IMPROVEMENT > I. SEASON AND VARIETY > 2. Morphological Description of COW(W) 1")]
    assert ("CROP IMPROVEMENT", 1) in {(f["first"], f["moved"]) for f in report["reading_order_fixes_applied"]}
    # without the fix, "CROP IMPROVEMENT" is an empty unit and the season section sits under the climate
    rejected = ENTRY.model_copy(update={"reading_order_fix": [
        f.model_copy(update={"status": "rejected"}) if f.first == "CROP IMPROVEMENT" else f
        for f in ENTRY.reading_order_fix]})
    units2, _ = segment(rejected, FULL)
    assert wheat_p134(units2)[:3] == [("leaf", "WHEAT > CROP IMPROVEMENT"), ("intro", "WHEAT > CLIMATE REQUIREMENT"),
                                      ("intro", "WHEAT > CLIMATE REQUIREMENT > I. SEASON AND VARIETY")]
