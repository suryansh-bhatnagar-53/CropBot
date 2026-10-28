"""kg.query.ask, the agent's entry point: the answer of kg.query.answer, unchanged, for a template name and a
FarmContext or a plain dict; unknown templates and context fields are refused. Offline (a fake driver); the live
fixtures (tests/query/test_live_fixtures.py) go through ask too."""

import pytest

from kg.query import AskError, FarmContext, answer, ask
from tests.query.test_answer import GRAIN, FakeDriver

CONTEXT = {"crop": "crop:rice", "state": "state:33", "purpose": "purpose:grain"}


def test_ask_returns_exactly_what_answer_returns_for_a_dict_or_a_context():
    want = answer(FakeDriver([GRAIN]), "drying_target", FarmContext(**CONTEXT))
    assert ask("drying_target", CONTEXT, driver=FakeDriver([GRAIN])) == want
    assert ask("drying_target", FarmContext(**CONTEXT), driver=FakeDriver([GRAIN])) == want
    assert want["slots"][0]["facts"][0]["values"]["target_moisture_pct_max"] == 12.0


def test_an_unknown_template_is_refused_with_the_list():
    with pytest.raises(AskError, match="unknown template 'drying'; pick one of: drying_target, harvest_readiness"):
        ask("drying", CONTEXT, driver=FakeDriver())


def test_a_bad_farm_context_is_refused():
    with pytest.raises(AskError, match="bad farm context: zone: Extra inputs are not permitted"):
        ask("sowing_window", {**CONTEXT, "zone": "zone:uk_mid_hills"}, driver=FakeDriver())     # it is `zones`
    with pytest.raises(AskError, match="crop: Field required"):
        ask("sowing_window", {"state": "state:5"}, driver=FakeDriver())
