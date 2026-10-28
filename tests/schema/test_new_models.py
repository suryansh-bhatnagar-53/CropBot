"""The seven subtypes outside the first slice, and the concept models added for step 10."""

import copy

import pytest
from pydantic import ValidationError

from kg.schema import FACT
from kg.schema.concepts import ActiveIngredient, Disease, Fertilizer, OrganicInput, Pest, Weed

from .examples import fact, span

SPAN = span("span:x", 30, "Rice > 1.1.1. Wet nursery", "quote")
STEP = {"order": 1, "operation": "sowing", "instruction_en": "Use 30 kg seed per ha."}


@pytest.mark.parametrize("subtype, fields", [
    ("SeedRate", {"method": "transplanted", "steps": [STEP]}),
    ("Spacing", {"row_cm": 20, "plant_cm": 15, "raw": {"row_cm": "20", "plant_cm": "15 cm"}}),
    ("SeedTreatment", {"steps": [{**STEP, "operation": "seed_treatment"}]}),
    ("IrrigationRule", {"depth_cm": 2.5, "raw": {"depth_cm": "2.5 cm"}, "criterion": "hairline cracks"}),
    ("DoseFormula", {"target_nutrient": "nutrient:n", "coefficients": {"T": 4.25, "SN": 0.45},
                     "raw": {"coefficients": "FN = 4.25 T - 0.45 SN"}}),
    ("WeatherRule", {"operation": "spraying", "advice": "avoid"}),
    ("QualitySpec", {"authority": "DFPD", "commodity_form": "paddy", "grades": ["grade_a", "common"],
                     "grades_origin": "section", "grades_evidence": "UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY",
                     "parameter": "moisture", "parameter_raw": "Moisture content", "limit_type": "max",
                     "limit_value": 17, "unit": "pct", "raw": {"limit_value": "17.0"}}),
])
def test_the_other_seven_subtypes_validate(subtype, fields):
    assert FACT.validate_python(fact("rec:x", subtype, "s", SPAN, **fields)).subtype == subtype


@pytest.mark.parametrize("subtype, fields, message", [
    ("Spacing", {"row_cm": 20}, "raw\\['row_cm'\\]"),
    ("SeedTreatment", {}, "needs at least one Step"),
    ("DoseFormula", {"target_nutrient": "fertilizer:urea"}, "is not a nutrient id"),
    ("QualitySpec", {"parameter": "moisture"}, "authority"),
    ("WeatherRule", {"advice": "maybe"}, "advice"),
])
def test_the_other_seven_subtypes_reject(subtype, fields, message):
    with pytest.raises(ValidationError, match=message):
        FACT.validate_python(fact("rec:x", subtype, "s", copy.deepcopy(SPAN), **fields))


def test_active_ingredient_reg_status_defaults_to_unknown():
    ai = ActiveIngredient(id="ai:chlorantraniliprole", name_en="Chlorantraniliprole", use_class="insecticide",
                          review_status="needs_review")
    assert ai.reg_status.value == "unknown"


def test_new_concepts_check_their_ids_and_vocabularies():
    Pest(id="pest:brown_planthopper", name_en="Brown planthopper", scientific_name="Nilaparvata lugens",
         pest_type="insect", review_status="needs_review")
    Disease(id="disease:blast", name_en="Blast", review_status="needs_review")
    Weed(id="weed:echinochloa", name_en="Barnyard grass", weed_type="grass", review_status="needs_review")
    OrganicInput(id="organic_input:fym", name_en="FYM", kind="fym", review_status="needs_review")
    with pytest.raises(ValidationError, match="is not a pest id"):
        Pest(id="disease:blast", name_en="x", pest_type="insect", review_status="needs_review")
    with pytest.raises(ValidationError, match="kind"):
        OrganicInput(id="organic_input:x", name_en="x", kind="manure", review_status="needs_review")


ZN = '[{"nutrient_id": "nutrient:zn", "pct": 21, "raw": "21% Zn"}]'


def test_fertilizer_contains_is_edges_not_a_map_property():
    f = Fertilizer(id="fertilizer:znso4", name_en="Zinc sulphate", n_pct=0, p2o5_pct=0, k2o_pct=0,
                   contains=ZN, review_status="needs_review", source="x")
    assert f.edges() == [("CONTAINS", "Nutrient", "nutrient:zn", {"pct": 21.0, "raw": "21% Zn"})]
    assert ("contains", "nutrient:zn", "Nutrient") in f.references()
    assert "contains" not in f.props() and f.props()["n_pct"] == 0


@pytest.mark.parametrize("contains, message", [
    ('[{"nutrient_id": "nutrient:zn", "pct": 210, "raw": "x"}]', "less than or equal to 100"),
    ('[{"nutrient_id": "fertilizer:x", "pct": 2, "raw": "x"}]', "is not a nutrient id"),
    ('[{"nutrient_id": "nutrient:zn", "pct": 2}]', "raw"),
    ('[{"nutrient_id": "nutrient:zn", "pct": 2, "raw": "x"}, {"nutrient_id": "nutrient:zn", "pct": 3, "raw": "y"}]',
     "appears twice"),
])
def test_fertilizer_contains_is_checked(contains, message):
    with pytest.raises(ValidationError, match=message):
        Fertilizer(id="fertilizer:x", name_en="x", n_pct=0, p2o5_pct=0, k2o_pct=0, contains=contains,
                   review_status="needs_review", source="x")

