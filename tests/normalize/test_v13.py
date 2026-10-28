"""Schema v1.3 in steps 10 to 12: strengths, ratios and shares, repeat words, sample sizes, Inputs, AI groups
and ABOUT, flags kept on the fact, fact_key with the step method and anchor, the new claims."""

import copy

import pytest

from kg.extract.model import FACT as RAW
from kg.normalize import Fact, build, fact_key_parts
from kg.normalize.link import Linker
from kg.normalize.units import canon_conc_unit, repeat, sample
from kg.schema import FACT
from kg.schema.concepts import (ActiveIngredient, AIGroup, Fertilizer, Input, Label, Nutrient, Pest)
from kg.validate import check_raw_numbers
from kg.verify.claims import claims_for

NODES = [
    Fertilizer(id="fertilizer:mop", name_en="Muriate of potash (MOP)", n_pct=0, p2o5_pct=0, k2o_pct=60,
               review_status="needs_review", source="x"),
    Label(concept_id="fertilizer:mop", text="KCl", lang="en", script="Latn", kind="alias", review_status="approved"),
    Input(id="input:trichogramma_japonicum", name_en="Trichogramma japonicum", kind="bioagent",
          review_status="needs_review"),
    Input(id="input:gypsum", name_en="Gypsum", kind="amendment", review_status="needs_review"),
    AIGroup(id="ai_group:synthetic_pyrethroids", name_en="Synthetic pyrethroids", review_status="needs_review"),
    ActiveIngredient(id="ai:zinc_phosphide", name_en="Zinc phosphide", review_status="needs_review"),
    ActiveIngredient(id="ai:acephate", name_en="Acephate", review_status="needs_review"),
    Pest(id="pest:brown_planthopper", name_en="Brown planthopper", pest_type="insect", review_status="approved"),
    Label(concept_id="pest:brown_planthopper", text="BPH", lang="en", script="Latn", kind="abbreviation",
          review_status="approved"),
    Pest(id="pest:earhead_bug", name_en="Earhead bug", pest_type="insect", review_status="approved"),
    Nutrient(id="nutrient:k2o", name_en="Potassium", symbol="K2O", review_status="approved"),
]
L = Linker(NODES)
UNIT = {"id": "unit:tnau_agriculture_2020:abc", "source_id": "source:tnau_agriculture_2020",
        "section_path": "RICE > CROP PROTECTION", "pdf_pages": [64, 64],
        "regions": [{"id": "state:33", "origin": "source"}], "purposes": [], "default_scope": []}
RUN = {"extraction_model": "m", "prompt_version": "v3", "cache_key": "k" * 64}
QC = {"ok": True, "occurrences": 1, "refs": ["#/texts/1"], "pdf_pages": [64], "printed_pages": ["52"]}


def raw(**data):
    return Fact(RUN, UNIT, {"index": 0, "fact": RAW.validate_python({"summary_en": "s", "quote": "q", **data})
                            .model_dump(mode="json"), "quote_check": QC})


def finish(f, d):
    d["evidence"] = [{"id": "span:x", "source_id": UNIT["source_id"], "pdf_page": 64, "section_path": "s",
                      "quote": "q", "extraction_method": "native_text"}]
    d["fact_key"], d["id"], d["status"] = "fk:x", "rec:x", "needs_review" if f.review else "extracted"
    for s in d["steps"]:
        s["instruction_en"] = "x"
    return FACT.validate_python(d).model_dump(mode="json")


@pytest.mark.parametrize("printed, unit", [("%", "pct"), ("N", "normal"), ("µM", "micromolar"), ("w/w", "pct"),
                                           ("�M", None), ("ppm", None)])
def test_strength_units(printed, unit):
    got = canon_conc_unit(printed)
    assert (got.value if got else None) == unit


@pytest.mark.parametrize("printed, expected", [
    ("thrice (at weekly interval", (3, 1, "weeks")),
    ("twice", (2, None, None)),
    ("at fortnightly interval", (None, 2, "weeks")),
    ("4 times at 10 days interval", (4, 10, "days")),
    ("second a week later", (None, 1, "weeks")),            # schema v1.4 word table: "a week" is 1 week
    ("second a fortnight on", None),                       # not in the word table: held, never guessed
])
def test_repeat_word_table(printed, expected):
    got = repeat(printed)
    if expected is None:
        assert got is None
    else:
        assert (got[0], got[1], got[2].value if got[2] else None) == expected


@pytest.mark.parametrize("printed, expected", [("/25 net sweeps", (25, "net_sweep")), ("/100 ear heads", (100, "earhead")),
                                               ("in 12 passes", (12, "pass")), ("/tiller", None)])
def test_sample_sizes(printed, expected):
    got = sample(printed)
    assert (None if got is None else (got[0], got[1].value)) == expected


def test_strength_only_quantity_links_kcl_to_mop_and_validates():
    f = raw(subtype="SeedTreatment", steps=[{"order": 1, "operation": "seed_treatment", "method": "soak",
                                            "applies": [{"target": "KCl", "conc_value": 1, "conc_unit": "%",
                                                         "conc_raw": "1% KCl solution"}]}])
    d = build(f, L, "crop:rice", {})
    a = d["steps"][0]["applies"][0]
    assert (a["target_id"], a["conc_value"], a["conc_unit"], a["conc_raw"]) == ("fertilizer:mop", 1, "pct",
                                                                               "1% KCl solution")
    assert not f.blocks and finish(f, d)["steps"][0]["applies"][0]["conc_unit"] == "pct"
    assert claims_for(finish(f, d), {}, {"applies": [["KCl"]]}) == [
        "Does the passage state that KCl 1% is applied?"]


def test_a_damaged_strength_glyph_is_held():
    f = raw(subtype="SeedTreatment", steps=[{"order": 1, "operation": "seed_treatment", "applies": [
        {"target": "gypsum", "conc_value": 80, "conc_unit": "�M", "conc_raw": "80 �M"}]}])
    build(f, L, "crop:rice", {})
    assert f.blocks == ["no canonical strength unit for '�M'; raw '80 �M'"]


def test_ratio_whole_is_computed_by_code_and_numbers_are_checked_on_the_parts():
    bait = {"subtype": "ControlMeasure", "control_class": "chemical", "targets": ["Brown planthopper"],
            "quote": "Poison bait at 1 part zinc phosphide with 49 parts popped corn",
            "steps": [{"order": 1, "operation": "baiting", "method": "poison bait",
                       "applies": [{"target": "zinc phosphide", "ratio_part": 1, "ratio_rest": 49,
                                    "ratio_raw": "1 part zinc phosphide with 49 parts"}]}]}
    f = raw(**bait)
    d = build(f, L, "crop:rice", {})
    a = d["steps"][0]["applies"][0]
    assert (a["ratio_part"], a["ratio_whole"]) == (1, 50) and "ratio 1 part with 49 parts -> 1 in 50" in \
        f.conversions[-1]["rule"]
    assert check_raw_numbers(f.raw)["status"] == "pass"
    wrong = copy.deepcopy(bait)
    wrong["steps"][0]["applies"][0]["ratio_rest"] = 48
    assert check_raw_numbers(raw(**wrong).raw)["status"] == "fail"
    assert claims_for(finish(f, d), {}, {"applies": [["zinc phosphide"]], "target_ids": ["BPH"]}) == [
        "Does the passage state that zinc phosphide is applied against BPH at 1 part with 49 parts?"]


def test_repeat_words_become_fields_and_claims_in_the_table_words():
    f = raw(subtype="ControlMeasure", control_class="biological", targets=["Brown planthopper"],
            quote="Release Trichogramma japonicum thrice (at weekly interval from 37 DAT) @ 1,00,000/ha",
            steps=[{"order": 1, "operation": "release", "anchor": "transplanting", "offset_min": 37, "offset_max": 37,
                    "timing_raw": "from 37 DAT", "repeat_raw": "thrice (at weekly interval",
                    "applies": [{"target": "Trichogramma japonicum", "value": 100000, "unit": "count", "basis": "/ha",
                                 "raw": "@ 1,00,000/ha"}]}])
    d = build(f, L, "crop:rice", {})
    s = d["steps"][0]
    assert (s["repeat_count"], s["repeat_interval"], s["repeat_interval_unit"]) == (3, 1, "weeks")
    assert s["applies"][0]["target_id"] == "input:trichogramma_japonicum" and not f.blocks
    (claim,) = claims_for(finish(f, d), {}, {"applies": [["Trichogramma japonicum"]], "target_ids": ["BPH"]})
    assert claim.endswith("37 days after transplanting thrice at weekly interval?")
    held = raw(subtype="ControlMeasure", control_class="biological", targets=["Brown planthopper"],
               steps=[{"order": 1, "operation": "release", "repeat_raw": "second a fortnight on"}])
    build(held, L, "crop:rice", {})
    assert held.blocks == ["repeat words 'second a fortnight on' are not in the code word table"]


def test_sample_sizes_storage_range_spacing_and_caution_about():
    f = raw(subtype="PestThreshold", pests=["Earhead bug"],
            clauses=[{"observation": "insects", "value": 5, "sampling_unit": "/25 net sweeps", "raw": "5/25 net sweeps"}])
    d = build(f, L, "crop:rice", {})
    assert (d["clauses"][0]["sampling_count"], d["clauses"][0]["sampling_object"]) == (25, "net_sweep")
    assert claims_for(finish(f, d), {}, {"pest_ids": ["Earhead bug"]}) == [
        "Does the passage state that action against Earhead bug is needed at 5 insects per 25 net sweeps?"]
    store = FACT.validate_python({"id": "rec:s", "fact_key": "fk:s", "subtype": "StorageRule", "summary_en": "s",
                                  "crop_ids": ["crop:rice"], "regions": [{"id": "state:33", "origin": "source"}],
                                  "evidence": [{"id": "span:s", "source_id": "source:tnau_agriculture_2020",
                                                "pdf_page": 75, "section_path": "s", "quote": "q",
                                                "extraction_method": "native_text"}],
                                  "storage_months_min": 8, "storage_months_max": 9, "min_moisture_pct": 12,
                                  "max_moisture_pct": 13, "raw": {"storage_months_min": "8-9 months",
                                                                  "storage_months_max": "8-9 months",
                                                                  "min_moisture_pct": "12 - 13 %",
                                                                  "max_moisture_pct": "12 - 13 %"}}).model_dump(mode="json")
    assert claims_for(store, {}) == ["Does the passage state that it is stored for 8 to 9 months at a moisture "
                                     "content of 12 to 13%?"]
    spacing = {**store, "subtype": "Spacing", "raw": {"seedlings_per_hill_min": "3 - 4",
                                                     "seedlings_per_hill_max": "3 - 4"},
               "seedlings_per_hill_min": 3, "seedlings_per_hill_max": 4}
    assert claims_for(spacing, {}) == ["Does the passage state that 3 to 4 seedlings are planted per hill?"]
    caution = raw(subtype="Caution", kind="prohibition", text_en="t", concerns=["acephate", "synthetic pyrethroids"],
                  about=["BPH"], extraction_flags=["scope_from_heading"])
    d = build(caution, L, "crop:rice", {})
    assert d["concerns"] == ["ai:acephate", "ai_group:synthetic_pyrethroids"] and d["about_ids"] == [
        "pest:brown_planthopper"]
    assert d["extraction_flags"] == ["scope_from_heading"] and finish(caution, d)["extraction_flags"] == [
        "scope_from_heading"]
    assert claims_for(finish(caution, d), {}, {"concerns": ["acephate", "synthetic pyrethroids"], "about_ids": ["BPH"]}
                      )[1] == "Does the passage state that it advises against using synthetic pyrethroids for BPH?"


def test_fact_key_tells_apart_steps_by_method_and_anchor():
    def key(method):
        f = raw(subtype="IrrigationRule", steps=[{"order": 1, "operation": "irrigation", "method": method}])
        return fact_key_parts(f, build(f, L, "crop:rice", {}))
    assert key("saturate the soil") != key(None)
