"""Offline tests for code-built Jev claims (kg.verify.claims)."""

import pytest

from kg.verify.claims import claim_key, claims_for, control_claim, printed_in_unit, printed_names

NAMES = {"fertilizer:dap": "Diammonium phosphate (DAP)", "pest:brown_planthopper": "Brown planthopper",
         "purpose:seed": "Seed", "ai:quinalphos": "Quinalphos", "organic_input:azospirillum": "Azospirillum",
         "soil:clay": "Clay"}


def step(**kw):
    s = {"order": 1, "alt_group": None, "alt_option": None, "operation": "fertilizer_application", "method": None,
         "anchor": None, "offset_min": None, "offset_max": None, "offset_unit": "days", "timing_raw": None,
         "condition_raw": None, "applies": [], "conditions": []}
    return {**s, **kw}


def fact(subtype="NutrientDose", **kw):
    return {"id": "rec:x", "fact_key": "fk:x", "subtype": subtype, "duration_group": None, "variety_ids": [],
            "soil_ids": [], "system_ids": [], "purpose_ids": [], "steps": [], **kw}


DAP = {"target_id": "fertilizer:dap", "value": 2, "unit": "kg", "basis": "per_cent_nursery", "area_cents": 20,
       "formulation": None, "raw": "40 kg of DAP"}


def test_nursery_dose_is_stated_in_the_books_terms():
    f = fact(steps=[step(anchor="last_puddling", timing_raw="before the last puddling", applies=[DAP])])
    assert claims_for(f, NAMES) == ["Does the passage state that Diammonium phosphate (DAP) is applied at 40 kg per "
                                    "20 cents of nursery before the last puddling?"]


def test_offsets_conditions_and_applicability():
    f = fact(duration_group="medium", purpose_ids=["purpose:seed"], soil_ids=["soil:clay"],
             steps=[step(anchor="pulling_out", offset_min=-10, offset_max=-10, timing_raw="10 days prior",
                         condition_raw="If seedlings are to be pulled out after 25 days",
                         applies=[{**DAP, "inherited": True}])])
    assert claims_for(f, NAMES) == [
        "Does the passage state that, for medium duration varieties grown for seed on clay soils, Diammonium "
        "phosphate (DAP) is applied at 40 kg per 20 cents of nursery 10 days before pulling out the seedlings "
        "(If seedlings are to be pulled out after 25 days)?"]


def test_threshold_clauses_and_cautions():
    f = fact("PestThreshold", pest_ids=["pest:brown_planthopper"], clauses=[
        {"observation": "hoppers", "value": 2, "unit": "count", "sampling_unit": "per_tiller",
         "conditions": [{"variable": "spider_count_per_hill", "op": ">=", "value": 1.0, "value_max": None}]}])
    assert claims_for(f, NAMES) == ["Does the passage state that action against Brown planthopper is needed at 2 "
                                    "hoppers per tiller when the spider count per hill is at least 1?"]
    caution = fact("Caution", concerns=["ai:quinalphos"])
    assert claims_for(caution, NAMES) == ["Does the passage state that it advises against using Quinalphos?"]
    assert claims_for(fact("Caution", concerns=[]), NAMES) == []                 # human review: no claim


def test_storage_and_drying_bounds():
    store = fact("StorageRule", storage_months_min=15, storage_months_min_inclusive=False, storage_months_max=None,
                 max_moisture_pct=8, max_moisture_pct_inclusive=False, structure="700 gauge polythene bag",
                 raw={"storage_months_min": "more than 15 months", "max_moisture_pct": "less than 8 %"})
    assert claims_for(store, NAMES) == ["Does the passage state that it is stored for more than 15 months at a "
                                        "moisture content below 8% in 700 gauge polythene bag?"]
    dry = fact("DryingSpec", target_moisture_pct_min=12, target_moisture_pct_max=13, storage_term_raw="short term storage")
    assert claims_for(dry, NAMES) == ["Does the passage state that the produce is dried to 12 to 13% moisture for "
                                      "short term storage?"]


def test_bound_words_only_when_printed():
    target = fact("DryingSpec", target_moisture_pct_max=12, raw={"target_moisture_pct_max": "12%"})
    assert claims_for(target, NAMES) == ["Does the passage state that the produce is dried to 12% moisture?"]
    at_most = fact("DryingSpec", target_moisture_pct_max=12, raw={"target_moisture_pct_max": "not more than 12%"})
    assert "dried to at most 12% moisture" in claims_for(at_most, NAMES)[0]
    store = fact("StorageRule", storage_months_min=15, storage_months_max=None, max_moisture_pct=13,
                 raw={"storage_months_min": "15 months", "max_moisture_pct": "13 %"})
    assert claims_for(store, NAMES) == ["Does the passage state that it is stored for 15 months at a moisture "
                                        "content of 13%?"]
    inclusive = {**store, "raw": {"storage_months_min": "at least 15 months", "max_moisture_pct": "maximum 13 %"}}
    assert claims_for(inclusive, NAMES) == ["Does the passage state that it is stored for at least 15 months at a "
                                            "moisture content of at most 13%?"]


def test_untimed_steps_fall_back_to_operation_and_method():
    f = fact("IrrigationRule", depth_cm=None, steps=[step(operation="irrigation", method="avoid stagnation of water")])
    assert claims_for(f, NAMES) == ["Does the passage state that the advice includes irrigation: avoid stagnation of water?"]
    assert claims_for(fact("Spacing"), NAMES) == []


def test_keys_are_stable_and_controls_change_one_number():
    c = "Does the passage state that x?"
    assert claim_key("fk:a", c) == claim_key("fk:a", c) and claim_key("fk:a", c) != claim_key("fk:b", c)
    assert claim_key("fk:a", c).startswith("c_") and claim_key("fk:a", c, control=True).startswith("x_")
    f = fact(steps=[step(timing_raw="before the last puddling", applies=[DAP])])
    assert control_claim(f, NAMES) == ("Does the passage state that Diammonium phosphate (DAP) is applied at 80 kg "
                                       "per 20 cents of nursery before the last puddling?")
    dry = fact("DryingSpec", target_moisture_pct_max=12, raw={"target_moisture_pct_max": "12%"})
    assert "dried to 22% moisture" in control_claim(dry, NAMES)
    assert control_claim(fact("Caution", concerns=["ai:quinalphos"]), NAMES) is None


def test_controls_also_swap_a_unit_or_name_another_pest():
    f = fact(steps=[step(timing_raw="before the last puddling", applies=[DAP])])
    assert control_claim(f, NAMES, kind="unit") == ("Does the passage state that Diammonium phosphate (DAP) is "
                                                    "applied at 40 g per 20 cents of nursery before the last puddling?")
    names = {**NAMES, "pest:army_worm": "Army worm"}
    th = fact("PestThreshold", pest_ids=["pest:brown_planthopper"], clauses=[
        {"observation": "hoppers", "value": 1, "unit": "count", "sampling_unit": "per_tiller", "conditions": []}])
    printed = {"applies": [], "pest_ids": ["BPH"], "target_ids": [], "concerns": [], "about_ids": []}
    assert claims_for(th, names, printed)[0].startswith("Does the passage state that action against BPH ")
    assert control_claim(th, names, printed, kind="pest").startswith(
        "Does the passage state that action against Army worm ")                    # first other seeded pest
    assert control_claim(th, names, printed, kind="unit") is None                   # no amount with a unit
    names["pest:zz_beetle"] = "ZZ beetle"
    unit = "Army worm: 2 hoppers / tiller\nZZ beetle: hand picking\nBPH, Nilaparvata lugens : 1 hoppers/tiller"
    swapped = control_claim(th, names, printed, kind="pest", unit_text=unit)
    assert swapped.startswith("Does the passage state that action against ZZ beetle ")   # Army worm shares a line
    terms = {"pest:army_worm": {"Army worm"}, "pest:zz_beetle": {"ZZ beetle", "ZZB"}}     # with "hoppers"
    assert control_claim(th, names, printed, kind="pest", unit_text=unit + "\nZZB 5 hoppers per hill",
                         pest_terms=terms) is None                                      # a label counts too
    assert control_claim(th, {**NAMES}, printed, kind="pest", unit_text="x") is None     # no other pest seeded
    spaced = {"pest:army_worm": {"Blue leafhopper / white leafhopper"}}
    assert control_claim(th, {**NAMES, "pest:army_worm": "Blue leafhopper / white leafhopper"}, printed,
                         kind="pest", unit_text="Blue leafhopper/ white leafhopper 5 hoppers",
                         pest_terms=spaced) is None                                     # spaces are ignored
    caution = fact("Caution", concerns=["ai:quinalphos"], about_ids=["pest:brown_planthopper"])
    assert control_claim(caution, names, kind="pest") == ("Does the passage state that it advises against using "
                                                          "Quinalphos for Army worm?")
    with pytest.raises(ValueError, match="unknown control kind"):
        control_claim(f, NAMES, kind="colour")


def test_a_control_the_unit_prints_elsewhere_is_not_used():
    """b879: 30 kg x2 = 60 kg, which the unit prints for short duration varieties."""
    unit = "[p.29] 30 kg for long duration [p.29] 60 kg for short duration varieties"
    claim = "Does the passage state that, for long duration varieties, seed is applied at 30 kg per hectare?"
    assert printed_in_unit(claim, claim.replace("30 kg", "60 kg"), unit)
    assert not printed_in_unit(claim, claim.replace("30 kg", "30 g"), unit)
    assert printed_in_unit(claim, claim.replace("30 kg", "60 kg"), "60kg for short")         # printed without a space


UREA ={**DAP, "target_id": "fertilizer:urea", "value": 0.8, "raw": "16 kg of urea"}
SSP = {**DAP, "target_id": "fertilizer:ssp", "value": 6, "raw": "120 kg of super phosphate"}


def nursery_alternatives():
    return fact(steps=[step(alt_group=1, alt_option=1, timing_raw="before the last puddling", applies=[DAP]),
                       step(alt_group=1, alt_option=2, timing_raw="before the last puddling",
                            condition_raw="if not readily available", applies=[UREA, SSP])])


def test_a_fallbacks_condition_stays_with_the_whole_fallback():
    printed = {"applies": [["DAP"], ["urea", "super phosphate"]], "pest_ids": [], "target_ids": [], "concerns": []}
    assert claims_for(nursery_alternatives(), NAMES, printed) == [
        "Does the passage state that DAP is applied at 40 kg per 20 cents of nursery before the last puddling?",
        "Does the passage state that the alternative to DAP, if not readily available, is urea 16 kg and super "
        "phosphate 120 kg per 20 cents of nursery before the last puddling?"]
    both = fact(steps=[step(condition_raw="if the soil is acidic", applies=[UREA, SSP])])
    assert claims_for(both, NAMES, {**printed, "applies": [["urea", "super phosphate"]]}) == [
        "Does the passage state that, if the soil is acidic, urea 16 kg and super phosphate 120 kg per 20 cents of "
        "nursery are applied?"]


def test_names_as_printed():
    raw = {"steps": [{"applies": [{"target": "DAP"}]}, {"applies": [{"target": "urea"}, {"target": "super phosphate"}]}]}
    printed = printed_names(raw, nursery_alternatives())
    assert printed["applies"] == [["DAP"], ["urea", "super phosphate"]]
    with pytest.raises(ValueError, match="don't line up"):
        printed_names({"steps": raw["steps"][:1]}, nursery_alternatives())
    control = fact("ControlMeasure", target_ids=["pest:stem_borer"], steps=[step(
        operation="spraying", applies=[{**DAP, "target_id": "ai:chlorpyrifos", "value": 1250, "unit": "ml",
                                        "basis": "per_ha", "formulation": "20% EC"}])])
    names = {**NAMES, "ai:chlorpyrifos": "Chlorpyrifos", "pest:stem_borer": "Stem borer"}
    p = {"applies": [["Chlorpyriphos"]], "pest_ids": [], "target_ids": ["Stem borer Scirpophaga incertulas"],
         "concerns": []}
    assert claims_for(control, names, p) == ["Does the passage state that Chlorpyriphos 20% EC is applied against "
                                             "Stem borer Scirpophaga incertulas at 1250 ml per hectare?"]
    caution = fact("Caution", concerns=["ai:chlorpyrifos"])
    assert claims_for(caution, names, {**p, "applies": [], "target_ids": [], "concerns": ["chlorpyriphos"]}) == [
        "Does the passage state that it advises against using chlorpyriphos?"]
    assert claims_for(caution, names) == ["Does the passage state that it advises against using Chlorpyrifos?"]


def test_a_conditions_raw_text_is_used():
    f = fact("PestThreshold", pest_ids=["pest:brown_planthopper"], clauses=[
        {"observation": "hoppers", "value": 1, "unit": "count", "sampling_unit": "per_tiller",
         "conditions": [{"variable": "spider_count_per_hill", "op": "<", "value": 1.0, "value_max": None,
                         "raw": "in the absence of predatory spider"}]}])
    printed = {"applies": [], "pest_ids": ["Brown planthopper"], "target_ids": [], "concerns": []}
    assert claims_for(f, NAMES, printed) == ["Does the passage state that action against Brown planthopper is needed "
                                             "at 1 hoppers per tiller in the absence of predatory spider?"]
