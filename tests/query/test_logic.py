"""Offline tests for three-valued conditions and on_unknown policies (kg.query.logic)."""

import pytest

from kg.query import FarmContext
from kg.query.logic import FALSE, TRUE, UNKNOWN, combine, condition_state, policy, question

SPIDER_LT = {"variable": "spider_count_per_hill", "op": "<", "value": 1.0, "any_of_group": 1,
             "raw": "in the absence of predatory spider"}
RAIN = {"variable": "forecast_rain_mm_24h", "op": ">", "value": 10.0, "any_of_group": 1, "raw": "rain expected"}


def ctx(**kw):
    return FarmContext(crop="crop:rice", state="state:33", **kw)


def test_a_missing_value_is_unknown_never_a_default():
    assert condition_state(SPIDER_LT, ctx()) == UNKNOWN
    assert condition_state(SPIDER_LT, ctx(observations={"spider_count_per_hill": 0})) == TRUE
    assert condition_state(SPIDER_LT, ctx(observations={"spider_count_per_hill": 2})) == FALSE


@pytest.mark.parametrize("states, expected", [
    # one group (OR): TRUE OR UNKNOWN = TRUE; FALSE OR UNKNOWN = UNKNOWN
    (([0.0], [None]), TRUE),
    (([5.0], [None]), UNKNOWN),
    (([5.0], [5.0]), FALSE),
])
def test_or_within_a_group(states, expected):
    spider, pest = states
    conds = [SPIDER_LT, {"variable": "pest_count", "op": "<", "value": 1.0, "any_of_group": 1, "raw": "no pests"}]
    obs = {k: v[0] for k, v in (("spider_count_per_hill", spider), ("pest_count", pest)) if v[0] is not None}
    assert combine(conds, ctx(observations=obs))[0] == expected


def test_and_across_groups_false_wins_over_unknown():
    other = {**RAIN, "any_of_group": 2}
    c = ctx(observations={"spider_count_per_hill": 3})                 # group 1 FALSE, group 2 UNKNOWN
    assert combine([SPIDER_LT, other], c) == (FALSE, [])
    c = ctx(observations={"spider_count_per_hill": 0})                 # TRUE AND UNKNOWN = UNKNOWN
    assert combine([SPIDER_LT, other], c) == (UNKNOWN, ["forecast_rain_mm_24h"])
    assert combine([], ctx()) == (TRUE, [])


def test_policies_follow_the_registry():
    assert policy("spider_count_per_hill").value == "ask"
    assert policy("forecast_rain_mm_24h").value == "conservative"
    assert policy("storage_months").value == "ask_then_branch"
    assert policy("duration_group").value == "ask_then_branch"           # applicability, outside the registry
    assert question("spider_count_per_hill")["question"] == "How many spiders do you see per hill?"


def test_context_values():
    c = ctx(purpose="purpose:seed", soil={"N": "low", "pH": 8.2}, forecast={"rain_mm_24h": 18})
    assert c.value("purpose") == "seed" and c.value("soil_N_rating") == "low" and c.value("soil_pH") == 8.2
    assert c.value("forecast_rain_mm_24h") == 18 and c.value("storage_months") is None
    assert c.region_ids() == ["state:33", "country:in"]
