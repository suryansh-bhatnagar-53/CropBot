"""Prompt v4 (schema v1.4) in the raw model: repeat_offsets, durations, purpose, bait strength and carrier,
word-only ratios, a ControlMeasure with no generic target, and the version rules (v4 fields stay out of
v1 to v3; the program, not the model, sets operation_from_formulation)."""

import pytest
from pydantic import ValidationError

from kg.extract.model import FACT, RawQuantity, RawStep
from kg.extract.versions import V4_FIELDS, field_names, version_problems

GLH = dict(order=1, alt_group=1, alt_option=1, operation="spraying", anchor="transplanting",
           timing_raw="15 and 30 days after transplanting", repeat_raw="twice")


def test_an_option_list_at_stated_times():
    s = RawStep(**GLH, offset_min=15, offset_max=15, repeat_offsets=[15, 30])
    assert s.repeat_offsets == [15, 30]
    with pytest.raises(ValidationError, match="hold the first time"):
        RawStep(**GLH, offset_min=30, offset_max=30, repeat_offsets=[15, 30])
    with pytest.raises(ValidationError, match="need repeat_raw"):
        RawStep(**{**GLH, "repeat_raw": None}, offset_min=15, offset_max=15, repeat_offsets=[15, 30])


def test_durations_are_kept_as_printed():
    s = RawStep(order=1, operation="seed_treatment", duration_min=12, duration_max=16, duration_unit="h",
                duration_raw="for 12 - 16 h")
    assert (s.duration_min, s.duration_unit) == (12, "h")
    assert RawStep(order=1, operation="seed_treatment", duration_raw="overnight").duration_min is None
    with pytest.raises(ValidationError, match="its unit and its phrase"):
        RawStep(order=1, operation="seed_treatment", duration_min=10)
    with pytest.raises(ValidationError, match="without a duration"):
        RawStep(order=1, operation="seed_treatment", duration_unit="h", duration_raw="h")
    assert RawStep(order=1, operation="harvest", purpose_raw="to escape monsoon rains").purpose_raw


def test_bait_strength_carrier_and_word_ratio():
    bait = RawQuantity(target="bromodialone", formulation="0.25 w/w", ratio_part=1, ratio_rest=49, ratio_raw="(1:49)",
                       mix_conc_value=0.005, mix_conc_unit="%", mix_conc_raw="at 0.005%",
                       carrier_raw="popped corn/rice/dry fish")
    assert bait.mix_conc_value == 0.005
    straw = RawQuantity(target="chlorpyriphos", formulation="1.5% DP", value=25, unit="kg", basis="/ha",
                        raw="25 kg/ha", carrier_raw="chopped paddy straw")
    assert straw.carrier_raw == "chopped paddy straw"
    equal = RawQuantity(target="KCl", conc_value=1, conc_unit="%", conc_raw="1% KCl solution",
                        ratio_raw="in equal volume")
    assert equal.ratio_part is None and equal.ratio_raw == "in equal volume"     # the program reads the words
    with pytest.raises(ValidationError, match="ratio_part, ratio_rest and ratio_raw"):
        RawQuantity(target="x", ratio_part=1, ratio_raw="1 :")
    with pytest.raises(ValidationError, match="go together"):
        RawQuantity(target="x", mix_conc_value=0.005, mix_conc_raw="0.005%")


def test_a_control_measure_may_have_no_generic_target_in_v4_only():
    fact = {"subtype": "ControlMeasure", "summary_en": "s", "quote": "Trim field bunds", "control_class": "cultural",
            "steps": [{"order": 1, "operation": "bund_management", "method": "Trim field bunds"}]}
    assert FACT.validate_python(fact).targets == []
    assert version_problems(fact, "v4") == []
    assert any("needs a target" in p for p in version_problems(fact, "v3"))


def test_versions_keep_their_fields_and_flags():
    assert V4_FIELDS <= field_names("v4") and not V4_FIELDS & field_names("v3")
    fact = {"subtype": "SeedTreatment", "extraction_flags": ["operation_from_formulation"],
            "steps": [{"order": 1, "duration_raw": "overnight", "applies": [{"target": "x", "carrier_raw": "c"}]}]}
    v3 = version_problems(fact, "v3")
    assert any("duration_raw" in p for p in v3) and any("carrier_raw" in p for p in v3)
    assert any("not a flag of prompt v4" in p for p in version_problems(fact, "v4"))
    general = {"subtype": "ControlMeasure", "extraction_flags": ["general_practice"]}     # step 10 code sets it
    assert all(any("'general_practice' is not a flag" in p for p in version_problems(general, v))
               for v in ("v2", "v3", "v4"))
