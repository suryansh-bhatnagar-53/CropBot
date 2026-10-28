"""kg.export round trip on the live test database: seed and load facts, export to a temporary folder, empty the
database, rebuild it from the JSONL alone, and get the same snapshot hash (created_at included).

  uv run python -m pytest tests/export/test_live_export.py --neo4j-test-db cropbot-test
"""

import pytest

import kg.export as ex
from kg.load import facts as lf
from kg.registry import read_entry
from kg.validate import VALIDATED_DIR
from tests.conftest import reset_and_seed


def test_export_empty_load_gives_the_same_snapshot(neo4j_test_db, tmp_path):
    driver, name = neo4j_test_db
    concepts = reset_and_seed(driver, name)
    for source in ("source:dfpd_uniform_spec_kms_2026_27", "source:gbpuat_kharif_advisory_2020"):
        if not (VALIDATED_DIR / source.split(":", 1)[1] / "facts.jsonl").exists():
            pytest.skip("needs data/validated and data/verified for %s" % source)
        entry = read_entry(source)
        lf.load(driver, entry, lf.build(entry, lf.read_inputs(entry), concepts), name)
    before = lf.snapshot(driver, name)
    manifest = ex.write(driver, name, tmp_path)
    assert manifest["snapshot"] == before and manifest["counts"]["nodes"] == before["nodes"]
    again = ex.write(driver, name, tmp_path / "again")                                # byte-identical re-export
    assert all((tmp_path / f).read_bytes() == (tmp_path / "again" / f).read_bytes() for f in (ex.NODES, ex.RELS))
    with pytest.raises(ex.ExportError, match="not empty"):
        ex.load(driver, name, tmp_path)
    driver.execute_query("MATCH (n) DETACH DELETE n", database_=name)
    loaded = ex.load(driver, name, tmp_path)
    assert loaded["created"] == {"nodes": before["nodes"], "relationships": before["relationships"]}
    assert loaded["snapshot"] == before
    assert ex.check(driver, name, tmp_path) == []
    assert again["facts_by_source_and_status"] == ex.facts_by_status(driver, name)


def test_into_empty_home_on_a_simulated_single_database_server(neo4j_test_db, tmp_path, monkeypatch):
    """cropbot-test plays the home database (as on Community or AuraDB Free): refused by default, refused
    with --into-empty-home while anything is in it, loaded with it once it is completely empty."""
    driver, name = neo4j_test_db
    concepts = reset_and_seed(driver, name)
    entry = read_entry("source:gbpuat_kharif_advisory_2020")
    if not (VALIDATED_DIR / "gbpuat_kharif_advisory_2020" / "facts.jsonl").exists():
        pytest.skip("needs data/validated and data/verified for GBPUAT")
    lf.load(driver, entry, lf.build(entry, lf.read_inputs(entry), concepts), name)
    before = lf.snapshot(driver, name)
    ex.write(driver, name, tmp_path)
    monkeypatch.setattr(ex, "home_databases", lambda d: {name})
    driver.execute_query("MATCH (n) DETACH DELETE n", database_=name)
    with pytest.raises(ex.ExportError, match="it is the home database"):
        ex.load(driver, name, tmp_path)
    driver.execute_query("CREATE (:Crop {id: 'crop:leftover'})", database_=name)
    with pytest.raises(ex.ExportError, match=r"not empty \(1 nodes, 0 relationships\)"):
        ex.load(driver, name, tmp_path, into_empty_home=True)
    driver.execute_query("MATCH (n) DETACH DELETE n", database_=name)
    loaded = ex.load(driver, name, tmp_path, into_empty_home=True)
    assert loaded["home"] is True and loaded["snapshot"] == before
