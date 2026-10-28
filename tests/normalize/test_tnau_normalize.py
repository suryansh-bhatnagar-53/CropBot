"""Normalisation of the four hand-run TNAU units. Needs the step 9 v2 runs and the units/tables
(gitignored); skipped when they are missing."""

import pytest

from kg.extract import EXTRACTED_DIR
from kg.normalize import run
from kg.registry import read_entry
from kg.schema import FACT

ENTRY = read_entry("source:tnau_agriculture_2020")
RUNS = EXTRACTED_DIR / "tnau_agriculture_2020" / "v2"
UNITS = {"8e1d1b38b483", "b879265e483b", "e63c6fbba0e4", "f5b06c9fd3f8"}
pytestmark = pytest.mark.skipif(not all((RUNS / ("%s.json" % u)).exists() for u in UNITS),
                                reason="needs the v2 hand-runs in data/extracted")


@pytest.fixture(scope="module")
def result():
    return run(ENTRY)


def fact(result, unit, index):
    return next(x for x in result["facts"] if x["unit_id"].endswith(unit) and x["raw_index"] == index)


def test_every_fact_is_validated_or_held_with_reasons_and_none_is_approved(result):
    # prompt v4 (2026-10-22): 124 facts. Under v3 it was 123, after the step 8 rebuild removed e63c's WBPH
    # Pymetrozine fact; v4 adds e63c#71, split off e63c#33 when the "avoid" advice became a Caution.
    # 103 validated / 21 held, then 113 / 11 with disease:tungro approved and general practices allowed
    assert (len(result["facts"]), len(result["held"])) == (113, 11)
    assert all(h["reasons"] for h in result["held"])
    for x in result["facts"]:
        assert x["status"] in ("extracted", "needs_review")
        FACT.validate_python(x["fact"])


def test_inherited_nursery_dap(result):
    a = fact(result, "b879265e483b", 20)["fact"]["steps"][0]["applies"][0]
    assert (a["target_id"], a["value"], a["basis"], a["area_cents"], a["inherited"]) == (
        "fertilizer:dap", 2, "per_cent_nursery", 20, True)


def test_seed_npk_by_convention_and_section_purpose(result):
    x = fact(result, "f5b06c9fd3f8", 11)
    assert [(a["target_id"], a["value"]) for a in x["fact"]["steps"][0]["applies"]] == [
        ("nutrient:n", 150), ("nutrient:p2o5", 50), ("nutrient:k2o", 80)]
    assert x["status"] == "needs_review" and x["purpose_origins"] == {"purpose:seed": ["section"]}
    assert fact(result, "f5b06c9fd3f8", 24)["purpose_origins"] == {"purpose:seed": ["text", "section"]}


def test_general_practices_validate_and_operations_are_still_held(result):
    general = {"%s#%d" % (x["unit_id"][-12:-8], x["raw_index"]) for x in result["facts"]
               if "general_practice" in x["fact"]["extraction_flags"]}
    assert general == {"b879#16", "b879#17", "e63c#0", "e63c#1", "e63c#2", "e63c#3", "e63c#7", "e63c#52", "e63c#60"}
    assert all(x["status"] == "needs_review" for x in result["facts"]
               if "general_practice" in x["fact"]["extraction_flags"])
    reasons = [r for h in result["held"] for r in h["reasons"]]
    assert not any("target" in r and "printed" in r for r in reasons)
    assert any("has no operation" in r for r in reasons)
