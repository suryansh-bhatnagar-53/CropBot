"""Schema v1.5 QualitySpec: one printed regulatory limit with its commodity form, grades, fixed parameter,
limit type and sub-limit link."""

import pytest
from pydantic import ValidationError

from kg.schema import FACT
from kg.schema.vocab import AuthorityTier, QualityParameter

from .examples import fact, span

SPAN = span("span:x", 6, "UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY > SCHEDULE OF SPECIFICATION", "q")
BASE = {"authority": "DFPD", "season_label": "KHARIF MARKETING SEASON 2026-2027", "marketing_season": "KMS",
        "season_start_year": 2026, "commodity_form": "paddy", "grades": ["grade_a", "common"],
        "grades_origin": "section", "grades_evidence": "UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY"}


def quality(**kw):
    return FACT.validate_python(fact("rec:x", "QualitySpec", "s", SPAN, **{**BASE, **kw}))


def test_max_min_absent_and_a_unitless_ratio():
    assert quality(parameter="moisture", parameter_raw="Moisture content", limit_type="max", limit_value=17,
                   unit="pct", raw={"limit_value": "17.0"}).limit_inclusive is True
    lb = quality(parameter="length_breadth_ratio", parameter_raw="length and breadth ratio (L: B)", limit_type="min",
                 limit_value=2.5, raw={"limit_value": "2.5"}, grades=["grade_a"], grades_origin="text",
                 grades_evidence=None)
    assert lb.unit is None and lb.grades == ["grade_a"]
    absent = quality(parameter="argemone_mexicana", parameter_raw="Argemone mexicana", limit_type="absent")
    assert absent.limit_value is None
    sub = quality(parameter="dhatura_seeds", parameter_raw="Dhatura", limit_type="max", limit_value=0.025,
                  unit="pct", raw={"limit_value": "0.025%"}, part_of="poisonous_seeds")
    assert sub.part_of == QualityParameter.POISONOUS_SEEDS


@pytest.mark.parametrize("kw, message", [
    ({"parameter": "moisture", "parameter_raw": "m", "limit_type": "max"}, "needs limit_value"),
    ({"parameter": "moulds", "parameter_raw": "moulds", "limit_type": "absent", "limit_value": 0,
      "raw": {"limit_value": "0"}}, "absent limit has no limit_value"),
    ({"parameter": "moisture", "parameter_raw": "m", "limit_type": "max", "limit_value": 17,
      "raw": {"limit_value": "17"}}, "is a percentage"),
    ({"parameter": "length_breadth_ratio", "parameter_raw": "L: B", "limit_type": "min", "limit_value": 2.5,
      "unit": "pct", "raw": {"limit_value": "2.5"}}, "has no unit"),
    ({"parameter": "moisture", "parameter_raw": "m", "limit_type": "max", "limit_value": 17, "unit": "pct",
      "raw": {"limit_value": "17"}, "part_of": "moisture"}, "part of itself"),
    ({"parameter": "dust", "parameter_raw": "dust", "limit_type": "absent"}, "parameter"),
    ({"parameter": "moisture", "parameter_raw": "m", "limit_type": "max", "limit_value": 17, "unit": "pct",
      "raw": {"limit_value": "17"}, "grades": []}, "grades"),
    ({"parameter": "moisture", "parameter_raw": "m", "limit_type": "max", "limit_value": 17, "unit": "pct",
      "raw": {"limit_value": "17"}, "grades_evidence": None}, "need the heading as evidence"),
])
def test_rejected(kw, message):
    with pytest.raises(ValidationError, match=message):
        quality(**kw)


def test_the_regulatory_tier_ranks_first():
    assert AuthorityTier.REGULATORY == 0 < AuthorityTier.STATE_POP
