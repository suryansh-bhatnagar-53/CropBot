"""Facts that break a schema rule must fail validation, for that rule's reason."""

import copy

import pytest
from pydantic import ValidationError

from kg.schema import FACT, Condition

from .examples import BPH_THRESHOLD, DRYING_SEED_SHORT, NURSERY_DAP, STORAGE_LONG


def broken(base, change):
    data = copy.deepcopy(base)
    change(data)
    return data


def first_applies(d):
    return d["steps"][0]["applies"][0]


def drop(d, *keys):
    for k in keys:
        d.pop(k)


# name: (valid base fact, change that breaks it, text the error must contain)
CASES = {
    # required by the task
    "no region": (NURSERY_DAP, lambda d: d.update(regions=[]), "regions"),
    "region key missing": (NURSERY_DAP, lambda d: d.pop("regions"), "Field required"),
    "unknown unit": (NURSERY_DAP, lambda d: first_applies(d).update(unit="quintal"),
                     "Input should be 'kg'"),
    "number without raw (APPLIES)": (NURSERY_DAP, lambda d: first_applies(d).pop("raw"),
                                     "needs its raw source text"),
    "number without raw (subtype field)": (DRYING_SEED_SHORT,
                                           lambda d: d["raw"].pop("target_moisture_pct_max"),
                                           "needs its raw source text"),
    "number without raw (threshold clause)": (BPH_THRESHOLD, lambda d: d["clauses"][0].pop("raw"),
                                              "Field required"),
    # other schema rules
    "no source span": (NURSERY_DAP, lambda d: d.update(evidence=[]), "at least 1 item"),
    "no crop": (NURSERY_DAP, lambda d: d.update(crop_ids=[]), "at least 1 item"),
    "state slug instead of LGD code": (
        NURSERY_DAP, lambda d: d.update(regions=[{"id": "state:tn", "origin": "source"}]),
        "is not a region id"),
    "unknown region origin": (NURSERY_DAP, lambda d: d["regions"][0].update(origin="guess"),
                              "Input should be 'text'"),
    "unknown basis": (NURSERY_DAP, lambda d: first_applies(d).update(basis="per_acre"),
                      "Input should be 'per_ha'"),
    "per_cent_nursery without area": (NURSERY_DAP, lambda d: first_applies(d).pop("area_cents"),
                                      "per_cent_nursery and area_cents go together"),
    "value and range together": (NURSERY_DAP, lambda d: first_applies(d).update(min=30),
                                 "either value or min/max"),
    "no amount and no quantity_ref": (
        NURSERY_DAP, lambda d: drop(first_applies(d), "value", "raw", "unit", "basis", "area_cents"),
        "quantity_ref='previous'"),
    "unknown operation": (NURSERY_DAP, lambda d: d["steps"][0].update(operation="puddling"),
                          "Input should be 'sowing'"),
    "unknown anchor": (NURSERY_DAP, lambda d: d["steps"][0].update(anchor="DAS"),
                       "Input should be 'sowing'"),
    "calendar anchor without month": (NURSERY_DAP, lambda d: d["steps"][0].update(anchor="calendar"),
                                      "calendar anchor and month_start"),
    "offset without timing_raw": (
        NURSERY_DAP, lambda d: [d["steps"][0].pop("timing_raw"), d["steps"][0].update(offset_min=-1)],
        "timing needs timing_raw"),
    "alt_priority 3": (NURSERY_DAP, lambda d: d["steps"][0].update(alt_priority=3),
                       "Input should be 1 or 2"),
    "unknown status": (NURSERY_DAP, lambda d: d.update(status="draft"),
                       "Input should be 'extracted'"),
    "extra field": (NURSERY_DAP, lambda d: d.update(confidence=0.9), "Extra inputs"),
    "unknown subtype": (NURSERY_DAP, lambda d: d.update(subtype="FertilizerTip"),
                        "does not match any of the expected tags"),
    "conflict without needs_review": (STORAGE_LONG, lambda d: d.update(status="extracted"),
                                      "must be needs_review"),
    "months from short/long term only": (
        DRYING_SEED_SHORT,
        lambda d: [d.update(storage_months_max=9), d["raw"].update(storage_months_max="short term")],
        "storage_months must stay null"),
    "min above max": (DRYING_SEED_SHORT, lambda d: d.update(target_moisture_pct_min=14),
                      "is greater than"),
    "moisture above 100": (DRYING_SEED_SHORT, lambda d: d.update(target_moisture_pct_max=130),
                           "less than or equal to 100"),
}


@pytest.mark.parametrize("name", CASES)
def test_rejected(name):
    base, change, message = CASES[name]
    with pytest.raises(ValidationError, match=message):
        FACT.validate_python(broken(base, change))


GOOD_CONDITION = {"variable": "spider_count_per_hill", "op": "<", "value": 1,
                  "unit": "count", "any_of_group": 1, "raw": "in the absence of predatory spider"}

# name: (fields to change, None = remove; text the error must contain)
BAD_CONDITIONS = {
    "no raw": ({"raw": None}, "Field required"),
    "unknown variable": ({"variable": "spiders"}, "unknown condition variable"),
    "unit not the variable's unit": ({"unit": "pct"}, "takes unit count"),
    "between without value_max": ({"op": "between"}, "needs value and value_max"),
    "value_max without between": ({"value_max": 3}, "only used with `between`"),
    "in without a list": ({"op": "in"}, "needs a non-empty list"),
    "list without in": ({"value": [1, 2]}, "only `in` takes a list"),
    "between with value >= value_max": ({"op": "between", "value": 3, "value_max": 2},
                                        "value < value_max"),
    "text value for a number": ({"value": "one"}, "not a valid number value"),
    "group 0": ({"any_of_group": 0}, "greater than 0"),
    "rating compared with <": ({"variable": "soil_N_rating", "unit": None, "value": "low"},
                               "only takes ==, != or in"),
    "rating outside low/medium/high": ({"variable": "soil_N_rating", "unit": None, "op": "==",
                                        "value": "very low"}, "not a valid rating value"),
}


def test_good_condition_validates():
    Condition.model_validate(GOOD_CONDITION)


@pytest.mark.parametrize("name", BAD_CONDITIONS)
def test_condition_rejected(name):
    change, message = BAD_CONDITIONS[name]
    data = {k: v for k, v in {**GOOD_CONDITION, **change}.items() if v is not None}
    with pytest.raises(ValidationError, match=message):
        Condition.model_validate(data)


def test_condition_groups_must_run_without_gaps():
    data = copy.deepcopy(BPH_THRESHOLD)
    data["clauses"][0]["conditions"].append({**GOOD_CONDITION, "any_of_group": 3})
    with pytest.raises(ValidationError, match="without gaps"):
        FACT.validate_python(data)
