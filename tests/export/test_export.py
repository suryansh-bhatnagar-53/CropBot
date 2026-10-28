"""kg.export offline: sorted, byte-identical JSONL; the DateTime round trip; refused values; the secrets check;
and the loader's refusals (home database, a database that is not empty, labels outside the schema)."""

import json

import pytest
from neo4j.time import DateTime

import kg.export as ex


class FakeDriver:
    """Answers the export's two graph queries from fixed rows, in a scrambled order."""
    def __init__(self, nodes, rels, home="neo4j", count=0, rel_count=0):
        self.nodes, self.rels, self.home, self.count, self.rel_count = nodes, rels, home, count, rel_count

    def execute_query(self, q, database_=None, **params):
        if q.startswith("MATCH (n) RETURN labels"):
            return [{"labels": l, "props": p} for l, p in self.nodes], None, None
        if q.startswith("MATCH (a)-[r]->(b)"):
            return [{"type": t, "start": a, "end": b, "props": p} for t, a, b, p in self.rels], None, None
        if q.startswith("SHOW DATABASES"):
            return [{"name": self.home}], None, None
        if q.startswith("MATCH (n) RETURN count"):
            return [{"n": self.count}], None, None
        if q.startswith("MATCH ()-[r]->() RETURN count"):
            return [{"n": self.rel_count}], None, None
        raise AssertionError(q)


WHEN = DateTime(2026, 10, 24, 5, 41, 23, 123456789)
NODES = [(["Recommendation", "DryingSpec"], {"id": "rec:b", "status": "approved", "created_at": WHEN, "x": [1.0, 2.0]}),
         (["Concept", "Crop"], {"id": "crop:rice", "name_en": "Rice"})]
RELS = [("FOR_CROP", "rec:b", "crop:rice", {}), ("EVIDENCED_BY", "rec:b", "span:a", {"origin": "text"})]


def test_the_export_is_sorted_and_byte_identical():
    a = ex.read_graph(FakeDriver(NODES, RELS))
    b = ex.read_graph(FakeDriver(list(reversed(NODES)), list(reversed(RELS))))
    assert ex.jsonl(a[0]) == ex.jsonl(b[0]) and ex.jsonl(a[1]) == ex.jsonl(b[1])
    nodes, rels = a
    assert [n["id"] for n in nodes] == ["crop:rice", "rec:b"]
    assert nodes[1]["labels"] == ["DryingSpec", "Recommendation"] and "id" not in nodes[1]["props"]
    assert [r["type"] for r in rels] == ["EVIDENCED_BY", "FOR_CROP"]
    line = ex.jsonl(nodes).decode("utf-8").splitlines()[1]
    assert line == ('{"id":"rec:b","labels":["DryingSpec","Recommendation"],"props":{"created_at":'
                    '{"$datetime":"2026-10-24T05:41:23.123456789"},"status":"approved","x":[1.0,2.0]}}')


def test_a_datetime_survives_the_round_trip_and_other_types_are_refused():
    utc = DateTime.from_iso_format("2026-10-24T05:41:23.123456789+00:00")
    assert ex.decode(json.loads(ex.dumps(ex.encode(utc, "x")))) == utc
    with pytest.raises(ex.ExportError, match="a dict value is not exported"):
        ex.encode({"a": 1}, "n.p")


def test_duplicate_ids_are_refused():
    with pytest.raises(ex.ExportError, match="duplicate node id crop:rice"):
        ex.read_graph(FakeDriver(NODES + [(["Crop"], {"id": "crop:rice"})], []))


def test_secrets_are_found_by_name_and_never_printed(monkeypatch):
    monkeypatch.setattr(ex, "dotenv_values", lambda path: {"NEO4J_PASSWORD": "hunter2-xyz", "NEO4J_USER": "neo4j"})
    monkeypatch.setattr(ex, "ROOT", ex.Path("."))
    monkeypatch.setattr(ex.Path, "exists", lambda self: True)
    found = ex.secrets_in({"nodes.jsonl": '{"note":"hunter2-xyz","db":"neo4j"}'})
    assert found == ["nodes.jsonl: the value of NEO4J_PASSWORD"] and "hunter2" not in " ".join(found)
    assert ex.secrets_in({"m": 'api_key = "abcdef123456"'}) == ["m: key-like string at offset 0"]
    assert ex.secrets_in({"m": '{"transcription_sha256":"%s"}' % ("a" * 64)}) == []     # hashes are no secret


def test_the_loader_refuses_the_home_database_and_a_database_that_is_not_empty():
    with pytest.raises(ex.ExportError, match="refusing 'neo4j'"):
        ex.load(FakeDriver([], []), "neo4j")
    with pytest.raises(ex.ExportError, match="refusing 'system'"):
        ex.load(FakeDriver([], []), "system")
    with pytest.raises(ex.ExportError, match="refusing 'cropbot-test': it is not empty"):
        ex.load(FakeDriver([], [], count=3), "cropbot-test")


def test_into_empty_home_is_explicit_and_only_for_a_completely_empty_home_database():
    with pytest.raises(ex.ExportError, match="it is the home database; .* --into-empty-home"):
        ex.load(FakeDriver([], [], home="neo4j"), "neo4j")                          # the default refuses
    with pytest.raises(ex.ExportError, match=r"not empty \(5 nodes, 0 relationships\); --into-empty-home loads only"):
        ex.load(FakeDriver([], [], home="neo4j", count=5), "neo4j", into_empty_home=True)
    with pytest.raises(ex.ExportError, match=r"not empty \(0 nodes, 2 relationships\)"):
        ex.load(FakeDriver([], [], home="neo4j", rel_count=2), "neo4j", into_empty_home=True)
    with pytest.raises(ex.ExportError, match="refusing 'system'"):
        ex.load(FakeDriver([], [], home="system"), "system", into_empty_home=True)


def test_the_loader_refuses_labels_outside_the_schema(tmp_path):
    nodes = [{"id": "x:1", "labels": ["Evil`) DETACH DELETE (m"], "props": {}}]
    files = {ex.NODES: ex.jsonl(nodes), ex.RELS: b""}
    for k, v in files.items():
        (tmp_path / k).write_bytes(v)
    (tmp_path / ex.MANIFEST).write_text(json.dumps({"snapshot": {}, "files": {k: {"sha256": ex.sha256(v)}
                                                                                 for k, v in files.items()}}))
    with pytest.raises(ex.ExportError, match="labels or types not allowed"):
        ex.load(FakeDriver([], []), "cropbot-test", tmp_path)
    (tmp_path / ex.NODES).write_bytes(b"changed\n")
    with pytest.raises(ex.ExportError, match="does not match its sha256"):
        ex.load(FakeDriver([], []), "cropbot-test", tmp_path)
