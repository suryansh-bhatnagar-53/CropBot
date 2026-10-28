"""The revision rules against a real Neo4j database, never the main one.

  uv run python -m pytest tests/load/test_live_revisions.py --neo4j-test-db cropbot-test

Skipped without --neo4j-test-db. The database must already exist (CREATE DATABASE needs Enterprise; names
allow letters, digits, dots and dashes, not underscores), its name must contain "test", and it must not be
the server's home database; the test empties it first.
Steps: load the TNAU facts, approve one by hand, then load a copy of the input where that fact's value
changed and another fact was removed.
"""

import copy
import hashlib

import pytest

from kg.load import facts as lf
from kg.registry import read_entry
from kg.validate import VALIDATED_DIR
from tests.conftest import reset_and_seed

ENTRY = read_entry("source:tnau_agriculture_2020")
APPROVED = ("f5b06c9fd3f8", 23)          # StorageRule: 12-15 months at <= 9 %
REMOVED = ("e63c6fbba0e4", 29)           # ControlMeasure: phenthoate against case worm


@pytest.fixture(scope="module")
def db(neo4j_test_db):
    if not (VALIDATED_DIR / "tnau_agriculture_2020" / "facts.jsonl").exists():
        pytest.skip("needs data/validated and data/verified for the TNAU guide")
    driver, name = neo4j_test_db
    return driver, name, reset_and_seed(driver, name)          # the test database only


def short(rec):
    return rec["unit_id"].rsplit(":", 1)[1], rec["raw_index"]


def node(driver, name, rid):
    rows, _, _ = driver.execute_query("MATCH (r:Recommendation {id: $id}) RETURN properties(r) AS p", id=rid,
                                      database_=name)
    return rows[0]["p"] if rows else None


def modified(inputs):
    """A re-extraction: the approved fact's value changed (so a new id), one other fact gone."""
    out = copy.deepcopy(inputs)
    out["validated"] = [r for r in out["validated"] if short(r) != REMOVED]
    rec = next(r for r in out["validated"] if short(r) == APPROVED)
    old_id = rec["fact"]["id"]
    new_id = "rec:" + hashlib.sha256((old_id + "|max_moisture_pct=10").encode()).hexdigest()[:16]
    rec["fact"]["id"] = rec["fact_id"] = new_id
    rec["fact"]["max_moisture_pct"] = 10.0
    rec["fact"]["raw"] = {**rec["fact"]["raw"], "max_moisture_pct": "10 %"}
    out["verified"][new_id] = {**out["verified"][old_id], "fact_id": new_id}
    out["normalized"][new_id] = out["normalized"][old_id]
    return out, old_id, new_id


def test_approved_facts_survive_a_changed_value_and_removed_facts_are_flagged(db):
    driver, name, concepts = db
    inputs = lf.read_inputs(ENTRY)
    first = lf.load(driver, ENTRY, lf.build(ENTRY, inputs, concepts), name)
    assert first["write"]["created"]["nodes"] > 0 and first["write"]["revisions"] == []
    removed_id = next(r["fact"]["id"] for r in inputs["validated"] if short(r) == REMOVED)
    changed, old_id, new_id = modified(inputs)
    driver.execute_query("MATCH (r:Recommendation) WHERE r.id IN $ids SET r.status = 'approved', "
                         "r.reviewed_by = 'live test'", ids=[old_id, removed_id], database_=name)
    approved_before = node(driver, name, old_id)

    second = lf.load(driver, ENTRY, lf.build(ENTRY, changed, concepts), name)

    assert node(driver, name, old_id) == approved_before                        # untouched, still approved
    assert approved_before["status"] == "approved" and approved_before["max_moisture_pct"] == 9.0
    new = node(driver, name, new_id)
    assert new["status"] == "needs_review" and new["max_moisture_pct"] == 10.0
    rows, _, _ = driver.execute_query("MATCH (n {id: $new})-[r:REVISION_OF]->(o {id: $old}) RETURN count(r) AS n",
                                      new=new_id, old=old_id, database_=name)
    assert rows[0]["n"] == 1 and second["write"]["revisions"] == [{"src": new_id, "dst": old_id}]
    gone = node(driver, name, removed_id)
    assert gone is not None and gone["missing_in_latest_run"] is True              # flagged, never deleted
    rows, _, _ = driver.execute_query("MATCH (r {id: $id})-[e]->() RETURN count(e) AS n", id=removed_id,
                                      database_=name)
    assert rows[0]["n"] > 0                                                         # its edges are kept
    assert second["write"]["missing_in_latest_run"] == [removed_id]
    assert gone["status"] == "approved"                                             # approved and missing:
    assert [r["fact_id"] for r in lf.missing_approved(driver, name)] == [removed_id]  # served, and queued

    third = lf.load(driver, ENTRY, lf.build(ENTRY, changed, concepts), name)
    assert third["write"]["created"] == {"nodes": 0, "relationships": 0} and not third["changed"]
