"""The one-time --reset-source on a real Neo4j database, never the main one.

  uv run python -m pytest tests/load/test_live_reset.py --neo4j-test-db cropbot-test

Skipped without --neo4j-test-db; the test empties that database, loads concepts/ and the TNAU facts, resets
the source, then shows that reviewed work blocks a reset.
"""

import pytest

from kg.load import facts as lf
from kg.registry import read_entry
from kg.validate import VALIDATED_DIR
from tests.conftest import reset_and_seed

ENTRY = read_entry("source:tnau_agriculture_2020")


def count(driver, name, query, **params):
    rows, _, _ = driver.execute_query(query, database_=name, **params)
    return rows[0]["n"]


@pytest.fixture
def loaded(neo4j_test_db):
    if not (VALIDATED_DIR / "tnau_agriculture_2020" / "facts.jsonl").exists():
        pytest.skip("needs data/validated and data/verified for the TNAU guide")
    driver, name = neo4j_test_db
    concepts = reset_and_seed(driver, name)                  # the test database only
    lf.load(driver, ENTRY, lf.build(ENTRY, lf.read_inputs(ENTRY), concepts), name)
    return driver, name


def reset(driver, name):
    with driver.session(database=name) as session:
        return session.execute_write(lf.reset_source, ENTRY.id)


def test_reset_removes_the_sources_facts_and_keeps_varieties_and_concepts(loaded):
    driver, name = loaded
    recs = count(driver, name, "MATCH (r:Recommendation) RETURN count(r) AS n")
    concepts = count(driver, name, "MATCH (c:Concept) RETURN count(c) AS n")
    assert recs > 0
    done = reset(driver, name)
    assert done["recommendations"] == recs and done["steps_clauses_conditions"] > 0 and done["spans"] > 0
    for label in ("Recommendation", "Step", "ThresholdClause", "Condition"):
        assert count(driver, name, "MATCH (n:%s) RETURN count(n) AS n" % label) == 0
    assert count(driver, name, "MATCH (c:Concept) RETURN count(c) AS n") == concepts            # varieties included
    assert count(driver, name, "MATCH (v:Variety)-[:EVIDENCED_BY]->(s:SourceSpan) RETURN count(s) AS n") == 38
    assert count(driver, name, "MATCH (s:Source {id: $id}) RETURN count(s) AS n", id=ENTRY.id) == 1
    assert reset(driver, name) == {"recommendations": 0, "steps_clauses_conditions": 0, "spans": 0}


@pytest.mark.parametrize("change", ["r.status = 'approved'", "r.status = 'rejected'", "r.reviewed_by = 'reviewer'"])
def test_reviewed_work_blocks_the_reset_and_nothing_is_deleted(loaded, change):
    driver, name = loaded
    driver.execute_query("MATCH (r:Recommendation) WITH r LIMIT 1 SET %s" % change, database_=name)
    before = lf.snapshot(driver, name)
    with pytest.raises(lf.LoadError, match="has reviewed work, nothing deleted"):
        reset(driver, name)
    assert lf.snapshot(driver, name) == before
