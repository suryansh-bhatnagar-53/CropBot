"""Prompt v3 (schema v1.3) in the raw model: strengths, mixing parts and shares as printed, repeat words,
min moisture, seedling ranges, Caution ABOUT, the two new flags, and the fields v1 and v2 never had."""

import pytest
from pydantic import ValidationError

from kg.extract.model import FACT, RawQuantity, RawStep
from kg.extract.versions import V3_FIELDS, field_names, version_problems


def test_strength_parts_and_share_are_kept_as_printed():
    kcl = RawQuantity(target="KCl", conc_value=1, conc_unit="%", conc_raw="1% KCl solution")
    assert kcl.value is None and kcl.conc_unit == "%"
    bait = RawQuantity(target="zinc phosphide", ratio_part=1, ratio_rest=49,
                       ratio_raw="1 part zinc phosphide with 49 parts popped corn/rice/dry fish")
    assert (bait.ratio_part, bait.ratio_rest) == (1, 49)                 # the model never adds them up
    assert RawQuantity(target="K", share_pct=50, share_raw="basal (50%)").share_pct == 50
    with pytest.raises(ValidationError, match="conc_unit and conc_raw"):
        RawQuantity(target="KCl", conc_value=1)
    with pytest.raises(ValidationError, match="ratio_part, ratio_rest and ratio_raw"):
        RawQuantity(target="x", ratio_part=1, ratio_raw="1 part")
    with pytest.raises(ValidationError, match="no amount"):
        RawQuantity(target="x")


def test_repeat_words_stay_text():
    s = RawStep(order=1, operation="release", repeat_raw="thrice (at weekly interval")
    assert s.repeat_raw == "thrice (at weekly interval" and "repeat_count" not in RawStep.model_fields


def test_storage_min_moisture_spacing_range_and_caution_about():
    store = FACT.validate_python({"subtype": "StorageRule", "summary_en": "s", "quote": "q",
                                  "min_moisture_pct": 12, "max_moisture_pct": 13,
                                  "raw": {"min_moisture_pct": "12 - 13 %", "max_moisture_pct": "12 - 13 %"}})
    assert store.min_moisture_pct == 12
    spacing = FACT.validate_python({"subtype": "Spacing", "summary_en": "s", "quote": "q",
                                    "seedlings_per_hill_min": 3, "seedlings_per_hill_max": 4,
                                    "raw": {"seedlings_per_hill_min": "3 - 4", "seedlings_per_hill_max": "3 - 4"}})
    assert spacing.seedlings_per_hill_max == 4
    caution = FACT.validate_python({"subtype": "Caution", "summary_en": "s", "quote": "q", "kind": "prohibition",
                                    "text_en": "t", "concerns": ["synthetic pyrethroids"],
                                    "about": ["BPH, Nilaparvata lugens"]})
    assert caution.about == ["BPH, Nilaparvata lugens"]


def test_versions_keep_their_own_fields_and_flags():
    assert V3_FIELDS <= field_names("v3") and not V3_FIELDS & field_names("v2")
    assert "seedlings_per_hill" in field_names("v2") and "seedlings_per_hill" not in field_names("v3")
    fact = {"subtype": "SeedTreatment", "extraction_flags": ["operation_from_formulation"],
            "steps": [{"order": 1, "applies": [{"target": "KCl", "conc_value": 1}]}]}
    v2 = version_problems(fact, "v2")
    assert any("not a flag of prompt v2" in p for p in v2) and any("conc_value" in p for p in v2)
    assert version_problems(fact, "v3") == []
