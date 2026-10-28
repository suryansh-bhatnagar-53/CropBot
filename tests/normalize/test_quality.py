"""Schema v1.5 QualitySpec through steps 10-14: normalisation (registry authority and season, vocabularies,
grades from the quote or the section scope, value cuts held), validation, claims, the quality_check verdict and
the review sheet's values."""

import pytest

from kg.extract.model import FACT as RAW
from kg.normalize import Fact, build
from kg.normalize.link import Linker
from kg.registry import read_entry
from kg.schema import FACT
from tests.normalize.test_v13 import finish as finish_for_test

ENTRY = read_entry("source:dfpd_uniform_spec_kms_2026_27")
RUN = {"extraction_model": "m", "prompt_version": "v5", "cache_key": "k" * 64}
QC = {"ok": True, "occurrences": 1, "refs": ["tr:p006#/tables/0 row 7"], "pdf_pages": [6], "printed_pages": [None]}
GRADES = [{"id": "grade_a", "origin": "section", "evidence": "UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY"},
          {"id": "common", "origin": "section", "evidence": "UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY"}]
UNIT = {"id": "unit:dfpd_uniform_spec_kms_2026_27:be6702f9b908", "source_id": ENTRY.id,
        "section_path": "UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY > SCHEDULE OF SPECIFICATION",
        "pdf_pages": [6, 6], "regions": [{"id": "country:in", "origin": "source"}], "purposes": [],
        "default_scope": [], "grades": GRADES, "items": []}
MOISTURE = {"subtype": "QualitySpec", "summary_en": "Paddy moisture at most 17%.", "quote": "5. | Moisture content | 17.0",
            "table_ref": "tr:p006#/tables/0", "table_row": 7, "commodity_form": "paddy", "parameter": "moisture",
            "parameter_raw": "Moisture content", "limit_type": "max", "limit_value": 17.0, "unit": "%",
            "raw": {"limit_value": "17.0"}}


def raw(prompt="v5", seg=UNIT, **kw):
    fact = RAW.validate_python({**MOISTURE, **kw}).model_dump(mode="json")
    f = Fact({**RUN, "prompt_version": prompt}, seg, {"index": 0, "fact": fact, "quote_check": QC})
    f.entry = ENTRY
    return f


def built(f):
    return build(f, Linker([]), "crop:rice", {})


def test_authority_and_season_come_from_the_registry_and_grades_from_the_section_scope():
    f = raw()
    d = built(f)
    assert not f.blocks
    assert (d["authority"], d["season_label"], d["marketing_season"], d["season_start_year"]) == (
        ENTRY.publisher, "KHARIF MARKETING SEASON 2026-2027", "KMS", 2026)
    assert (d["grades"], d["grades_origin"], d["grades_evidence"]) == (
        ["grade_a", "common"], "section", "UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY")
    assert (d["parameter"], d["limit_type"], d["limit_value"], d["unit"]) == ("moisture", "max", 17.0, "pct")
    fact = finish_for_test(f, d)
    assert FACT.validate_python(fact).grades == ["grade_a", "common"]


def test_grades_printed_in_the_quote_win():
    f = raw(quote="If the ratio is greater than & equal to 2.5, then it is classified as Grade ‘A ’",
            table_ref=None, table_row=None, parameter="length_breadth_ratio", parameter_raw="ratio",
            limit_type="min", limit_value=2.5, unit=None, raw={"limit_value": "2.5"}, grades=["grade_a"])
    d = built(f)
    assert not f.blocks and (d["grades"], d["grades_origin"], d["unit"]) == (["grade_a"], "text", None)


@pytest.mark.parametrize("kw, block", [
    ({"parameter": "dust"}, "parameter 'dust' is not in the fixed list"),
    ({"limit_type": "about"}, "limit_type 'about' is not in the fixed list"),
    ({"commodity_form": "flour"}, "commodity_form 'flour' is not in the fixed list"),
    ({"unit": "kg"}, "unit 'kg' is not a percentage"),
    ({"parameter_raw": None}, "parameter_raw"),
    ({"unmapped": ["with value cut"]}, "value-cut rule held"),
    ({"grades": ["grade_b"]}, "grades ['grade_b'] are not in the fixed list"),
])
def test_what_holds_a_limit(kw, block):
    f = raw(**kw)
    built(f)
    assert any(block in b for b in f.blocks)


def test_no_grade_without_a_scope_holds_and_old_prompts_hold():
    f = raw(seg={**UNIT, "grades": []})
    built(f)
    assert any("no grade" in b for b in f.blocks)
    old = raw(prompt="v4", commodity_form=None, parameter_raw=None, limit_type=None)
    built(old)
    assert old.blocks == ["QualitySpec needs prompt v5 (schema v1.5)"]


def test_identity_is_in_the_fact_key_only_for_quality_specs():
    from kg.normalize import fact_key_parts
    a, b = raw(), raw(parameter="admixture_lower_class", parameter_raw="Admixture of lower class")
    pa, pb = (fact_key_parts(f, built(f)) for f in (a, b))
    assert pa["identity"]["parameter"] == "moisture" and pa != pb


# --- steps 11-14 -------------------------------------------------------------------------------------------

def quality(**kw):
    f = raw(**kw)
    return finish_for_test(f, built(f))


def test_value_ranges_and_printed_text_for_a_limit():
    from kg.validate import check_printed_text, check_value_ranges
    assert check_value_ranges(quality())["status"] == "pass"
    assert check_value_ranges(quality(limit_value=30.0, raw={"limit_value": "30.0"}))["status"] == "fail"
    assert check_value_ranges(quality(parameter="admixture_lower_class", parameter_raw="Admixture of lower class",
                                      limit_value=6.0, raw={"limit_value": "6.0"}))["status"] == "pass"
    row = "5. | Moisture content | 17.0 S .No | Refractions | Maximum Limit (%)"     # its row and the header
    assert check_printed_text(MOISTURE, row=row)["status"] == "pass"                  # "%" is in the header
    assert check_printed_text({**MOISTURE, "parameter_raw": "Moisture"}, row=row)["status"] == "pass"
    assert check_printed_text({**MOISTURE, "parameter_raw": "Water content"}, row=row)["status"] == "fail"


def test_table_rows_take_the_header_too():
    from kg.validate import table_rows
    rendered = ["[tr:p006#/tables/0 header] S .No | Refractions | Maximum Limit (%)",
                "[tr:p006#/tables/0 row 7] 5. | Moisture content | 17.0"]
    assert table_rows(rendered, ["tr:p006#/tables/0 row 7"]) == (
        "5. | Moisture content | 17.0 S .No | Refractions | Maximum Limit (%)")


def test_claims_read_like_the_page():
    from kg.verify.claims import _changed, claims_for
    assert claims_for(quality(), {}) == [
        "Does the passage state that, for paddy (Grade 'A' and Common), Moisture content is at most 17%?"]
    absent = quality(quote="free from moulds", table_ref=None, table_row=None, parameter="moulds",
                     parameter_raw="moulds", limit_type="absent", limit_value=None, unit=None, raw={})
    assert claims_for(absent, {}) == ["Does the passage state that paddy (Grade 'A' and Common) is free from moulds?"]
    sub = quality(parameter="dhatura_seeds", parameter_raw="Dhatura", limit_value=0.025, raw={"limit_value": "0.025%"},
                  part_of="poisonous_seeds")
    assert claims_for(sub, {})[0].endswith("Dhatura is at most 0.025% within the limit for poisonous seeds?")
    # a number control is stricter than printed, never looser (a looser limit is implied by the true one)
    assert _changed(quality())["limit_value"] == 8.5
    lb = quality(quote="If the ratio is greater than & equal to 2.5, then it is classified as Grade ‘A ’",
                 table_ref=None, table_row=None, parameter="length_breadth_ratio", parameter_raw="ratio",
                 limit_type="min", limit_value=2.5, unit=None, raw={"limit_value": "2.5"}, grades=["grade_a"])
    assert _changed(lb)["limit_value"] == 5.0


def test_quality_check_and_verdict():
    from kg.query import FarmContext
    from kg.query.answer import applicability, quality_check, verdict
    f = quality()
    ctx = FarmContext(crop="crop:rice", commodity_form="paddy", quality={"moisture": 18})
    assert quality_check(f, ctx) == {"parameter": "moisture", "value": 18, "result": "fail"}
    assert quality_check(f, FarmContext(crop="crop:rice", observations={"grain_moisture_pct": 17}))["result"] == "pass"
    assert quality_check(f, FarmContext(crop="crop:rice"))["result"] == "unknown"
    row = {"fact": f, "variety_ids": [], "season_ids": [], "system_ids": [], "soil_ids": [], "purpose_ids": [],
           "stage_ids": []}
    ok, unknown, _, _ = applicability(row, FarmContext(crop="crop:rice"))
    assert ok and unknown == {"commodity_form": ["paddy"]}                 # both grades: no grade question
    assert not applicability(row, FarmContext(crop="crop:rice", commodity_form="raw_rice"))[0]
    out = {"slots": [{"facts": [{"check": {"parameter": "moisture", "result": "fail"}},
                                {"check": {"parameter": "admixture_lower_class", "result": "unknown"}}]}]}
    assert verdict(out) == {"result": "fail", "failed": ["moisture"], "not_checked": ["admixture_lower_class"],
                            "passed": [], "grade_rules": []}
    # a grade rule is reported, never counted: L:B 2.0 makes paddy Common, it does not reject it
    rule = {"check": {"parameter": "length_breadth_ratio", "value": 2.0, "result": "fail"},
            "values": {"grades": ["grade_a"]}}
    lone = verdict({"slots": [{"facts": [rule, {"check": {"parameter": "moisture", "result": "pass"}}]}]})
    assert (lone["result"], lone["failed"], lone["grade_rules"][0]["grades"]) == ("pass", [], ["grade_a"])
    lb = {**row, "fact": {**f, "parameter": "length_breadth_ratio", "grades": ["grade_a"]}}
    assert applicability(lb, FarmContext(crop="crop:rice", commodity_form="paddy"))[1] == {}   # no grade question


def test_review_sheet_shows_the_limit():
    from kg.review.sheet import ORDER, scope, values
    f = quality()
    assert ORDER.index("QualitySpec") == ORDER.index("HarvestRule") + 1
    assert "moisture (printed: Moisture content): max 17%" in values(f, {})
    assert "grades: grade_a, common (section: UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY)" in scope(f, {})
