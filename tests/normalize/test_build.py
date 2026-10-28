"""Offline tests for building final facts (kg.normalize): conversions, quantity_ref, scope,
holding and status. Raw facts are made with the step 9 raw model."""

import copy

from kg.extract.model import FACT as RAW
from kg.normalize import Fact, build, resolve_quantity_refs
from kg.normalize.link import Linker
from kg.schema import FACT
from kg.schema.concepts import AgroClimaticZone, Fertilizer, Label, Pest, Purpose, SoilType

NODES = [
    Fertilizer(id="fertilizer:dap", name_en="DAP", n_pct=18, p2o5_pct=46, k2o_pct=0, review_status="approved",
               source="x"),
    Pest(id="pest:brown_planthopper", name_en="Brown planthopper", pest_type="insect", review_status="approved"),
    SoilType(id="soil:clay", name_en="Clay", review_status="approved"),
    Label(concept_id="soil:clay", text="clayey soils", lang="en", script="Latn", kind="alias", review_status="approved"),
    *[AgroClimaticZone(id=z, name_en=n, scheme="state_book", state_id="state:33", review_status="approved")
      for z, n in (("zone:tn_cauvery_delta", "Cauvery Delta"), ("zone:tn_western", "Western Zone"),
                   ("zone:tn_southern", "Southern Zone"))],
]
L = Linker(NODES)
ZONES = {"state:33": ["zone:tn_cauvery_delta", "zone:tn_western", "zone:tn_southern"]}
UNIT = {"id": "unit:tnau_agriculture_2020:abc", "source_id": "source:tnau_agriculture_2020",
        "section_path": "RICE > 1.1 Nursery management > 1.1.1. Wet nursery", "pdf_pages": [30, 30],
        "regions": [{"id": "state:33", "origin": "source"}], "purposes": [], "default_scope": []}
RUN = {"extraction_model": "m", "prompt_version": "v2", "cache_key": "k" * 64}
QC = {"ok": True, "occurrences": 1, "refs": ["#/texts/106"], "pdf_pages": [30], "printed_pages": ["18"]}
DAP_STEP = {"order": 1, "operation": "fertilizer_application", "anchor": "last_puddling",
            "timing_raw": "before the last puddling",
            "applies": [{"target": "DAP", "value": 40, "unit": "kg", "basis": "20 cents nursery",
                         "basis_inferred": True, "raw": "40 kg of DAP"}]}


def raw_fact(index=0, unit=UNIT, **fields):
    data = {"subtype": "NutrientDose", "dose_basis": "blanket", "summary_en": "s", "quote": "q",
            "steps": [copy.deepcopy(DAP_STEP)], **fields}
    return Fact(RUN, unit, {"index": index, "fact": RAW.validate_python(data).model_dump(mode="json"),
                            "quote_check": QC})


def finish(f, d):
    """What run() adds before validation: evidence, keys, ids, status, instructions."""
    d["evidence"] = [{"id": "span:x", "source_id": UNIT["source_id"], "pdf_page": 30, "section_path": "s",
                      "quote": "q", "extraction_method": "native_text"}]
    d["fact_key"], d["id"] = "fk:x", "rec:x"
    d["status"] = "needs_review" if f.review else "extracted"
    for s in d["steps"]:
        s["instruction_en"] = "x"
    return FACT.validate_python(d)


def test_nursery_dose_converts_and_validates():
    f = raw_fact()
    d = build(f, L, "crop:rice", ZONES)
    a = d["steps"][0]["applies"][0]
    assert (a["target_id"], a["value"], a["unit"], a["basis"], a["area_cents"], a["raw"]) == (
        "fertilizer:dap", 2, "kg", "per_cent_nursery", 20, "40 kg of DAP")
    assert f.conversions[0]["rule"] == "kg -> kg; 20 cents nursery -> per_cent_nursery (/20, area_cents 20)"
    assert not f.blocks and any("basis inferred" in r for r in f.review)
    assert finish(f, d).status.value == "needs_review"


def test_quantity_ref_is_inherited_from_the_one_earlier_fact():
    first = raw_fact(0)
    later = raw_fact(1, steps=[{"order": 1, "operation": "fertilizer_application",
                                "applies": [{"target": "DAP", "quantity_ref": "previous"}]}])
    built = [(first, build(first, L, "crop:rice", ZONES)), (later, build(later, L, "crop:rice", ZONES))]
    resolve_quantity_refs(built)
    a = built[1][1]["steps"][0]["applies"][0]
    assert (a["value"], a["basis"], a["area_cents"], a["inherited"]) == (2, "per_cent_nursery", 20, True)
    assert not later.blocks and finish(later, built[1][1]).status.value == "needs_review"


def test_quantity_ref_with_no_or_several_candidates_is_held():
    later = raw_fact(2, steps=[{"order": 1, "operation": "fertilizer_application",
                                "applies": [{"target": "DAP", "quantity_ref": "previous"}]}])
    built = [(later, build(later, L, "crop:rice", ZONES))]
    resolve_quantity_refs(built)
    assert later.blocks == ["quantity_ref for fertilizer:dap: 0 earlier facts state an amount"]
    a, b = raw_fact(0), raw_fact(1)
    later = raw_fact(2, steps=[{"order": 1, "operation": "fertilizer_application",
                                "applies": [{"target": "DAP", "quantity_ref": "previous"}]}])
    built = [(x, build(x, L, "crop:rice", ZONES)) for x in (a, b, later)]
    resolve_quantity_refs(built)
    assert later.blocks == ["quantity_ref for fertilizer:dap: 2 earlier facts state an amount"]


def test_exclusion_is_expanded_by_code():
    f = raw_fact(excluded_regions=[{"name": "Cauvery Delta", "raw": "other than Cauvery Delta"}])
    d = build(f, L, "crop:rice", ZONES)
    assert d["regions"] == [{"id": "zone:tn_western", "origin": "text_exclusion"},
                            {"id": "zone:tn_southern", "origin": "text_exclusion"}]
    assert d["excluded_regions"] == [{"id": "zone:tn_cauvery_delta", "raw": "other than Cauvery Delta"}]
    assert finish(f, d).status.value == "needs_review"


def test_section_purpose_merges_with_the_quote():
    unit = {**UNIT, "purposes": [{"id": "purpose:seed", "origin": "section"}]}
    f = raw_fact(unit=unit)
    d = build(f, Linker(NODES + [Purpose(id="purpose:seed", name_en="Seed", review_status="approved")]),
              "crop:rice", ZONES)
    assert d["purpose_ids"] == ["purpose:seed"] and f.purpose_origins == {"purpose:seed": ["section"]}


def test_blocking_reasons():
    f = raw_fact(soils=["sandy soils"])
    build(f, L, "crop:rice", ZONES)
    assert f.blocks == ["unlinked soil 'sandy soils' (no concept matches)"]
    f = raw_fact(soils=["clayey soils"])
    assert build(f, L, "crop:rice", ZONES)["soil_ids"] == ["soil:clay"] and not f.blocks
    f = raw_fact(steps=[{"order": 1, "method": "release",
                         "applies": [{"target": "DAP", "value": 0.5, "unit": "%", "raw": "0.5 % DAP"}]}])
    build(f, L, "crop:rice", ZONES)
    # schema v1.4: the no-operation check runs after the formulation table, so it is listed last
    assert f.blocks == ["no basis printed or given by a rule (a concentration or share); raw '0.5 % DAP'",
                        "step 1 has no operation; method 'release'"]
    f = Fact(RUN, UNIT, {"index": 0, "quote_check": QC, "fact": RAW.validate_python(
        {"subtype": "ControlMeasure", "summary_en": "s", "quote": "q", "control_class": "cultural", "targets": ["Pest"],
         "steps": [{"order": 1, "operation": "weeding"}]}).model_dump(mode="json")})
    build(f, L, "crop:rice", ZONES)
    assert f.blocks == ["unlinked target 'Pest' (generic target, no concept)"]


def test_one_soil_phrase_gives_two_soil_edges():
    nodes = NODES + [SoilType(id="soil:saline", name_en="Saline", review_status="approved"),
                     SoilType(id="soil:sodic", name_en="Sodic", review_status="approved")] + [
        Label(concept_id=c, text="saline / sodic soils", lang="en", script="Latn", kind="alias",
              review_status="approved") for c in ("soil:saline", "soil:sodic")]
    f = raw_fact(soils=["saline / sodic soils"])
    d = build(f, Linker(nodes), "crop:rice", ZONES)
    assert d["soil_ids"] == ["soil:saline", "soil:sodic"] and not f.blocks


def test_flags_and_unlinked_step_stage_mean_review_not_hold():
    f = raw_fact(extraction_flags=["shared_amount"],
                 steps=[{**copy.deepcopy(DAP_STEP), "anchor": None, "stage": "panicle initiation",
                         "timing_raw": "at panicle initiation"}])
    d = build(f, L, "crop:rice", ZONES)
    assert not f.blocks and d["steps"][0]["stage_id"] is None and d["steps"][0]["timing_raw"] == "at panicle initiation"
    assert any("flags" in r for r in f.review) and any("stage" in r for r in f.review)
    assert finish(f, d).status.value == "needs_review"


def drying(index, term, quote):
    data = {"subtype": "DryingSpec", "summary_en": "s", "quote": quote, "purposes": ["seeds"],
            "target_moisture_pct_max": 13, "raw": {"target_moisture_pct_max": "13 %"}, "storage_term_raw": term,
            "steps": [{"order": 1, "operation": "drying"}]}
    return Fact(RUN, UNIT, {"index": index, "fact": RAW.validate_python(data).model_dump(mode="json"), "quote_check": QC})


def key(f):
    from kg.normalize import fact_key_parts
    return fact_key_parts(f, build(f, Linker(NODES + [Purpose(id="purpose:seed", name_en="Seed",
                                                             review_status="approved")]), "crop:rice", ZONES))


def test_fact_key_identity_includes_storage_term_and_conditions():
    short, long_ = drying(0, "short term storage", "a"), drying(1, "long term storage", "b")
    assert key(short) != key(long_)                                   # same passage, different storage term
    assert key(short) == key(drying(2, "short term storage", "different words, same passage"))
    cond = {"variable": "spider_count_per_hill", "op": ">=", "value": 1, "raw": "when spider is present at 1/hill"}
    a, b = raw_fact(0), raw_fact(1, conditions=[cond])
    assert key(a) != key(b)
    assert key(b)["identity"]["conditions"] == [("spider_count_per_hill", ">=", "when spider is present at 1/hill")]


def test_a_fact_inheriting_from_a_held_fact_is_held_too():
    from kg.normalize import hold_inheritors
    source, child, grandchild, other = raw_fact(0), raw_fact(1), raw_fact(2), raw_fact(3)
    source.blocks.append("unlinked applies target 'x'")
    child.inherits_from.add((UNIT["id"], 0))
    grandchild.inherits_from.add((UNIT["id"], 1))
    other.inherits_from.add((UNIT["id"], 9))
    hold_inheritors([grandchild, child, source, other])
    assert child.blocks == ["inherits its amount from held fact 0"]
    assert grandchild.blocks == ["inherits its amount from held fact 1"]
    assert other.blocks == []


def test_basis_rule_must_be_approved_for_the_unit():
    rule = "dose basis = per_ha unless stated [ii) Main field, PDF pp. 63-69]"
    step = {"order": 1, "operation": "spraying", "applies": [
        {"target": "DAP", "value": 1000, "unit": "ml", "basis": "per_ha", "basis_rule": rule, "raw": "1000 ml"}]}
    f = raw_fact(steps=[step])
    build(f, L, "crop:rice", ZONES)
    assert f.blocks == ["basis rule %r is not approved for this unit" % rule]
    f = raw_fact(unit={**UNIT, "default_scope": [rule]}, steps=[step])
    d = build(f, L, "crop:rice", ZONES)
    assert not f.blocks and d["steps"][0]["applies"][0]["basis"] == "per_ha"
