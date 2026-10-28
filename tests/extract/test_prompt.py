"""Offline tests for the prompts, rendering, caching, ingest and compare (kg.extract)."""

import json
import re

import pytest

import kg.extract as ex
from kg.extract.versions import LATEST, field_names
from kg.registry import read_entry

ENTRY = read_entry("source:tnau_agriculture_2020")
UNIT = {
    "id": "unit:tnau_agriculture_2020:abc123", "source_id": ENTRY.id, "kind": "leaf",
    "chapter": {"number": "1", "title": "RICE", "status": "approved"},
    "section_path": "RICE > CROP PROTECTION > A) Pest management > ii) Main field",
    "items": [
        {"ref": "#/texts/1", "kind": "subheading", "text": "Nutrient management", "pdf_page": 30,
         "subheading": "Nutrient management"},
        {"ref": "#/texts/2", "kind": "text", "text": "Apply 40 kg of DAP before the last puddling.",
         "pdf_page": 30, "printed_page": "18", "subheading": "Nutrient management"},
        {"ref": "#/texts/3", "kind": "text", "text": "DAP is a good source of P. It is cheap.",
         "pdf_page": 30, "printed_page": "18", "subheading": "Nutrient management"},
        {"ref": "#/tables/53", "kind": "table", "text": None, "pdf_page": 63, "printed_page": "51"},
        {"ref": "#/tables/54", "kind": "table", "text": None, "pdf_page": 64, "printed_page": "52"},
    ],
    "pdf_pages": [30, 64], "regions": [{"id": "state:33", "origin": "source"}],
    "default_scope": [r.label() for r in ENTRY.default_scope if "per_ha" in r.rule],
}
ETL = {"table_refs": ["#/tables/53", "#/tables/54", "#/tables/55"], "pdf_pages": [63, 64, 65],
       "header": ["Pest", "ETL"],
       "rows": [[{"text": "Stem borer", "part_ref": "#/tables/53", "row": 1},
                 {"text": "10% dead hearts", "part_ref": "#/tables/53", "row": 1}],
                [{"text": "Brown planthopper", "part_ref": "#/tables/54", "row": 0},
                 {"text": "1 hopper/ tiller", "part_ref": "#/tables/54", "row": 0,
                  "continued_from": [{"part_ref": "#/tables/55", "row": 0, "col": 1, "text": "x"}]}]]}
TABLES = {ref: ETL for ref in ETL["table_refs"]}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "EXTRACTED_DIR", tmp_path)
    monkeypatch.setattr(ex, "load_tables", lambda entry: TABLES)
    return tmp_path


@pytest.mark.parametrize("version", ["v1", "v2", "v3", "v4", "v5", "v6"])
def test_prompt_field_reference_matches_the_raw_model(version):
    text, _ = ex.prompt_template(version)
    section = text.split("## Field reference", 1)[1].split("\n## ", 1)[0]
    listed = set(re.findall(r"`([a-z_0-9]+)`", section))
    assert listed == field_names(version), (sorted(field_names(version) - listed),
                                            sorted(listed - field_names(version)))


def test_v2_drops_instruction_en_and_adds_flags():
    assert "instruction_en" in field_names("v1") and "instruction_en" not in field_names("v2")
    assert "extraction_flags" in field_names("v2") and "extraction_flags" not in field_names("v1")
    assert {"facts", "not_extracted", "reason"} <= field_names("v2")


@pytest.mark.parametrize("version", ["v1", "v2", "v3", "v4", "v5", "v6"])
def test_prompt_has_each_slot_once_and_vocabularies_come_from_code(version):
    text, _ = ex.prompt_template(version)
    assert all(text.count(s) == 1 for s in ex.SLOTS)
    vocab = ex.render_vocabularies(version)
    assert "last_puddling" in vocab and "spider_count_per_hill (count, number)" in vocab
    # schema v1.5's QualitySpec lists appear from v5 on, v1.6's window_for from v6; earlier prompts render as before
    assert ("- limit_type: max, min, absent" in vocab) == (version in ("v5", "v6"))
    assert ("damaged_discoloured_sprouted_weevilled" in vocab) == (version in ("v5", "v6"))
    assert ("- window_for: nursery_sowing, direct_seeding, transplanting, sowing" in vocab) == (version == "v6")


def test_tnau_pins_v4_so_its_runs_are_read():
    from kg.extract.versions import source_version
    assert source_version(ENTRY) == "v4" and LATEST == "v6"


def test_render_unit_and_segments():
    text, segments = ex.render_unit(ENTRY, UNIT, TABLES)
    assert "[p.30] ## Nutrient management" in text
    assert "[p.63-65] TABLE #/tables/53 + #/tables/54 + #/tables/55" in text and text.count("TABLE") == 1
    assert "[#/tables/54 row 0 + #/tables/55 row 0] Brown planthopper | 1 hopper/ tiller" in text
    row = next(s for s in segments if s["ref"] == "#/tables/54 row 0 + #/tables/55 row 0")
    assert (row["kind"], row["pdf_page"], row["printed_page"]) == ("row", 64, "52")
    assert row["pdf_pages"] == [64, 65] and row["printed_pages"] == ["52", "53"]      # every piece's page
    assert [s["kind"] for s in segments] == ["subheading", "text", "text", "header", "row", "row"]


def test_missing_table_fails_loudly():
    with pytest.raises(ex.ExtractError, match="run kg.tables first"):
        ex.render_unit(ENTRY, UNIT, {})


def test_default_scope_rule_is_shown_with_its_quote():
    scope = ex.render_default_scope(ENTRY, UNIT)
    assert scope.startswith("- RULE: dose basis = per_ha") and "QUOTE (PDF p. 63)" in scope
    assert ex.render_default_scope(ENTRY, {**UNIT, "default_scope": []}) == "none"


def test_cache_key_depends_on_unit_text_model_and_prompt_version():
    assert ex.build(ENTRY, UNIT, "model-a", TABLES)["version"] == LATEST
    a = ex.build(ENTRY, UNIT, "model-a", TABLES, version="v2")
    assert a["cache_key"] == ex.build(ENTRY, UNIT, "model-a", TABLES, version="v2")["cache_key"]
    assert a["cache_key"] != ex.build(ENTRY, UNIT, "model-b", TABLES, version="v2")["cache_key"]
    assert a["cache_key"] != ex.build(ENTRY, UNIT, "model-a", TABLES, version="v1")["cache_key"]
    assert a["cache_key"] != ex.build(ENTRY, UNIT, "model-a", TABLES, version="v3")["cache_key"]
    changed = {**UNIT, "items": UNIT["items"][:2]}
    assert a["cache_key"] != ex.build(ENTRY, changed, "model-a", TABLES, version="v2")["cache_key"]
    assert "{{" not in a["prompt"] and "Apply 40 kg of DAP" in a["prompt"]


STEP = {"order": 1, "operation": "fertilizer_application", "anchor": "last_puddling",
        "timing_raw": "before the last puddling",
        "applies": [{"target": "DAP", "value": 40, "unit": "kg", "basis": "per 20 cents",
                     "basis_inferred": True, "raw": "40 kg of DAP"}]}
FACT = {"subtype": "NutrientDose", "dose_basis": "blanket", "summary_en": "DAP before last puddling",
        "quote": "Apply 40 kg of DAP before the last puddling."}
V1_GOOD = {**FACT, "steps": [{**STEP, "instruction_en": "Apply DAP."}]}
V2_GOOD = {**FACT, "steps": [STEP]}
ETL_FACT = {"subtype": "PestThreshold", "pests": ["Stem borer"], "summary_en": "Stem borer ETL",
            "quote": "Stem borer | 10% dead hearts", "table_ref": "#/tables/53", "table_row": 1,
            "clauses": [{"observation": "dead hearts", "value": 10, "unit": "%", "raw": "10% dead hearts"}]}
BPH_FACT = {**ETL_FACT, "pests": ["Brown planthopper"], "quote": "1 hopper/ tiller", "table_ref": "#/tables/54",
            "table_row": 0, "table_col": 1,
            "clauses": [{"observation": "hoppers", "value": 1, "sampling_unit": "/ tiller", "raw": "1 hopper/ tiller"}]}
SKIP = {"quote": "DAP is a good source of P. It is cheap.", "reason": "statement; advises nothing"}


def v2(facts, skipped=(SKIP,)):
    return json.dumps({"facts": list(facts), "not_extracted": list(skipped)})


def test_v1_answers_still_check_as_v1(store):
    bad_quote = {**V1_GOOD, "quote": "Apply 40 kg DAP before the last puddling."}
    bad_parse = {**V1_GOOD, "dose_basis": "per_ha"}
    answer = json.dumps([V1_GOOD, bad_quote, bad_parse])
    path, rec = ex.ingest(ENTRY, UNIT, "model-a", answer, version="v1")
    s = rec["summary"]
    assert path.parent.name == "v1" and rec["coverage"] is None
    assert not rec["ok"] and [f["index"] for f in s["quote_failures"]] == [1]
    assert [f["index"] for f in s["parse_failures"]] == [2]
    assert s["by_subheading"] == {"Nutrient management": 2, "(none)": 1}   # an unfound quote has no place
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["answer"] == answer and stored["facts"][1]["answer"]["quote"] == bad_quote["quote"]
    with pytest.raises(ex.ExtractError, match="already holds an answer"):
        ex.ingest(ENTRY, UNIT, "model-a", answer, version="v1")
    _, rec = ex.ingest(ENTRY, UNIT, "model-a", json.dumps([V2_GOOD]), force=True, version="v1")
    assert rec["summary"]["parse_failures"][0]["errors"] == ["steps.0.instruction_en: required by prompt v1"]


def test_v2_answer_with_every_line_accounted_for(store):
    path, rec = ex.ingest(ENTRY, UNIT, "model-a", v2([V2_GOOD, ETL_FACT, BPH_FACT]), version="v2")
    assert rec["ok"] and path.parent.name == "v2", rec["summary"]
    assert rec["coverage"] == {"uncovered": [], "sentences_outside_quotes": []}
    assert rec["summary"]["not_extracted"] == [{"index": 0, "quote": SKIP["quote"], "reason": SKIP["reason"], "ok": True}]


def test_v2_uncovered_lines_and_partly_quoted_lines(store):
    part = {"quote": "It is cheap.", "reason": "statement"}
    _, rec = ex.ingest(ENTRY, UNIT, "model-a", v2([V2_GOOD, ETL_FACT], [part]), version="v2")
    cov = rec["coverage"]
    assert not rec["ok"] and [u["ref"] for u in cov["uncovered"]] == ["#/tables/54 row 0 + #/tables/55 row 0"]
    assert cov["sentences_outside_quotes"] == [{"ref": "#/texts/3", "sentence": "DAP is a good source of P."}]


def test_v2_rejects_instruction_en_unknown_flags_and_the_v1_envelope(store):
    with_text = {**V2_GOOD, "steps": [{**STEP, "instruction_en": "Apply DAP."}]}
    _, rec = ex.ingest(ENTRY, UNIT, "model-a", v2([with_text, ETL_FACT, BPH_FACT]), version="v2")
    assert rec["summary"]["parse_failures"][0]["errors"] == ["steps.0.instruction_en: not part of prompt v2"]
    flagged = {**V2_GOOD, "extraction_flags": ["guessed"]}
    _, rec = ex.ingest(ENTRY, UNIT, "model-a", v2([flagged, ETL_FACT, BPH_FACT]), force=True, version="v2")
    assert "extraction_flags.0" in rec["summary"]["parse_failures"][0]["errors"][0]
    _, rec = ex.ingest(ENTRY, UNIT, "model-a", json.dumps([V2_GOOD]), force=True, version="v2")
    assert rec["parse_error"].startswith('the answer must be {"facts"')


def test_v2_flags_and_a_bad_not_extracted_quote_are_reported(store):
    flagged = {**V2_GOOD, "extraction_flags": ["anchor_from_context"]}
    _, rec = ex.ingest(ENTRY, UNIT, "model-a", v2([flagged, ETL_FACT, BPH_FACT],
                                                  [SKIP, {"quote": "DAP is cheap", "reason": "x"}]), version="v2")
    s = rec["summary"]
    assert s["extraction_flags"] == [{"index": 0, "flags": ["anchor_from_context"]}]
    assert s["not_extracted_failures"] == [1] and not rec["ok"]


def test_count_unit_and_indian_digit_grouping_keep_their_raw_text():
    from kg.extract.model import RawQuantity
    q = RawQuantity(target="Trichogramma japonicum", value=100000, unit="count", basis="/ha",
                    raw="@ 1,00,000/ha each release")
    assert q.value == 100000 and q.raw == "@ 1,00,000/ha each release"


def test_compare_matches_by_subtype_and_quote_and_ignores_instruction_en(store):
    _, a = ex.ingest(ENTRY, UNIT, "model-a", json.dumps([V1_GOOD, {**ETL_FACT, "steps": []}]), version="v1")
    longer = {**V2_GOOD, "quote": "Apply 40 kg of DAP before the last puddling. DAP is a good source of P.",
              "extraction_flags": ["anchor_from_context"]}
    _, b = ex.ingest(ENTRY, UNIT, "model-a", v2([longer, BPH_FACT]), version="v2")
    c = ex.compare(a, b)
    assert (c["matched"], len(c["only_from"]), len(c["only_to"])) == (1, 1, 1)
    diff = c["changed"][0]["diff"]
    assert diff == {"quote": [V1_GOOD["quote"], longer["quote"]],
                    "extraction_flags": [[], ["anchor_from_context"]]}       # whole lists, no instruction_en


def test_compare_ignores_fields_a_stored_v1_fact_never_had(store):
    _, a = ex.ingest(ENTRY, UNIT, "model-a", json.dumps([V1_GOOD]), version="v1")
    del a["facts"][0]["fact"]["extraction_flags"]                     # as stored before v2 existed
    _, b = ex.ingest(ENTRY, UNIT, "model-a", v2([V2_GOOD, ETL_FACT, BPH_FACT]), version="v2")
    c = ex.compare(a, b)
    assert c["matched"] == 1 and c["unchanged"] == 1 and c["changed"] == []


def test_a_new_run_keeps_the_earlier_one(store):
    path, first = ex.ingest(ENTRY, UNIT, "model-a", v2([V2_GOOD, ETL_FACT, BPH_FACT]), version="v2")
    path2, second = ex.ingest(ENTRY, UNIT, "model-b", v2([V2_GOOD, ETL_FACT, BPH_FACT]), version="v2")   # different cache key
    assert path2 == path and second["previous_run"] == "tnau_agriculture_2020/v2/history/%s" % (
        ex.history_name("abc123", first))
    kept = store / second["previous_run"]
    assert json.loads(kept.read_text(encoding="utf-8"))["extraction_model"] == "model-a"
    assert ex.load_run(ENTRY, UNIT["id"], str(kept))["cache_key"] == first["cache_key"]
    assert ex.load_run(ENTRY, UNIT["id"], "v2")["cache_key"] == second["cache_key"]
    with pytest.raises(ex.ExtractError, match="no run v1"):
        ex.load_run(ENTRY, UNIT["id"], "v1")


def test_forced_reruns_with_the_same_key_keep_every_run(store):
    """Before 2026-10-21 the second --force re-run overwrote history/<hash>.<key>.json, the run kept by the first,
    and the kept run's previous_run pointed at itself."""
    answer = v2([V2_GOOD, ETL_FACT, BPH_FACT])
    _, first = ex.ingest(ENTRY, UNIT, "model-a", answer, version="v2")
    _, second = ex.ingest(ENTRY, UNIT, "model-a", answer, force=True, version="v2")
    _, third = ex.ingest(ENTRY, UNIT, "model-a", answer, force=True, version="v2")
    assert first["cache_key"] == second["cache_key"] == third["cache_key"]
    assert second["previous_run"] != third["previous_run"]
    kept_first, kept_second = (json.loads((store / r["previous_run"]).read_text(encoding="utf-8"))
                               for r in (second, third))
    assert kept_first["created_at"] == first["created_at"] and kept_second["created_at"] == second["created_at"]
    assert kept_second["previous_run"] == second["previous_run"] != third["previous_run"]   # never itself
    assert len(list((store / "tnau_agriculture_2020" / "v2" / "history").glob("*.json"))) == 2


def test_an_existing_history_file_is_never_overwritten(store):
    answer = v2([V2_GOOD, ETL_FACT, BPH_FACT])
    path, first = ex.ingest(ENTRY, UNIT, "model-a", answer, version="v2")
    taken = path.parent / "history" / ex.history_name("abc123", first)
    taken.parent.mkdir()
    taken.write_text("an earlier run", encoding="utf-8")
    with pytest.raises(ex.ExtractError, match="refusing to overwrite"):
        ex.ingest(ENTRY, UNIT, "model-b", answer, version="v2")
    assert taken.read_text(encoding="utf-8") == "an earlier run"
    assert json.loads(path.read_text(encoding="utf-8"))["created_at"] == first["created_at"]   # nothing written


def test_a_new_prompt_keeps_the_earlier_one(store):
    a, b = ex.build(ENTRY, UNIT, "model-a", TABLES, version="v2"), ex.build(ENTRY, UNIT, "model-b", TABLES, version="v2")
    path = ex.write_prompt(ENTRY, UNIT, a)
    assert ex.write_prompt(ENTRY, UNIT, a) == path                              # same key: nothing to keep
    assert not (store / "tnau_agriculture_2020" / "v2" / "history").exists()
    ex.write_prompt(ENTRY, UNIT, b)
    kept = store / "tnau_agriculture_2020" / "v2" / "history" / ("abc123.%s.md" % a["cache_key"][:12])
    assert kept.read_text(encoding="utf-8") == a["prompt"] and path.read_text(encoding="utf-8") == b["prompt"]
    assert (path.parent / "abc123.key").read_text(encoding="utf-8") == b["cache_key"]


def test_file_stem_has_no_colon():
    assert ex.file_stem("unit:tnau_agriculture_2020:abc123-2") == "abc123-2"
