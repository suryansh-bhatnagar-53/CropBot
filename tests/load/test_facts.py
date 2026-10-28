"""Offline tests for the step 13 fact loader (kg.load.facts): rows, flattening, refusals, conflict keys
and the reviewer conflicts. No database; the TNAU test is skipped without data/verified."""

import copy

import pytest

from kg.load import facts as lf
from kg.registry import read_entry
from kg.registry.model import Conflict
from kg.validate import VALIDATED_DIR

REGISTERED = read_entry("source:tnau_agriculture_2020")
ENTRY = REGISTERED.model_copy(update={"conflict": []})          # unit tests: no reviewer conflicts
SPAN ={"id": "span:x1", "source_id": "source:tnau_agriculture_2020", "pdf_page": 75, "printed_page": "63",
        "bbox": None, "section_path": "RICE > SEED", "quote": "Store the seeds for more than 15 months",
        "table_ref": None, "table_row": None, "table_col": None, "extraction_method": "native_text"}


def storage(rid="rec:aaaa", months=15, moisture=8.0, quote=None, **kw):
    f = {"id": rid, "subtype": "StorageRule", "fact_key": "fk:1", "summary_en": "Store seed", "status": "extracted",
         "crop_ids": ["crop:rice"], "regions": [{"id": "state:33", "origin": "source"}],
         "purpose_ids": ["purpose:seed"], "storage_months_min": months, "storage_months_min_inclusive": False,
         "max_moisture_pct": moisture, "max_moisture_pct_inclusive": False, "structure": "700 gauge polythene bag",
         "raw": {"storage_months_min": "more than %s months" % months, "max_moisture_pct": "less than %s %%" % moisture},
         "steps": [{"order": 1, "operation": "storage", "instruction_en": "Storage.", "applies": [], "conditions": []}],
         "evidence": [{**SPAN, "quote": quote or SPAN["quote"]}], **kw}
    return f


def inputs(*facts, varieties=()):
    validated = [{"unit_id": "unit:x:abc", "raw_index": i, "subtype": f["subtype"], "fact_id": f["id"],
                  "review_reasons": ["r1"], "fact": f} for i, f in enumerate(facts)]
    verified = {f["id"]: {"fact_id": f["id"], "status": f["status"], "verifier": "jev-test", "verifier_score": 0.9,
                          "claims": [{"key": "c_1", "claim": "Does it?", "control": False, "p_yes": 0.9},
                                     {"key": "x_1", "claim": "Control?", "control": True, "p_yes": 0.1}],
                          "notes": []} for f in facts}
    normalized = {f["id"]: {"purpose_origins": {p: ["section"] for p in f.get("purpose_ids") or []}} for f in facts}
    return {"validated": validated, "verified": verified, "normalized": normalized, "varieties": list(varieties)}


CONCEPTS = {"crop:rice", "state:33", "purpose:seed", "purpose:grain", "ai:carbendazim"}


def test_rows_flatten_maps_and_carry_verifier_and_review_fields():
    built = lf.build(ENTRY, inputs(storage()), CONCEPTS)
    (rec,) = built["recs"]
    p = rec["props"]
    assert p["raw_storage_months_min"] == "more than 15 months" and "raw" not in p
    assert p["review_reasons"] == ["r1"] and p["verifier_claims"] == ["Does it?"]          # controls left out
    assert p["verifier_claim_p_yes"] == [0.9] and p["excluded_region_ids"] == []
    assert not {"steps", "regions", "evidence", "status", "reviewed_by", "created_at"} & set(p)
    assert built["nodes"]["Step"]["step:aaaa:0"]["props"]["operation"] == "storage"
    edges = {rel: rows for (_, rel, _), rows in built["edges"].items()}
    assert edges["IN_REGION"][0]["props"] == {"origin": "source"}
    assert edges["FOR_PURPOSE"][0]["props"] == {"origin": ["section"]}                    # v1.3 item, built
    assert lf.counts(built)["edges"]["IN_SOURCE"] == 1


def test_variety_cells_become_one_json_string():
    v = {"id": "variety:co_51", "name": "CO 51", "name_en": "CO 51", "kind": "variety", "crop_id": "crop:rice",
         "review_status": "needs_review", "source": "s", "traits": ["Habit: erect"], "raw": {"release_year": "2013"},
         "release_year": 2013, "cells": {"duration": {"table_ref": "#/tables/9", "row": 4, "text": "105-110"}},
         "evidence": {**SPAN, "id": "span:v1", "table_ref": "#/tables/9", "table_row": 0, "table_col": 1}}
    built = lf.build(ENTRY, inputs(varieties=[v]), CONCEPTS)
    (row,) = built["varieties"]
    assert row["props"]["raw_release_year"] == "2013" and isinstance(row["props"]["cells_json"], str)
    assert "cells" not in row["props"] and "crop_id" not in row["props"]


@pytest.mark.parametrize("change, problem", [
    (lambda f: f.update(regions=[]), "not a valid fact"),                        # no IN_REGION (model refuses)
    (lambda f: f.update(evidence=[]), "not a valid fact"),                       # no SourceSpan
    (lambda f: f.update(status="approved"), "comes only from a reviewer"),
    (lambda f: f.update(purpose_ids=["purpose:fodder"]), "no such concept"),
])
def test_refusals(change, problem):
    f = storage()
    change(f)
    with pytest.raises(lf.LoadError) as e:
        lf.build(ENTRY, inputs(f), CONCEPTS)
    assert any(problem in p for p in e.value.problems)


def test_unanswered_claims_and_map_properties_are_refused():
    f = storage()
    data = inputs(f)
    data["verified"][f["id"]]["claims"][0]["p_yes"] = None
    with pytest.raises(lf.LoadError, match="unanswered claims"):
        lf.build(ENTRY, data, CONCEPTS)
    v = {"id": "variety:x", "name": "X", "kind": "variety", "review_status": "needs_review", "source": "s",
         "parentage": {"a": 1}, "evidence": {**SPAN, "id": "span:v2"}}
    with pytest.raises(lf.LoadError, match="not a Neo4j primitive"):
        lf.build(ENTRY, inputs(varieties=[v]), CONCEPTS)


def test_one_span_id_with_different_properties_is_refused():
    a, b = storage(), storage(rid="rec:bbbb", months=12, moisture=9.0)
    b["fact_key"] = "fk:2"
    b["evidence"] = [{**SPAN, "pdf_page": 74}]
    with pytest.raises(lf.LoadError, match="same id with different properties"):
        lf.build(ENTRY, inputs(a, b), CONCEPTS)


def test_conflict_key_ignores_values_and_sources_but_not_the_storage_window():
    a = storage()
    b = copy.deepcopy(a)
    b["max_moisture_pct"], b["evidence"][0]["section_path"] = 7.0, "elsewhere"
    assert lf.conflict_key(a) == lf.conflict_key(b) and lf.value_key(a) != lf.value_key(b)
    c = storage(months=12)
    assert lf.conflict_key(a) != lf.conflict_key(c)                             # another storage period
    raw_only = copy.deepcopy(a)
    raw_only["raw"]["max_moisture_pct"] = "below 8 %"
    assert lf.value_key(a) == lf.value_key(raw_only)                             # printed wording is not a value
    scoped = copy.deepcopy(a)
    scoped["scope_in_unmapped"] = ["at 10 per cent moisture content"]            # step 11's flag is not a value
    assert lf.value_key(a) == lf.value_key(scoped) and lf.conflict_key(a) == lf.conflict_key(scoped)
    other_method = copy.deepcopy(a)
    other_method["steps"][0]["method"] = "maintain"                              # different advice, not a contradiction
    assert lf.conflict_key(a) != lf.conflict_key(other_method)


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(type("R", (), {"data": lambda s, r=r: r})() for r in self.rows)

    def consume(self):
        counters = type("C", (), {"nodes_created": 0, "relationships_created": 0})()
        return type("S", (), {"counters": counters})()


class FakeTx:
    """Answers the revision lookup with one older node of the same fact_key; every MATCH matches."""
    def __init__(self, old):
        self.old, self.calls = old, []

    def run(self, query, **params):
        self.calls.append((query, params))
        if "o.fact_key IN $keys" in query:
            return FakeResult(self.old)
        if "RETURN count(*) AS n" in query:
            return FakeResult([{"n": len(params["rows"])}])
        return FakeResult([])


def test_a_changed_value_becomes_a_needs_review_revision():
    built = lf.build(ENTRY, inputs(storage()), CONCEPTS)
    tx = FakeTx([{"key": "fk:1", "id": "rec:old1"}])
    rep = lf.write(tx, ENTRY, built)
    assert rep["revisions"] == [{"src": "rec:aaaa", "dst": "rec:old1"}]
    (merge,) = [p for q, p in tx.calls if "MERGE (n:Recommendation" in q]
    assert merge["rows"][0]["status"] == "needs_review" and merge["human"] == ["approved", "rejected"]
    assert any("REVISION_OF" in q and "MERGE" in q for q, _ in tx.calls)
    # superseded_by is set only by a source that supersedes another (schema v1.5); this one doesn't
    assert not any("SET r.superseded_by" in q for q, _ in tx.calls)
    missing = [q for q, _ in tx.calls if "missing_in_latest_run = true" in q]
    assert missing and "DELETE" not in " ".join(q for q, _ in tx.calls)          # flagged, never deleted


def test_a_newer_season_supersedes_the_older_sources_facts():
    """Schema v1.5: a source with `supersedes` marks every fact of the older source; conflict detection skips
    superseded facts, so two seasons' limits never conflict."""
    newer = ENTRY.model_copy(update={"supersedes": "source:older_edition"})
    built = lf.build(ENTRY, inputs(storage()), CONCEPTS)
    tx = FakeTx([])
    lf.write(tx, newer, built)
    (sup,) = [(q, p) for q, p in tx.calls if "SET r.superseded_by" in q]
    assert sup[1] == {"old": "source:older_edition", "new": ENTRY.id}
    (detect,) = [q for q, _ in tx.calls if "CONFLICTS_WITH" in q and "detected" in q]
    assert "a.superseded_by IS NULL AND b.superseded_by IS NULL" in detect


def test_cautions_against_the_same_thing_in_other_words_do_not_conflict():
    base = {"id": "rec:c1", "subtype": "Caution", "fact_key": "fk:c", "summary_en": "s", "kind": "prohibition",
            "crop_ids": ["crop:rice"], "regions": [{"id": "state:33", "origin": "source"}],
            "concerns": ["ai_group:synthetic_pyrethroids"], "text_en": "Do not use synthetic pyrethroids.", "steps": []}
    other = {**base, "id": "rec:c2", "text_en": "Avoid spraying synthetic pyrethroids; they cause resurgence."}
    assert lf.conflict_key(base) == lf.conflict_key(other) and lf.value_key(base) == lf.value_key(other)


def test_conflicts_inside_a_load_are_found_once_per_pair():
    a, b = storage(), storage(rid="rec:bbbb", moisture=7.0)
    b["fact_key"], b["evidence"] = "fk:2", [{**SPAN, "id": "span:x2", "quote": "another quote"}]
    built = lf.build(ENTRY, inputs(a, b), CONCEPTS)
    assert [d["pair"] for d in built["detected_in_load"]] == [["rec:aaaa", "rec:bbbb"]]


def test_reviewer_conflicts_need_exactly_one_fact_per_side(monkeypatch):
    dry = storage(rid="rec:dddd", quote="Dry the seeds to 8-9 % moisture for long term storage.")
    dry.update(subtype="DryingSpec", fact_key="fk:d", target_moisture_pct_min=8.0, target_moisture_pct_max=9.0,
               raw={"target_moisture_pct_min": "8-9 %", "target_moisture_pct_max": "8-9 %"},
               storage_term_raw="long term storage", evidence=[{**SPAN, "id": "span:d", "pdf_page": 74,
                                                                "quote": "Dry the seeds to 8-9 % moisture for long term storage."}])
    for k in ("storage_months_min", "storage_months_min_inclusive", "max_moisture_pct", "max_moisture_pct_inclusive",
              "structure"):
        dry.pop(k)
    side = lambda subtype, page, quote: {"subtype": subtype, "pdf_page": page, "quote": quote}
    conflict = Conflict(a=side("DryingSpec", 74, "Dry the seeds to 8-9 % moisture for long term storage."),
                        b=side("StorageRule", 75, SPAN["quote"]), note="n", status="proposed")
    entry = ENTRY.model_copy(update={"conflict": [conflict]})
    built = lf.build(entry, inputs(storage(), dry), CONCEPTS)
    assert built["reviewer"] == [] and built["proposed"][0]["src"] == "rec:aaaa"             # proposed: not linked
    approved = entry.model_copy(update={"conflict": [conflict.model_copy(update={"status": "approved"})]})
    assert lf.build(approved, inputs(storage(), dry), CONCEPTS)["reviewer"][0]["dst"] == "rec:dddd"
    wrong = entry.model_copy(update={"conflict": [conflict.model_copy(update={"b": conflict.a})]})
    with pytest.raises(lf.LoadError, match="side b matches 0 facts"):
        lf.build(wrong, inputs(storage()), CONCEPTS)


@pytest.mark.skipif(not (VALIDATED_DIR / "tnau_agriculture_2020" / "facts.jsonl").exists(),
                    reason="needs data/validated and data/verified for the TNAU guide")
def test_tnau_load_builds_without_refusals():
    from kg.load.seed import read_seed
    built = lf.build(REGISTERED, lf.read_inputs(REGISTERED), {n.id for n in read_seed().nodes})
    c = lf.counts(built)
    n = len(lf.read_inputs(REGISTERED)["validated"])            # 61 with the v2 runs under schema v1.3
    assert c["nodes"]["Recommendation"] == n and c["nodes"]["Variety"] == 38
    assert c["edges"]["IN_REGION"] == n and c["edges"]["EVIDENCED_BY"] == n + 38
    assert built["detected_in_load"] == [] and built["proposed"] == []
    (p,) = built["reviewer"]                                      # approved 2026-10-20
    assert sorted(p["facts"]) == ["f5b06c9fd3f8#18", "f5b06c9fd3f8#24"]
