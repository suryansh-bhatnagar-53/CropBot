"""Schema v1.3 additions to the models: concentrations, ratios and shares on APPLIES, repeats on Steps,
sampling counts on clauses, StorageRule min moisture, Spacing ranges, Caution groups and ABOUT, the Input
and AIGroup concepts, and the flags and notes kept on a fact."""

import pytest
from pydantic import ValidationError

from kg.schema import FACT
from kg.schema.concepts import ActiveIngredient, AIGroup, Input
from kg.schema.core import Applies, Step, ThresholdClause

SPAN = {"id": "span:x", "source_id": "source:tnau_agriculture_2020", "pdf_page": 75, "section_path": "RICE > SEED",
        "quote": "q", "extraction_method": "native_text"}
CORE = {"id": "rec:x", "fact_key": "fk:x", "summary_en": "s", "crop_ids": ["crop:rice"],
        "regions": [{"id": "state:33", "origin": "source"}], "evidence": [SPAN]}


def test_strength_ratio_and_share_need_no_dose():
    kcl = Applies(target_id="fertilizer:mop", conc_value=1, conc_unit="pct", conc_raw="1% KCl solution")
    assert kcl.value is None and kcl.conc_value == 1
    bait = Applies(target_id="ai:zinc_phosphide", ratio_part=1, ratio_whole=50,
                   ratio_raw="1 part zinc phosphide with 49 parts popped corn")
    assert bait.ratio_whole == 50
    split = Applies(target_id="nutrient:k2o", share_pct=50, share_raw="basal (50%)")
    assert split.share_pct == 50
    snp = Applies(target_id="input:sodium_nitroprusside", conc_min=80, conc_max=80, conc_unit="micromolar",
                  conc_raw="80 µM")
    assert snp.conc_unit == "micromolar"


@pytest.mark.parametrize("kw, message", [
    ({}, "no amount"),
    ({"conc_value": 1, "conc_unit": "pct"}, "conc_raw"),
    ({"conc_value": 1, "conc_min": 1, "conc_unit": "pct", "conc_raw": "1%"}, "either conc_value"),
    ({"conc_unit": "pct", "conc_raw": "1%"}, "without a concentration value"),
    ({"ratio_part": 1, "ratio_raw": "1 part"}, "ratio_part, ratio_whole and ratio_raw"),
    ({"ratio_part": 50, "ratio_whole": 1, "ratio_raw": "50:1"}, "less than ratio_whole"),
    ({"share_pct": 50}, "share_pct and share_raw"),
    ({"conc_value": 5, "conc_unit": "percent", "conc_raw": "5%"}, "conc_unit"),
])
def test_bad_quantities(kw, message):
    with pytest.raises(ValidationError, match=message):
        Applies(target_id="ai:x", **kw)


def test_applies_may_target_an_input_but_not_a_group():
    assert Applies(target_id="input:trichogramma_japonicum", value=100000, unit="count", basis="per_ha",
                   raw="@ 1,00,000/ha").target_id.startswith("input:")
    with pytest.raises(ValidationError):
        Applies(target_id="ai_group:synthetic_pyrethroids", value=1, unit="kg", basis="per_ha", raw="1 kg")


def test_repeats():
    s = Step(order=1, operation="release", instruction_en="Release.", repeat_count=3, repeat_interval=1,
             repeat_interval_unit="weeks", repeat_raw="thrice (at weekly interval")
    assert s.repeat_interval_unit == "weeks"
    for bad in ({"repeat_count": 3}, {"repeat_raw": "thrice"},
                {"repeat_interval": 1, "repeat_raw": "weekly"},
                {"repeat_interval": 1, "repeat_interval_unit": "months", "repeat_raw": "monthly"}):
        with pytest.raises(ValidationError):
            Step(order=1, operation="release", instruction_en="Release.", **bad)
    assert Step(order=1, operation="dusting", instruction_en="Dust.").operation == "dusting"
    assert Step(order=1, operation="sanitation", instruction_en="Destroy.").operation == "sanitation"


def test_sampling_counts():
    c = ThresholdClause(observation="insects", value=1, unit="count", sampling_count=25,
                        sampling_object="net_sweep", raw="1/25 net sweeps")
    assert c.sampling_object == "net_sweep"
    for bad in ({"sampling_count": 25}, {"sampling_count": 25, "sampling_object": "hill"},
                {"sampling_count": 25, "sampling_object": "earhead", "sampling_unit": "per_hill"}):
        with pytest.raises(ValidationError):
            ThresholdClause(observation="x", value=1, unit="count", raw="r", **bad)


def test_storage_keeps_both_moisture_bounds():
    f = FACT.validate_python({**CORE, "subtype": "StorageRule", "storage_months_min": 8, "storage_months_max": 9,
                              "min_moisture_pct": 12, "max_moisture_pct": 13,
                              "raw": {"storage_months_min": "8-9 months", "storage_months_max": "8-9 months",
                                      "min_moisture_pct": "12 - 13 %", "max_moisture_pct": "12 - 13 %"}})
    assert (f.min_moisture_pct, f.max_moisture_pct) == (12, 13)
    with pytest.raises(ValidationError, match="greater than"):
        FACT.validate_python({**CORE, "subtype": "StorageRule", "min_moisture_pct": 14, "max_moisture_pct": 13,
                              "raw": {"min_moisture_pct": "14", "max_moisture_pct": "13"}})


def test_spacing_range_and_flags_and_notes():
    f = FACT.validate_python({**CORE, "subtype": "Spacing", "seedlings_per_hill_min": 3, "seedlings_per_hill_max": 4,
                              "raw": {"seedlings_per_hill_min": "3 - 4", "seedlings_per_hill_max": "3 - 4"},
                              "extraction_flags": ["scope_from_heading"], "review_notes": ["n"]})
    assert f.seedlings_per_hill_max == 4 and f.extraction_flags == ["scope_from_heading"]
    with pytest.raises(ValidationError):
        FACT.validate_python({**CORE, "subtype": "Spacing", "extraction_flags": ["guessed"]})


def test_caution_concerns_a_group_and_is_about_a_pest():
    f = FACT.validate_python({**CORE, "subtype": "Caution", "kind": "prohibition", "text_en": "Avoid pyrethroids.",
                              "concerns": ["ai_group:synthetic_pyrethroids", "ai:quinalphos"],
                              "about_ids": ["pest:brown_planthopper"]})
    assert f.about_ids == ["pest:brown_planthopper"]


def test_input_and_group_concepts():
    trap = Input(id="input:thanjavur_bow_trap", name_en="Thanjavur bow trap", kind="trap",
                 review_status="needs_review", source="TNAU p. 68")
    assert trap.LABEL == "Input" and trap.props()["kind"] == "trap"
    with pytest.raises(ValidationError):
        Input(id="input:x", name_en="x", kind="pesticide", review_status="needs_review")
    group = AIGroup(id="ai_group:synthetic_pyrethroids", name_en="synthetic pyrethroids", review_status="needs_review")
    ai = ActiveIngredient(id="ai:deltamethrin", name_en="Deltamethrin", review_status="needs_review",
                          member_of='["ai_group:synthetic_pyrethroids"]', use_class="insecticide")
    assert ai.edges() == [("MEMBER_OF", "AIGroup", group.id, {})] and "member_of" not in ai.props()
    assert ("member_of", group.id, "AIGroup") in ai.references()
    assert ActiveIngredient(id="ai:dicofol", name_en="Dicofol", review_status="needs_review",
                            use_class="acaricide").use_class == "acaricide"
