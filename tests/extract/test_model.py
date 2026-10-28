"""Offline tests for the raw extraction model (kg.extract.model)."""

import pytest
from pydantic import ValidationError

from kg.extract.model import FACT, RawQuantity, RawStep

DAP = {"target": "DAP", "value": 40, "unit": "kg", "basis": "per 20 cents of nursery", "basis_inferred": True,
       "raw": "40 kg of DAP"}


def nursery_dose(**over):
    fact = {"subtype": "NutrientDose", "dose_basis": "blanket", "summary_en": "DAP before the last puddling",
            "quote": "apply 40 kg of DAP",
            "steps": [{"order": 1, "operation": "fertilizer_application", "anchor": "last_puddling",
                       "timing_raw": "before the last puddling", "instruction_en": "Apply DAP.", "applies": [DAP]}]}
    return {**fact, **over}


def test_names_units_and_bases_stay_as_printed():
    fact = FACT.validate_python(nursery_dose())
    q = fact.steps[0].applies[0]
    assert (q.target, q.unit, q.basis, q.basis_inferred) == ("DAP", "kg", "per 20 cents of nursery", True)


def test_all_16_subtypes_parse():
    from kg.schema.vocab import Subtype
    from kg.extract.model import SUBTYPES
    assert len(SUBTYPES) == 16 == len(Subtype)


@pytest.mark.parametrize("change, message", [
    ({"unit": None}, "raw phrase and its unit"),
    ({"raw": None}, "raw phrase and its unit"),
    ({"basis_rule": "per ha rule"}, "not inferred"),
    ({"value": None}, "quantity_ref='previous'"),
    ({"quantity_ref": "previous"}, "only for an amount stated earlier"),
])
def test_quantity_rules(change, message):
    with pytest.raises(ValidationError, match=message):
        RawQuantity(**{**DAP, **change})


def test_basis_may_be_empty_but_not_flagged_without_one():
    RawQuantity(target="NaCl", value=20, unit="%", raw="20% NaCl")
    with pytest.raises(ValidationError, match="need the basis they give"):
        RawQuantity(target="NaCl", value=20, unit="%", raw="20% NaCl", basis_inferred=True)


def test_amount_stated_earlier():
    q = RawQuantity(target="DAP", quantity_ref="previous")
    assert q.value is None and q.quantity_ref == "previous"


def test_step_timing_needs_its_words_and_hours_need_offsets():
    with pytest.raises(ValidationError, match="timing_raw"):
        RawStep(order=1, anchor="sowing", offset_min=18, instruction_en="Drain.")
    with pytest.raises(ValidationError, match="offset_unit hours set without offsets"):
        RawStep(order=1, offset_unit="hours", instruction_en="Drain.")
    s = RawStep(order=1, operation=None, anchor="sowing", offset_min=18, offset_max=24, offset_unit="hours",
                timing_raw="18 to 24 hrs after sowing", instruction_en="Drain the water.")
    assert s.operation is None                       # no operation type fits: left empty, reported


def test_numeric_subtype_fields_need_raw_text():
    spec = {"subtype": "DryingSpec", "summary_en": "Dry grain to 12%", "quote": "Dry the grains to 12%",
            "target_moisture_pct_max": 12}
    with pytest.raises(ValidationError, match="raw\\['target_moisture_pct_max'\\]"):
        FACT.validate_python(spec)
    FACT.validate_python({**spec, "raw": {"target_moisture_pct_max": "12%"}})


def test_unknown_condition_variable_and_vocabulary_are_rejected():
    clause = {"observation": "hoppers", "value": 2, "sampling_unit": "/tiller", "raw": "2 hoppers/tiller",
              "conditions": [{"variable": "spiders", "op": ">=", "value": 1, "raw": "spider is present at 1/hill"}]}
    fact = {"subtype": "PestThreshold", "summary_en": "BPH ETL", "quote": "2 hoppers/tiller", "pests": ["BPH"],
            "clauses": [clause]}
    with pytest.raises(ValidationError, match="unknown condition variable"):
        FACT.validate_python(fact)
    clause["conditions"][0]["variable"] = "spider_count_per_hill"
    FACT.validate_python(fact)
    with pytest.raises(ValidationError):
        FACT.validate_python(nursery_dose(dose_basis="per_ha"))


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError, match="Extra inputs"):
        FACT.validate_python(nursery_dose(crop_id="crop:rice"))
