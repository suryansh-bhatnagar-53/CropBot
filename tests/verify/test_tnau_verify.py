"""Step 12 planning on the validated TNAU facts (gitignored); skipped when they are missing. Sends nothing."""

import pytest

import kg.verify as verify
from kg.registry import read_entry
from kg.validate import VALIDATED_DIR

ENTRY = read_entry("source:tnau_agriculture_2020")
pytestmark = pytest.mark.skipif(not (VALIDATED_DIR / "tnau_agriculture_2020" / "facts.jsonl").exists(),
                                reason="needs data/validated for the TNAU guide")
NO_CLAIM_FACTS = {("b879265e483b", 10, "Caution"), ("e63c6fbba0e4", 10, "Caution"),    # cautions naming no chemical
                  # prompt v4 rule 12a: "avoid ..." advice is a prohibition Caution (2026-10-22)
                  ("b879265e483b", 12, "Caution"), ("e63c6fbba0e4", 4, "Caution"), ("e63c6fbba0e4", 5, "Caution"),
                  ("e63c6fbba0e4", 33, "Caution")}
# (the saline-soil Spacing, f5b06c9fd3f8#5, has a claim since prompt v3 gives its 3 - 4 seedlings per hill)


@pytest.fixture(scope="module")
def p():
    return verify.plan(ENTRY, "jev-test")


def test_facts_without_a_code_built_claim(p):
    assert {(r["unit_id"].rsplit(":", 1)[1], r["raw_index"], r["subtype"]) for r in p["no_claim"]} == NO_CLAIM_FACTS


def test_they_are_marked_for_human_review_and_never_auto_verified(p, monkeypatch):
    monkeypatch.setattr(verify, "threshold", lambda: 0.0)                # even the lowest threshold
    monkeypatch.setattr(verify, "load_answers", lambda entry: {})
    marked = {(f["unit_id"].rsplit(":", 1)[1], f["raw_index"], f["subtype"]): f
              for f in verify.results(ENTRY, p, "jev-test")["facts"] if verify.NO_CLAIM in f["notes"]}
    assert set(marked) == NO_CLAIM_FACTS
    assert all(f["status"] != "auto_verified" and f["claims"] == [] for f in marked.values())
