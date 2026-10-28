"""Step 11 on the normalised TNAU facts (gitignored); skipped when they are missing."""

import pytest

from kg.normalize import NORMALIZED_DIR
from kg.registry import read_entry
from kg.validate import run

ENTRY = read_entry("source:tnau_agriculture_2020")
pytestmark = pytest.mark.skipif(not (NORMALIZED_DIR / "tnau_agriculture_2020" / "facts.jsonl").exists(),
                                reason="needs data/normalized for the TNAU guide")


@pytest.fixture(scope="module")
def result():
    return run(ENTRY)


@pytest.fixture(scope="module")
def facts(result):
    return {(f["unit_id"].rsplit(":", 1)[1], f["raw_index"]): f for f in result["facts"]}


def test_approved_review_note_is_attached_and_values_are_unchanged(result, facts):
    fip = facts[("e63c6fbba0e4", 21)]
    assert fip["review_notes"] == ["suspected source typo: same product printed in g on p. 65"]
    assert "review note: suspected source typo: same product printed in g on p. 65" in fip["review_reasons"]
    a = next(a for s in fip["fact"]["steps"] for a in s["applies"] if a.get("formulation") == "80%WG")
    assert (a["min"], a["max"], a["unit"]) == (50, 62.5, "kg")                       # the value is never changed
    imid = ("inconsistent units for the same product in the source: g/ha on pp. 287–288, kg/ha on pp. 66, 67 "
            "and once on p. 288")
    assert facts[("e63c6fbba0e4", 35)]["review_notes"] == [imid]                     # BPH row, p. 66
    assert facts[("e63c6fbba0e4", 36)]["review_notes"] == [imid]                     # WBPH row, pp. 66-67


def test_no_approved_note_is_stale(result):                      # the WBPH row spans pp. 66-67 and matches both notes
    assert result["stale_notes"] == []


def test_nothing_is_approved_and_failures_mean_review(facts):
    for f in facts.values():
        assert f["status"] in ("extracted", "needs_review")
        if any(c["status"] == "fail" for c in f["checks"].values()):
            assert f["status"] == "needs_review"


def test_suspected_source_typos_fail_the_dose_check(facts):
    for key in (("e63c6fbba0e4", 21), ("e63c6fbba0e4", 35)):                  # Fipronil 80%WG kg, Imidacloprid 70% WG kg
        r = facts[key]["checks"]["value_ranges"]
        assert r["status"] == "fail" and "kg a.i./ha" in r["reason"]


def test_rice_seed_storage_ranges_keep_both_bounds(result, facts):
    """Schema v1.3: "12 - 13 %" and "8 - 9 %" (C2#22, #23) store min and max, so nothing is narrowed."""
    assert not [k for k, f in facts.items() if f["checks"]["range_narrowed"]["status"] == "fail"]
    for k, bounds in ((("f5b06c9fd3f8", 22), (12.0, 13.0)), (("f5b06c9fd3f8", 23), (8.0, 9.0))):
        f = facts[k]["fact"]
        assert (f["min_moisture_pct"], f["max_moisture_pct"]) == bounds


def test_no_lost_glyph_and_targets_as_printed(facts):
    assert all(f["checks"]["lost_glyph"]["status"] == "pass" for f in facts.values())
    failed = {k for k, f in facts.items() if f["checks"]["printed_text"]["status"] == "fail"}
    # prompt v4 copies methods, observations and maturity signs verbatim and flags "seed" target_from_heading;
    # under v3, 11 reworded methods, 2 observations and the 4 "Seed rate" facts failed too
    assert failed == {("f5b06c9fd3f8", i) for i in (9, 10, 11)} | {               # N, P, K from "NPK"
        ("e63c6fbba0e4", 52)}         # IPM Pseudomonas dip, split from a shared line: the name is before the quote
    for k in failed:
        assert facts[k]["status"] == "needs_review"


def test_every_applied_ingredient_fails_closed_while_unknown(facts):
    with_ai = [f for f in facts.values() if any(a["target_id"].startswith("ai:") for s in f["fact"]["steps"]
                                                 for a in s["applies"])]
    assert with_ai and all(f["checks"]["ingredients"]["status"] == "fail" for f in with_ai)


def test_nursery_alternatives_wait_for_approved_percentages(facts):
    r = facts[("b879265e483b", 19)]["checks"]["alternatives"]
    assert r["status"] == "skip" and r["applies"] and "no approved percentages" in r["reason"]
    assert any(x.startswith("alternatives:") for x in facts[("b879265e483b", 19)]["review_reasons"])


def test_scope_in_unmapped_flags_four_facts_with_the_exact_reason(facts):
    """2026-10-22 (prompt v4): the 4 validated facts whose unmapped phrase is scope. e63c#9 ("In BPH prone
    areas/seasons") is now an endemic_area condition, e63c#17 is held (tungro is only proposed), and f5b0#21
    (moisture) is held at step 10."""
    failed = {k: f["checks"]["scope_in_unmapped"]["phrases"] for k, f in facts.items()
              if f["checks"]["scope_in_unmapped"]["status"] == "fail"}
    assert failed == {("b879265e483b", 3): ["for hybrids"],
                      ("b879265e483b", 14): ["depending on the height of the seedlings"],
                      ("b879265e483b", 19): ["when the seedlings are to be pulled out in 20-25 days after sowing "
                                             "in less fertile nursery soils"],
                      ("e63c6fbba0e4", 56): ["submergence of recommended level during critical periods only"]}
    for k, phrases in failed.items():
        f = facts[k]
        assert f["status"] == "needs_review" and f["fact"]["scope_in_unmapped"] == phrases
        assert "scope in unmapped: served scope would be wider than printed" in f["review_reasons"]
    assert facts[("e63c6fbba0e4", 56)]["status_before"] == "extracted"
