"""Schema v1.6 through steps 10-12: calendar words read from the fixed table, window_for, a printed area or
variety group naming several concepts, the copied-text check and the code-built claims."""

import pytest

from kg.extract.model import FACT as RAW
from kg.normalize import Fact, build, fact_key_parts
from kg.normalize.calendar_words import read, window
from kg.normalize.link import Linker
from kg.registry import read_entry
from kg.schema import FACT
from kg.validate import check_printed_text
from kg.verify.claims import _changed, claims_for, printed_names
from tests.normalize.test_v13 import finish

ENTRY = read_entry("source:gbpuat_kharif_advisory_2020")
RUN = {"extraction_model": "m", "prompt_version": "v6", "cache_key": "k" * 64}
UNIT = {"id": "unit:gbpuat_kharif_advisory_2020:x", "source_id": ENTRY.id,
        "section_path": "Advisory for Kharif Season in Uttarakhand", "pdf_pages": [1, 3],
        "regions": [{"id": "state:5", "origin": "source"}], "purposes": [], "default_scope": [], "items": []}
ROW = ("Rice | Tarai, Bhabhar & Plain | Narendra-359, HKR-47, PR-113 & 114, Pant Dhan- 10,12, 19, 24 & 26 | "
       "Nursery sowing- 2 nd fortnight May to 1 st week of June Transplanting Time -June end to 1 st week of July")
NURSERY = {"subtype": "SowingWindow", "summary_en": "s", "table_ref": "#/tables/0", "table_row": 1, "table_col": 3,
           "quote": "Nursery sowing- 2 nd fortnight May to 1 st week of June", "regions": ["Tarai, Bhabhar & Plain"],
           "window_for": "nursery_sowing", "start_raw": "2 nd fortnight May", "end_raw": "1 st week of June"}


@pytest.fixture(scope="module")
def linker():
    return Linker.for_source(ENTRY)


def fact(prompt="v6", **kw):
    raw = RAW.validate_python({**NURSERY, **kw}).model_dump(mode="json")
    qc = {"ok": True, "occurrences": 1, "refs": ["#/tables/0 row 1"], "pdf_pages": [1], "printed_pages": [None]}
    f = Fact({**RUN, "prompt_version": prompt}, UNIT, {"index": 0, "fact": raw, "quote_check": qc})
    f.entry = ENTRY
    return f


@pytest.mark.parametrize("printed, want", [
    ("2 nd fortnight May", (5, 16, 31)), ("1 st week of June", (6, 1, 7)), ("June end", (6, 25, 30)),
    ("1 st week of July", (7, 1, 7)), ("1 st Fortnight May", (5, 1, 15)), ("2 nd fortnight June", (6, 16, 30)),
    ("April 2 nd fortnight", (4, 16, 30)), ("1 st Fortnight June", (6, 1, 15)), ("Mid March", (3, 15, 15)),
    ("Last week May", (5, 25, 31)), ("End of May", (5, 25, 31))])
def test_the_word_table(printed, want):
    r = read(printed)
    assert (r.month, r.first, r.last) == want


@pytest.mark.parametrize("printed", ["June", "2 nd week of August", "On set of monsoon", "Feb to July", "Mid"])
def test_words_outside_the_table_are_unread(printed):
    assert read(printed) is None


def test_a_window_opens_on_the_first_day_and_closes_on_the_last():
    dates, readings = window("June end", "1 st week of July")
    assert dates == {"start_month": 6, "start_day": 25, "end_month": 7, "end_day": 7}
    assert [x["rule"] for x in readings] == ["end = 25 to month end", "1st week = days 1-7"]
    assert window("1 st Fortnight May", None)[0] == {"start_month": 5, "start_day": 1, "end_month": 5, "end_day": 15}
    assert "not in the word table" in window("June", None)


def test_a_v6_window_is_read_by_code_kept_in_raw_and_sent_to_review(linker):
    f = fact()
    d = build(f, linker, "crop:rice", {})
    assert not f.blocks
    assert (d["window_for"], d["start_month"], d["start_day"], d["end_month"], d["end_day"]) == (
        "nursery_sowing", 5, 16, 6, 7)
    assert d["raw"] == {"start_month": "2 nd fortnight May", "start_day": "2 nd fortnight May",
                        "end_month": "1 st week of June", "end_day": "1 st week of June"}
    assert d["regions"] == [{"id": "zone:uk_tarai_bhabhar_plain", "origin": "text"}]
    assert any(r.startswith("calendar words read by code") and "16 May" in r for r in f.review)
    assert FACT.validate_python(finish(f, d)).window_for == "nursery_sowing"


def test_window_for_separates_a_zones_nursery_and_transplanting_windows(linker):
    a = fact()
    b = fact(quote="Transplanting Time -June end to 1 st week of July", window_for="transplanting",
             start_raw="June end", end_raw="1 st week of July")
    pa, pb = (fact_key_parts(f, build(f, linker, "crop:rice", {})) for f in (a, b))
    assert pa["identity"]["window_for"] == "nursery_sowing" and pa != pb


def test_the_loaders_conflict_key_keeps_window_for_and_value_key_leaves_it_out(linker):
    from kg.load.facts import conflict_key, value_key
    a = finish(fact(), build(fact(), linker, "crop:rice", {}))
    b = {**a, "window_for": "transplanting"}
    assert conflict_key(a) != conflict_key(b) and value_key(a) == value_key(b)


def test_unread_words_and_unknown_window_for_hold(linker):
    f = fact(start_raw="On set of monsoon", end_raw=None)
    build(f, linker, "crop:rice", {})
    assert any("not in the word table" in b for b in f.blocks)
    g = fact(window_for="harvest")
    build(g, linker, "crop:rice", {})
    assert any("window_for 'harvest' is not in the fixed list" in b for b in g.blocks)


def test_a_v5_window_keeps_its_numbers_and_sows(linker):
    old = {"subtype": "SowingWindow", "summary_en": "s", "quote": "June-July", "start_month": 6, "end_month": 7,
           "raw": {"start_month": "June", "end_month": "July"}}
    raw = RAW.validate_python(old).model_dump(mode="json")
    f = Fact({**RUN, "prompt_version": "v5"}, UNIT, {"index": 0, "fact": raw, "quote_check": {"refs": []}})
    d = build(f, linker, "crop:rice", {})
    assert (d["window_for"], d["start_month"], d["end_month"]) == ("sowing", 6, 7)


def test_a_printed_area_or_variety_group_links_every_concept_it_names(linker):
    f = fact(quote="Mid hills (900 - 1500msl) Nursery sowing - 1 st Fortnight May", table_row=2,
             regions=["Irrigated Hills"], systems=["Irrigated"], start_raw="1 st Fortnight May", end_raw=None)
    d = build(f, linker, "crop:rice", {})
    assert sorted(r["id"] for r in d["regions"]) == ["zone:uk_high_hills", "zone:uk_mid_hills"]
    assert d["system_ids"] == ["system:irrigated"]
    v = RAW.validate_python({"subtype": "VarietyRecommendation", "summary_en": "s", "table_ref": "#/tables/0",
                             "table_row": 1, "quote": "Pant Dhan- 10,12, 19, 24 & 26",
                             "recommends": ["Pant Dhan- 10,12, 19, 24 & 26"]}).model_dump(mode="json")
    g = Fact(RUN, UNIT, {"index": 1, "fact": v, "quote_check": {"refs": ["#/tables/0 row 1"]}})
    g.entry = ENTRY
    dv = build(g, linker, "crop:rice", {})
    assert not g.blocks and dv["recommends"] == ["variety:pant_dhan_%d" % n for n in (10, 12, 19, 24, 26)]


def test_calendar_words_must_be_printed_in_the_quote():
    assert check_printed_text({**NURSERY, "regions": []})["status"] == "pass"
    bad = {**NURSERY, "regions": [], "start_raw": "second fortnight May"}
    assert "start_raw 'second fortnight May' is not in the quote" in check_printed_text(bad)["reason"]


def test_claims_restate_the_dates_and_name_the_printed_place(linker):
    f = fact()
    d = finish(f, build(f, linker, "crop:rice", {}))
    printed = printed_names(f.raw, d)
    assert claims_for(d, {}, printed) == [
        "Does the passage state that the nursery is sown in Tarai, Bhabhar & Plain from 16 May to 7 June?"]
    moved = _changed(d)
    assert (moved["start_month"], moved["start_day"], moved["end_month"], moved["end_day"]) == (8, 16, 9, 7)
    v = RAW.validate_python({"subtype": "VarietyRecommendation", "summary_en": "s", "table_ref": "#/tables/0",
                             "table_row": 1, "quote": ROW.split(" | ")[2], "regions": ["Tarai, Bhabhar & Plain"],
                             "recommends": ["Narendra-359", "PR-113 & 114"]}).model_dump(mode="json")
    g = Fact(RUN, UNIT, {"index": 1, "fact": v, "quote_check": {"refs": ["#/tables/0 row 1"]}})
    g.entry = ENTRY
    dv = finish(g, build(g, linker, "crop:rice", {}))
    assert claims_for(dv, {}, printed_names(g.raw, dv)) == [
        "Does the passage state that Narendra-359 is recommended in Tarai, Bhabhar & Plain?",
        "Does the passage state that PR-113 & 114 are recommended in Tarai, Bhabhar & Plain?"]
