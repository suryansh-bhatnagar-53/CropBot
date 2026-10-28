"""Schema v1.4 additions to the models: repeat_offsets for an option list applied at stated times,
step durations and purpose, week offsets, the bait strength and carrier on APPLIES, and the
concept-valued endemic_area condition."""

import pytest
from pydantic import ValidationError

from kg.schema.core import Applies, Condition, Step, ThresholdClause
from kg.schema.vocab import CONDITION_VARIABLES, FORMULATION_OPERATION, FORMULATION_OVERRIDES, OnUnknown

GLH = dict(order=1, alt_group=1, alt_option=1, operation="spraying", instruction_en="Spray.", anchor="transplanting",
           timing_raw="15 and 30 days after transplanting", repeat_raw="twice")


def test_an_option_list_at_stated_times_keeps_one_step():
    """e63c#37 (p. 67): 'Spray any one of the following insecticides twice, 15 and 30 days after transplanting'."""
    s = Step(**GLH, offset_min=15, offset_max=15, repeat_offsets=[15, 30], repeat_count=2)
    assert s.repeat_offsets == [15, 30] and s.repeat_count == 2


@pytest.mark.parametrize("kw, message", [
    (dict(offset_min=15, offset_max=15, repeat_offsets=[15], repeat_count=1), "at least two"),
    (dict(offset_min=15, offset_max=15, repeat_offsets=[30, 15], repeat_count=2), "increasing"),
    (dict(offset_min=15, offset_max=15, repeat_offsets=[15, 30], repeat_count=3), "repeat_count equals"),
    (dict(offset_min=30, offset_max=30, repeat_offsets=[15, 30], repeat_count=2), "hold the first time"),
    (dict(offset_min=15, offset_max=15, repeat_offsets=[15, 30], repeat_count=2, repeat_interval=15,
          repeat_interval_unit="days"), "no interval"),
])
def test_bad_repeat_offsets(kw, message):
    with pytest.raises(ValidationError, match=message):
        Step(**GLH, **kw)


def test_durations_and_purpose():
    soak = Step(order=1, operation="seed_treatment", instruction_en="Soak.", duration_min=12, duration_max=16,
                duration_unit="hours", duration_raw="for 12 - 16 h")
    assert (soak.duration_min, soak.duration_max, soak.duration_unit) == (12, 16, "hours")
    night = Step(order=1, operation="seed_treatment", instruction_en="Soak.", duration_raw="overnight")
    assert night.duration_min is None and night.duration_raw == "overnight"
    shade = Step(order=2, operation="drying", instruction_en="Dry.", duration_min=30, duration_max=30,
                 duration_unit="minutes", duration_raw="for 30 minutes")
    assert shade.duration_unit == "minutes"
    salt = Step(order=1, operation="seed_treatment", instruction_en="Grade.",
                purpose_raw="adapting specific gravity grading")
    assert salt.purpose_raw == "adapting specific gravity grading"
    for bad, message in (({"duration_min": 12, "duration_raw": "12 h"}, "duration_unit"),
                         ({"duration_unit": "hours", "duration_raw": "h"}, "without a duration"),
                         ({"duration_min": 16, "duration_max": 12, "duration_unit": "hours",
                           "duration_raw": "16-12 h"}, "greater than"),
                         ({"duration_min": 2, "duration_unit": "weeks", "duration_raw": "2 weeks"}, "duration_unit")):
        with pytest.raises(ValidationError, match=message):
            Step(order=1, operation="seed_treatment", instruction_en="Soak.", **bad)


def test_a_week_is_one_week_not_seven_days():
    s = Step(order=1, operation="spraying", instruction_en="Spray.", anchor="harvest", offset_min=-1, offset_max=-1,
             offset_unit="weeks", timing_raw="a week before harvest")
    assert (s.offset_min, s.offset_unit) == (-1, "weeks")


def test_bait_strength_and_carrier():
    """e63c#45 (p. 68) 'bromodialone 0.25 w/w (1:49) at 0.005%'; e63c#43 'chopped paddy straw treated with …'."""
    bait = Applies(target_id="ai:bromadiolone", ratio_part=1, ratio_whole=50, ratio_raw="(1:49)", mix_conc_value=0.005,
                   mix_conc_unit="pct", mix_conc_raw="at 0.005%", carrier_raw="popped corn/rice/dry fish")
    assert bait.mix_conc_value == 0.005 and bait.carrier_raw == "popped corn/rice/dry fish"
    straw = Applies(target_id="ai:chlorpyrifos", value=25, unit="kg", basis="per_ha", formulation="1.5% DP",
                    raw="25 kg/ha", carrier_raw="chopped paddy straw")
    assert straw.carrier_raw == "chopped paddy straw"
    assert Applies(target_id="ai:x", mix_conc_value=0.005, mix_conc_unit="pct", mix_conc_raw="0.005%").value is None
    with pytest.raises(ValidationError, match="go together"):
        Applies(target_id="ai:x", value=1, unit="kg", basis="per_ha", raw="1 kg", mix_conc_value=0.005)


def test_endemic_area_is_a_concept_valued_condition():
    """e63c#17 (p. 64): '2/hill in tungro endemic area' sits on its clause."""
    assert CONDITION_VARIABLES["endemic_area"].on_unknown is OnUnknown.ASK_THEN_BRANCH
    c = Condition(variable="endemic_area", op="==", value="disease:tungro", any_of_group=1,
                  raw="in tungro endemic area")
    clause = ThresholdClause(observation="green leafhopper", value=2, unit="count", sampling_unit="per_hill",
                             raw="2/hill", conditions=[c])
    assert clause.conditions[0].value == "disease:tungro"
    assert Condition(variable="endemic_area", op="==", value="pest:brown_planthopper", any_of_group=1,
                     raw="In BPH prone areas/seasons").value == "pest:brown_planthopper"
    for bad in ({"value": "tungro"}, {"value": "crop:rice"}, {"op": "<", "value": "disease:tungro"}):
        with pytest.raises(ValidationError):
            Condition(**{"variable": "endemic_area", "op": "==", "any_of_group": 1, "raw": "r", **bad})


def test_formulation_table():
    assert FORMULATION_OPERATION["DP"] == "dusting" and FORMULATION_OPERATION["CG"] == "application"
    assert FORMULATION_OPERATION["SG"] == FORMULATION_OPERATION["SP"] == "spraying"
    assert FORMULATION_OVERRIDES == {"D", "DP", "G", "GR", "CG"}          # only these override a printed "spray"
