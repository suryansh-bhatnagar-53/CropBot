"""Offline tests for the step 11 checks (kg.validate). Failures go to review; nothing is fixed."""

import copy

from kg.extract.model import FACT as RAW
import pytest

from kg.validate import (check_alternatives, check_ingredients, check_lost_glyph, check_printed_text,
                         check_quote_location, check_range_narrowed, check_raw_numbers, check_review_kept,
                         check_scope_in_unmapped, check_value_ranges, scope_phrases, table_rows)
from kg.schema.concepts import ActiveIngredient, Fertilizer

SPAN = {"id": "span:x", "source_id": "source:tnau_agriculture_2020", "pdf_page": 64, "section_path": "s",
        "quote": "q", "table_ref": None, "table_row": None, "table_col": None, "extraction_method": "native_text"}


def step(order=1, applies=(), **kw):
    s = {"order": order, "alt_group": None, "alt_option": None, "alt_priority": None, "operation": "spraying",
         "offset_min": None, "offset_max": None, "offset_unit": "days", "applies": list(applies), "conditions": []}
    return {**s, **kw}


def fact(steps=(), **kw):
    return {"id": "rec:x", "subtype": "ControlMeasure", "status": "extracted", "steps": list(steps),
            "evidence": [copy.deepcopy(SPAN)], **kw}


def qty(target, value=None, unit="kg", basis="per_ha", formulation=None, raw="r", **kw):
    return {"target_id": target, "value": value, "unit": unit, "basis": basis, "formulation": formulation, "raw": raw, **kw}


# 1 quote location
def test_quote_must_be_found_once_and_in_the_row_named():
    qc = {"occurrences": 1, "refs": ["#/tables/56 row 4 + #/tables/57 row 0"]}
    f = fact()
    f["evidence"][0].update(table_ref="#/tables/57", table_row=0)
    assert check_quote_location(f, qc)["status"] == "pass"                         # either piece of a merged row
    f["evidence"][0].update(table_row=3)
    assert check_quote_location(f, qc)["status"] == "fail"
    assert check_quote_location(fact(), {"occurrences": 2, "refs": []})["reason"] == "quote found 2 times in its unit"


# 2 raw numbers
def raw(**fields):
    data = {"subtype": "NutrientDose", "dose_basis": "blanket", "summary_en": "s",
            "quote": "Apply 40 kg of DAP before the last puddling; spray Five packets (1kg/ha) a week later.",
            "steps": [{"order": 1, "operation": "fertilizer_application",
                       "applies": [{"target": "DAP", "value": 40, "unit": "kg", "basis": "x", "raw": "40 kg of DAP"}]}],
            **fields}
    return RAW.validate_python(data).model_dump(mode="json")


def test_every_raw_text_is_in_the_quote_and_every_number_printed():
    ok = raw(steps=[{"order": 1, "operation": "fertilizer_application",
                     "applies": [{"target": "DAP", "value": 40, "unit": "kg", "basis": "x", "raw": "40 kg of DAP"},
                                 {"target": "Azophos", "value": 5, "unit": "packets", "basis": "x",
                                  "raw": "Five packets (1kg/ha)"}]}])
    assert check_raw_numbers(ok)["status"] == "pass"                                 # number words count
    bad = raw(steps=[{"order": 1, "operation": "fertilizer_application", "anchor": "sowing", "offset_min": 7,
                      "offset_max": 7, "timing_raw": "a week later",
                      "applies": [{"target": "DAP", "value": 45, "unit": "kg", "basis": "x", "raw": "40 kg of DAP"},
                                  {"target": "urea", "value": 16, "unit": "kg", "basis": "x", "raw": "16 kg of urea"}]}])
    reason = check_raw_numbers(bad)["reason"]
    assert "DAP value 45 is not printed in '40 kg of DAP'" in reason
    assert "raw of urea '16 kg of urea' is not in the quote" in reason
    assert "offset_min 7 is not printed in 'a week later'" in reason             # "a week" = 7 is an interpretation


# 3 value ranges
def test_moisture_months_offsets_and_doses_within_bounds():
    assert check_value_ranges(fact(subtype="DryingSpec", target_moisture_pct_max=12))["status"] == "pass"
    assert "outside 5-20" in check_value_ranges(fact(target_moisture_pct_max=25))["reason"]
    assert "outside 10-25" in check_value_ranges(fact(threshing_moisture_pct_min=8))["reason"]
    assert "beyond +-72 hours" in check_value_ranges(fact([step(offset_min=96, offset_unit="hours")]))["reason"]
    assert check_value_ranges(fact([step(applies=[qty("nutrient:n", 150)])]))["status"] == "pass"
    assert "above 500" in check_value_ranges(fact([step(applies=[qty("nutrient:n", 600)])]))["reason"]
    assert "above 20" in check_value_ranges(fact([step(applies=[qty("ai:x", 25, "g", "per_kg_seed")])]))["reason"]
    assert "above 50" in check_value_ranges(fact([step(applies=[qty("fertilizer:dap", 60, basis="per_cent_nursery",
                                                                    area_cents=20)])]))["reason"]
    organic = qty("organic_input:fym", 0.08, "t", "per_cent_nursery", area_cents=20)     # 80 kg per cent
    assert check_value_ranges(fact([step(applies=[organic])]))["status"] == "pass"     # organic inputs: up to 100 kg


def test_active_ingredient_per_ha_from_the_formulation():
    good = qty("ai:carbofuran", 25, "kg", formulation="3% CG", raw="Carbofuran 3% CG 25 kg")
    assert check_value_ranges(fact([step(applies=[good])]))["status"] == "pass"            # 0.75 kg a.i.
    typo = {**qty("ai:fipronil", None, "kg", formulation="80%WG", raw="Fipronil 80%WG 50- 62.5 kg"), "min": 50, "max": 62.5}
    r = check_value_ranges(fact([step(applies=[typo])]))
    assert r["status"] == "fail" and "50.00 kg a.i./ha" in r["reason"]
    no_pct = qty("ai:beauveria_bassiana", 2.5, "kg", formulation="1.15 WP")
    r = check_value_ranges(fact([step(applies=[no_pct])]))
    assert r["status"] == "pass" and r["skipped"] == ["ai:beauveria_bassiana: no formulation % to compute a.i."]


# 4 alternatives
FERT = {i: Fertilizer(id=i, name_en=i, n_pct=n, p2o5_pct=p, k2o_pct=0, review_status="approved", source="x")
        for i, n, p in (("fertilizer:dap", 18, 46), ("fertilizer:urea", 46, 0), ("fertilizer:ssp", 0, 16))}


def nursery(urea=16):
    return fact([step(1, [qty("fertilizer:dap", 40)], alt_group=1, alt_option=1),
                 step(1, [qty("fertilizer:urea", urea), qty("fertilizer:ssp", 120)], alt_group=1, alt_option=2)])


def test_alternatives_agree_within_15_percent_on_approved_percentages():
    assert check_alternatives(nursery(), FERT)["status"] == "pass"                   # the schema's worked example
    assert "n totals" in check_alternatives(nursery(urea=30), FERT)["reason"]
    r = check_alternatives(nursery(), {k: v for k, v in FERT.items() if k != "fertilizer:ssp"})
    assert (r["status"], r["applies"]) == ("skip", True) and "fertilizer:ssp" in r["reason"]
    assert check_alternatives(fact([step(applies=[qty("ai:x", 1)])]), FERT)["applies"] is False
    blank = {**FERT, "fertilizer:ssp": Fertilizer(id="fertilizer:ssp", name_en="SSP", review_status="approved",
                                                  source="no grade sourced")}     # percentages optional (2026-10-20)
    r = check_alternatives(nursery(), blank)
    assert r["status"] == "skip" and "fertilizer:ssp" in r["reason"]


# 5 ingredients
def ai(i, status):
    return ActiveIngredient(id=i, name_en=i, use_class="insecticide", reg_status=status, review_status="needs_review")


def test_ingredients_fail_closed():
    f = fact([step(applies=[qty("ai:a", 1), qty("ai:b", 1)])])
    for status in ("unknown", "restricted", "banned"):
        r = check_ingredients(f, {"ai:a": ai("ai:a", "registered"), "ai:b": ai("ai:b", status)})
        assert r["status"] == "fail" and "ai:b=%s" % status in r["reason"]
    assert check_ingredients(f, {"ai:a": ai("ai:a", "registered")})["reason"].endswith("ai:b=not seeded")
    assert check_ingredients(f, {"ai:a": ai("ai:a", "registered"), "ai:b": ai("ai:b", "registered")})["status"] == "pass"
    assert check_ingredients(fact(), {})["status"] == "skip"
    caution = fact(subtype="Caution", concerns=["ai:b"])                         # a caution may name a banned AI
    assert check_ingredients(caution, {"ai:b": ai("ai:b", "banned")})["status"] == "skip"


# review notes
def test_review_notes_attach_only_when_approved_and_on_the_page():
    from types import SimpleNamespace
    from kg.registry.model import ReviewNote
    from kg.validate import review_notes
    notes = [ReviewNote(pdf_page=64, match="Fipronil 80%WG 50- 62.5 kg", note="typo?", status="approved"),
             ReviewNote(pdf_page=66, match="Imidacloprid 70% WG 30-35 kg", note="typo?", status="proposed")]
    entry = SimpleNamespace(review_note=notes)
    quote = "Fipronil 80%WG 50-  62.5 kg Imidacloprid 70% WG 30-35 kg"
    assert review_notes(entry, quote, [64]) == [0]
    assert review_notes(entry, quote, [65]) == []                                  # wrong page
    assert review_notes(entry, quote, [66]) == []                                  # proposed: not attached


# 6 review kept
def test_flagged_or_inferred_facts_must_be_needs_review():
    raw_fact = raw(extraction_flags=["shared_amount"])
    rec = {"fact": fact(), "review_reasons": []}
    assert check_review_kept(rec, raw_fact)["status"] == "fail"
    rec["fact"]["status"] = "needs_review"
    assert check_review_kept(rec, raw_fact)["status"] == "pass"
    inherited = {"fact": fact([step(applies=[qty("fertilizer:dap", 2, inherited=True)])]), "review_reasons": []}
    assert check_review_kept(inherited, raw())["status"] == "fail"


# 7 range narrowed
def test_a_printed_range_stored_as_one_bound_fails_and_the_value_is_kept():
    store = fact(subtype="StorageRule", max_moisture_pct=13.0, raw={"max_moisture_pct": "12 - 13 %"})
    r = check_range_narrowed(store)
    assert r["status"] == "fail" and r["reason"].startswith(
        "printed range stored as a single bound:")
    assert "max_moisture_pct 13 from '12 - 13 %'" in r["reason"] and store["max_moisture_pct"] == 13.0
    both = fact(subtype="StorageRule", storage_months_min=8.0, storage_months_max=9.0,
                raw={"storage_months_min": "8-9 months", "storage_months_max": "8-9 months"})
    assert check_range_narrowed(both)["status"] == "pass"
    one = fact(subtype="DryingSpec", target_moisture_pct_max=13.0, raw={"target_moisture_pct_max": "12 to 13%"})
    assert check_range_narrowed(one)["status"] == "fail"                      # any min/max field, not only storage
    assert check_range_narrowed(fact(subtype="DryingSpec", target_moisture_pct_max=12.0,
                                     raw={"target_moisture_pct_max": "12%"}))["status"] == "pass"


def test_min_and_max_prefixed_bounds_are_one_pair():
    """Schema v1.3 StorageRule names its bounds min_moisture_pct / max_moisture_pct (C2#22, PDF p. 75)."""
    both = fact(subtype="StorageRule", min_moisture_pct=12.0, max_moisture_pct=13.0,
                raw={"min_moisture_pct": "12 - 13 %", "max_moisture_pct": "12 - 13 %"})
    assert check_range_narrowed(both)["status"] == "pass"
    upper = fact(subtype="StorageRule", min_moisture_pct=None, max_moisture_pct=13.0,
                 raw={"max_moisture_pct": "12 - 13 %"})
    assert "max_moisture_pct 13 from '12 - 13 %'" in check_range_narrowed(upper)["reason"]
    equal = fact(subtype="StorageRule", min_moisture_pct=13.0, max_moisture_pct=13.0,
                 raw={"min_moisture_pct": "12 - 13 %", "max_moisture_pct": "12 - 13 %"})
    assert check_range_narrowed(equal)["status"] == "fail"                     # equal bounds still narrow it


def test_range_narrowed_covers_amounts_offsets_and_conditions():
    dose = fact(steps=[step(applies=[qty("ai:x", value=1000, unit="ml", raw="Fipronil 5% SC 1000-1500 ml")])])
    assert check_range_narrowed(dose)["status"] == "fail"
    ranged = fact(steps=[step(applies=[qty("ai:x", min=1000, max=1500, unit="ml", raw="Fipronil 5% SC 1000-1500 ml")])])
    assert check_range_narrowed(ranged)["status"] == "pass"
    other = fact(steps=[step(applies=[qty("ai:x", value=25, raw="Carbofuran 3% CG 25 kg (2-3 rounds)")])])
    assert check_range_narrowed(other)["status"] == "pass"                  # 25 is not an end of the printed range
    timed = fact(steps=[step(offset_min=-7, offset_max=-7, timing_raw="7 - 10 days before harvest")])
    assert check_range_narrowed(timed)["status"] == "fail"
    cond = fact(steps=[step(conditions=[{"variable": "soil_pH", "op": ">=", "value": 6.5, "value_max": None,
                                         "raw": "pH 6.5 - 7.5"}])])
    assert check_range_narrowed(cond)["status"] == "fail"


# 8 lost glyph
def soak(conc_unit="µM"):
    """PDF p. 73 prints "80 µM concentration of sodium nitroprusside" (U+00B5 in its text layer)."""
    data = {"subtype": "SeedTreatment", "summary_en": "s", "quote": "80 µM concentration of sodium nitroprusside",
            "steps": [{"order": 1, "operation": "seed_treatment",
                       "applies": [{"target": "sodium nitroprusside", "conc_value": 80, "conc_unit": conc_unit,
                                    "conc_raw": "80 %s concentration" % conc_unit}]}]}
    return RAW.validate_python(data).model_dump(mode="json")


def test_a_replacement_character_in_any_stored_text_fails():
    assert check_lost_glyph(fact(), soak())["status"] == "pass"
    r = check_lost_glyph(fact(), soak("�M"))                                  # the v3 hand-run typo
    assert r["status"] == "fail"
    assert "step 9 steps[0].applies[0].conc_unit" in r["reason"] and "conc_raw" in r["reason"]
    good = soak()
    stored = fact(evidence=[{**SPAN, "quote": "80 �M"}])                       # the stored fact counts too
    assert "fact evidence[0].quote" in check_lost_glyph(stored, good)["reason"]


# 9 printed text
def test_each_quantity_unit_and_target_appear_in_the_quote_as_printed():
    assert check_printed_text(raw())["reason"] == "step 1 basis 'x' is not in the quote"   # the fixture's basis
    printed = raw(steps=[{"order": 1, "operation": "fertilizer_application",
                          "applies": [{"target": "DAP", "value": 40, "unit": "kg", "raw": "40 kg of DAP"}]}])
    assert check_printed_text(printed)["status"] == "pass"
    wrong_target = raw(steps=[{"order": 1, "operation": "fertilizer_application",
                               "applies": [{"target": "urea", "value": 40, "unit": "kg", "raw": "40 kg of DAP"}]}])
    assert check_printed_text(wrong_target)["reason"] == "step 1 target 'urea' is not in the quote"
    wrong_unit = raw(steps=[{"order": 1, "operation": "fertilizer_application",
                             "applies": [{"target": "DAP", "value": 40, "unit": "g", "raw": "40 kg of DAP"}]}])
    assert check_printed_text(wrong_unit)["reason"] == "step 1 unit 'g' is not in the quote"   # "g" is not in "kg"
    assert check_printed_text(soak())["status"] == "pass"
    assert check_printed_text(soak("�M"))["reason"] == "step 1 conc_unit '�M' is not in the quote"
    counted = raw(quote="Release Trichogramma 5 cc/ha", steps=[{"order": 1, "operation": "release",
                  "applies": [{"target": "Trichogramma", "value": 5, "unit": "count", "raw": "Trichogramma 5"}]}])
    assert check_printed_text(counted)["status"] == "pass"                     # prompt v2's placeholder unit


def test_every_copied_text_is_printed_in_the_quote_its_row_or_flagged_heading():
    """2026-10-21: names, stages, observations, structures, methods and maturity signs, not only quantities."""
    def any_raw(subtype, **fields):
        return RAW.validate_python({"subtype": subtype, "summary_en": "s", **fields}).model_dump(mode="json")

    sign = any_raw("HarvestRule", quote="If the rice is clear and firm, it is in hard dough stage.",
                   maturity_signs=["dehusked rice is clear and firm (hard dough stage)"])
    r = check_printed_text(sign)
    assert r["reason"] == ("maturity_signs[0] 'dehusked rice is clear and firm (hard dough stage)' is not in the "
                           "quote (prompt v3 allows a short phrase here)")
    sign["maturity_signs"] = ["the rice is clear and firm"]
    assert check_printed_text(sign)["status"] == "pass"
    store = any_raw("StorageRule", quote="Store the seeds in polylined gunny bag", structure="polythene bag")
    assert check_printed_text(store)["reason"] == "structure 'polythene bag' is not in the quote"
    cased = raw(steps=[{"order": 1, "operation": "fertilizer_application", "method": "apply",
                        "applies": [{"target": "DAP", "value": 40, "unit": "kg", "raw": "40 kg of DAP"}]}])
    r = check_printed_text(cased)
    assert r["status"] == "pass" and r["case_only"] == ["step 1 method"]          # "Apply" in the quote
    cell = any_raw("ControlMeasure", quote="Spray phenthoate 50% EC 1000 ml", control_class="chemical",
                   targets=["Case worm Parapoynx stagnalis"], steps=[{"order": 1, "operation": "spraying"}])
    assert check_printed_text(cell)["status"] == "fail"
    row = "Case worm Parapoynx stagnalis | Spray phenthoate 50% EC 1000 ml"
    assert check_printed_text(cell, row=row)["status"] == "pass"                 # the pest is the row's first cell
    soil = raw(quote="Basal application of gypsum @ 500 kg / ha.", soils=["saline soil condition"],
               steps=[{"order": 1, "operation": "fertilizer_application",
                       "applies": [{"target": "gypsum", "value": 500, "unit": "kg", "raw": "500 kg"}]}])
    heading = "Recommendation for planting under saline soil condition"
    assert check_printed_text(soil, subheading=heading)["status"] == "fail"      # not flagged: heading not read
    soil["extraction_flags"] = ["scope_from_heading"]
    assert check_printed_text(soil, subheading=heading)["status"] == "pass"
    assert table_rows(["[#/tables/56 row 3] " + row, "[#/tables/56 row 4] Hispa"], ["#/tables/56 row 3"]) == row


# 10 scope in unmapped (approved 2026-10-21): every unmapped phrase of the TNAU v3 runs

SCOPE = {
    "for hybrids": ["variety"],                                                       # b879#3 (gold A5)
    "depending on the height of the seedlings": ["condition"],                        # b879#14, kept blocked
    "when the seedlings are to be pulled out in 20-25 days after sowing in less fertile nursery soils":
        ["condition"],                                                                # b879#19 (A38)
    "In BPH prone areas/seasons": ["area"],                                           # e63c#9 (B35)
    "in tungro endemic area": ["area"],                                               # e63c#17
    "submergence of recommended level during critical periods only": ["condition"],   # e63c#56
    "at 10 per cent moisture content": ["moisture"],                                  # f5b0#21 (C13b, C14, C15)
}
NOT_SCOPE = [
    "especially in BPH and leaffolder prone areas/seasons",       # e63c#5: "especially" narrows nothing
    "especially",
    "Taking the average duration of the crop as an indication", "Even at this stage, the leaves of some of the "
    "varieties may remain green.", "Maturity may be hastened by 3-4 days", "to escape monsoon rains", "for 10 hrs",
    "leave for 24hrs", "overnight", "sprout for 24hrs", "1lit of water", "for 30 minutes", "Thereafter",
    "fully decomposed", "can be followed", "30 cm space at every 2.5 m", "second a week later", "at 0.005%",
    "(45 x 30 cms)", "preferably", "(1' for every 8')", "ETL based insecticide / fungicide application",
    "in equal volume", "for 12 - 16 h", "for 16 h", "to original moisture content", "for 12 h",
    "at the ratio of 1 : 1", "to original seed moisture content", "for 16 hrs", "Shallow planting",
    "(CaOCl2 + CaCO3 + arappu (Albizzia amara) leaf powder mixed in the ratio of 5:4:1)",
]


@pytest.mark.parametrize("phrase, kinds", SCOPE.items())
def test_a_scope_like_unmapped_phrase_is_flagged(phrase, kinds):
    assert scope_phrases([phrase]) == [(phrase, kinds)]
    r = check_scope_in_unmapped(fact(unmapped=["Thereafter", phrase]))
    assert r["status"] == "fail" and r["phrases"] == [phrase]


@pytest.mark.parametrize("phrase", NOT_SCOPE)
def test_other_unmapped_phrases_are_not_scope(phrase):
    assert scope_phrases([phrase]) == []
    assert check_scope_in_unmapped(fact(unmapped=[phrase]))["status"] == "pass"


def test_no_unmapped_phrase_passes():
    assert check_scope_in_unmapped(fact())["status"] == "pass"
