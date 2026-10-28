"""Step 15 on the TNAU data (gitignored step 9-12 outputs); skipped when they are missing."""

import pytest

from kg.eval import (ADJUDICATIONS, NORMALIZED_DIR, VERIFIED_DIR, calibration, disagreements, metrics, run,
                     stale_adjudications)
from kg.registry import read_entry

pytestmark = pytest.mark.skipif(not (VERIFIED_DIR / "tnau_agriculture_2020" / "facts.jsonl").exists()
                                or not (NORMALIZED_DIR / "tnau_agriculture_2020" / "facts.jsonl").exists(),
                                reason="needs the step 10 and 12 outputs for the TNAU guide")


@pytest.fixture(scope="module")
def res():
    return run(read_entry("source:tnau_agriculture_2020"))


def test_every_scored_gold_row_is_found(res):
    missed = [o["row"]["fact_id"] for o in res["outcome"] if o["scored"] and not o["match"] and not o["not_extracted"]]
    assert missed == []               # B23 (Pymetrozine, p. 66) since the step 8 rebuild put it back in the BPH row
    b23 = next(o for o in res["outcome"] if o["row"]["fact_id"] == "B23")
    assert res["atoms"][b23["match"]["ai"]]["fact"] == "e63c#35"
    unscored = {o["row"]["fact_id"] for o in res["outcome"] if not o["scored"]}
    assert unscored == {"A1", "A22", "A23", "A25", "A26", "A27", "A28", "B38b", "B39", "B40", "B41"}


def test_bph_scope_keeps_out_the_wbph_row(res):
    in_b = {a["fact"] for a in res["atoms"] if a["section"] == "B" and a["in_scope"]}
    assert "e63c#35" in in_b and "e63c#67" in in_b                # the BPH row and the BPH resurgence list
    assert "e63c#36" not in in_b and "e63c#69" not in in_b        # WBPH row and WBPH resurgence list


def test_adjudications_count_and_nothing_else_is_decided(res):
    m = metrics(res)["sections"]
    assert m["all"]["found"] == 90
    # 2026-10-21: all 127 disagreements adjudicated (prompt v3: agree 74-84, precision 109/110, 92-102).
    # 2026-10-22, prompt v4: 125 disagreements (agree 73-85, precision 92-105 before B3 and C3 were adjudicated
    # "both"); pipeline recall 84/90 once the general practices validate
    assert (m["all"]["recall_agree"]["lower"]["k"], m["all"]["recall_agree"]["upper"]["k"]) == (75, 85)
    assert m["all"]["recall_pipeline_strict"]["k"] == 84
    assert m["all"]["precision_found"]["k"] == 110 and m["all"]["precision_found"]["n"] == 110
    assert (m["all"]["precision_agree_lower"]["k"], m["all"]["precision_agree_upper"]["k"]) == (95, 105)
    if ADJUDICATIONS.exists():                   # 2026-10-21: the BPH resurgence list is in the book (p. 69)
        assert m["B"]["extras_confirmed"] == 16
        verdicts = sorted(e["verdict"] for e in res["judged_extras"].values())
        assert verdicts == ["extraction"] * 16      # 8e1d#1/m2 (E8) is verbatim under v4, so its verdict is stale
        stale = {(s["gold_id"], s["field"]) for s in stale_adjudications(res, disagreements(res))}
        assert stale == {("A30", "subtype"), ("B35", "condition"), ("B36", "subtype"), ("B37", "subtype"),
                         ("", "extra")}
    calib = calibration(res)
    assert calib["proposal"]["threshold"] is None and calib["proposal"]["message"] == "no threshold yet"
