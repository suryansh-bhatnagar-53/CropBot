"""Offline tests for answers (kg.query.answer): rows stand in for what the Cypher returns; no database."""

import pytest

from kg.query import FarmContext, answer
from kg.query.answer import LABEL_AUTO, LABEL_UNREVIEWED, NO_LOCAL, NO_VERIFIED
from kg.query.templates import Template, query


class Rec(dict):
    def data(self):
        return dict(self)


class FakeDriver:
    """Returns the rows the template's Cypher would: `local` for the farmer's regions, `fallback` for others."""
    def __init__(self, local=(), fallback=()):
        self.local, self.fallback, self.queries = list(local), list(fallback), []

    def execute_query(self, q, database_=None, **params):
        self.queries.append(q)
        if "MATCH (s:State)" in q:
            return [Rec(id="state:33", name="Tamil Nadu")], None, None
        rows = self.fallback if "NOT EXISTS { (r)-[:IN_REGION]" in q else self.local
        return [Rec(r) for r in rows], None, None


def row(fid, subtype, status="needs_review", regions=(("state:33", 2),), purposes=(), steps=(), clauses=(),
        conditions=(), conflicts=(), tier=1, year=2020, quote="q", **fact):
    return {"fact": {"id": fid, "subtype": subtype, "status": status, "verifier_score": 0.9, "summary_en": fid, **fact},
            "regions": [{"id": g, "level": lvl, "origin": "source"} for g, lvl in regions],
            "variety_ids": [], "season_ids": [], "system_ids": [], "soil_ids": [], "stage_ids": [],
            "purpose_ids": list(purposes), "pest_ids": [], "target_ids": [], "concerns": [],
            "conditions": list(conditions), "steps": list(steps), "clauses": list(clauses), "conflicts": list(conflicts),
            "evidence": [{"span": {"quote": quote, "pdf_page": 74, "printed_page": "62"},
                          "source": {"id": "source:tnau_agriculture_2020", "title": "Crop Production Guide",
                                     "authority_tier": tier, "edition_year": year, "state_id": "state:33"}}],
            "cautions": []}


def ctx(**kw):
    return FarmContext(crop="crop:rice", state="state:33", **kw)


SHORT = row("rec:short", "DryingSpec", purposes=["purpose:seed"], target_moisture_pct_min=12.0,
            target_moisture_pct_max=13.0, storage_term_raw="short term storage")
LONG = row("rec:long", "DryingSpec", purposes=["purpose:seed"], target_moisture_pct_min=8.0,
           target_moisture_pct_max=9.0, storage_term_raw="long term storage",
           conflicts=[{"id": "rec:store24", "subtype": "StorageRule", "status": "needs_review", "origin": "review"}])
GRAIN = row("rec:grain", "DryingSpec", status="extracted", purposes=["purpose:grain"], target_moisture_pct_max=12.0)


def test_unknown_storage_months_asks_and_branches_by_term_never_maps():
    out = answer(FakeDriver([SHORT, LONG]), "drying_target", ctx(purpose="purpose:seed"))
    assert [a["variable"] for a in out["asks"]] == ["storage_months"]
    assert [s["branch"] for s in out["slots"]] == [{"storage_months": ["long term storage"]},
                                                   {"storage_months": ["short term storage"]}]
    long_fact = out["slots"][0]["facts"][0]
    assert long_fact["labels"] == [LABEL_UNREVIEWED] and long_fact["conflicts"][0]["origin"] == "review"
    assert long_fact["citation"] == {"quote": "q", "pdf_page": 74, "printed_page": "62",
                                     "source_title": "Crop Production Guide",
                                     "source_id": "source:tnau_agriculture_2020", "status": "needs_review",
                                     "verifier_score": 0.9, "missing_in_latest_run": False,
                                     "extraction_method": None, "transcription": None}   # schema v1.5 citation
    known = answer(FakeDriver([SHORT, LONG]), "drying_target", ctx(purpose="purpose:seed", storage_months=3))
    assert known["asks"] == [] and len(known["slots"]) == 2                        # both terms, no mapping
    assert any("not mapped to 3 months" in n for n in known["notes"])


def test_unknown_purpose_branches_and_a_known_one_filters():
    out = answer(FakeDriver([GRAIN, SHORT]), "drying_target", ctx(storage_months=3))
    assert "purpose" in [a["variable"] for a in out["asks"]] and len(out["slots"]) == 2
    grain = answer(FakeDriver([GRAIN, SHORT]), "drying_target", ctx(purpose="purpose:grain"))
    assert [f["id"] for s in grain["slots"] for f in s["facts"]] == ["rec:grain"]


def test_ranking_per_slot_keeps_the_whole_top_group_and_shows_disagreement():
    zone = row("rec:zone", "DryingSpec", regions=[("zone:tn_cauvery_delta", 3)], purposes=["purpose:grain"],
               target_moisture_pct_max=13.0)
    state_a = row("rec:a", "DryingSpec", purposes=["purpose:grain"], target_moisture_pct_max=12.0)
    out = answer(FakeDriver([zone, state_a]), "drying_target",
                 ctx(purpose="purpose:grain", zones=["zone:tn_cauvery_delta"]))
    assert [f["id"] for s in out["slots"] for f in s["facts"]] == ["rec:zone"]
    assert {"fact": "rec:a", "quote": "q", "reason": "outranked in its answer slot"} in out["hidden"]
    state_b = row("rec:b", "DryingSpec", purposes=["purpose:grain"], target_moisture_pct_max=14.0)
    tie = answer(FakeDriver([state_a, state_b]), "drying_target", ctx(purpose="purpose:grain"))
    (s,) = tie["slots"]
    assert s["disagreement"] and {f["id"] for f in s["facts"]} == {"rec:a", "rec:b"}   # no LIMIT
    older = row("rec:old", "DryingSpec", purposes=["purpose:grain"], target_moisture_pct_max=14.0, year=2015)
    newer = answer(FakeDriver([state_a, older]), "drying_target", ctx(purpose="purpose:grain"))
    assert [f["id"] for s in newer["slots"] for f in s["facts"]] == ["rec:a"]          # edition_year breaks the tie


def step(applies=(), conditions=(), **kw):
    return {"order": 1, "operation": "storage", "instruction_en": "Store.", "applies": list(applies),
            "conditions": list(conditions), **kw}


def ai(reg_status):
    return {"target_id": "ai:carbendazim", "is_ai": True, "reg_status": reg_status, "value": 2.0, "unit": "g",
            "basis": "per_kg_seed"}


@pytest.mark.parametrize("status, reg, shown, label", [
    ("approved", "registered", True, []),
    ("auto_verified", "registered", True, [LABEL_AUTO]),
    ("approved", "unknown", False, []),                  # fail closed, whatever the status
    ("approved", "restricted", False, []),
    ("needs_review", "registered", False, [LABEL_UNREVIEWED]),   # an unreviewed dose stays hidden
])
def test_visibility_and_ingredients_fail_closed(status, reg, shown, label):
    r = row("rec:s", "StorageRule", status=status, purposes=["purpose:seed"], storage_months_min=8.0,
            storage_months_max=9.0, structure="gunny bags", steps=[step([ai(reg)])])
    out = answer(FakeDriver([r]), "storage", ctx(purpose="purpose:seed", storage_months=8))
    (f,) = out["slots"][0]["facts"]
    assert f["labels"] == label and bool(f["steps"]) == shown and bool(f["hidden_steps"]) != shown
    if reg != "registered":
        assert "fail closed" in f["hidden_steps"][0]["reason"]


def test_a_fact_with_only_a_hidden_dose_is_hidden_with_its_reason():
    r = row("rec:carb", "StorageRule", purposes=["purpose:seed"], steps=[step([ai("unknown")])],
            storage_months_min_inclusive=True, max_moisture_pct_inclusive=True)     # flags alone are no answer
    out = answer(FakeDriver([r]), "storage", ctx(purpose="purpose:seed", storage_months=8))
    assert out["slots"] == [] and out["message"] == NO_VERIFIED
    assert out["hidden"][0]["reason"].startswith("ingredient not registered (fail closed)")


STORE = [row("rec:s%d" % i, "StorageRule", purposes=["purpose:seed"], storage_months_min=lo, storage_months_max=hi,
             storage_months_min_inclusive=hi is not None, max_moisture_pct=m) for i, (lo, hi, m) in
         enumerate([(8.0, 9.0, 13.0), (12.0, 15.0, 9.0), (15.0, None, 8.0)])]


def test_storage_windows_and_the_gap_between_them():
    unknown = answer(FakeDriver(STORE), "storage", ctx(purpose="purpose:seed"))
    assert [a["variable"] for a in unknown["asks"]] == ["storage_months"] and len(unknown["slots"]) == 3
    three = answer(FakeDriver(STORE), "storage", ctx(purpose="purpose:seed", storage_months=13))
    assert [f["id"] for s in three["slots"] for f in s["facts"]] == ["rec:s1"]
    sixteen = answer(FakeDriver(STORE), "storage", ctx(purpose="purpose:seed", storage_months=16))
    assert [f["id"] for s in sixteen["slots"] for f in s["facts"]] == ["rec:s2"]     # "more than 15"
    fifteen = answer(FakeDriver(STORE), "storage", ctx(purpose="purpose:seed", storage_months=15))
    assert [f["id"] for s in fifteen["slots"] for f in s["facts"]] == ["rec:s1"]     # 15 is not "more than 15"
    gap = answer(FakeDriver(STORE), "storage", ctx(purpose="purpose:seed", storage_months=10))
    assert gap["slots"] == [] and [a["variable"] for a in gap["asks"]] == ["storage_months"]
    assert "no rule for 10 months" in gap["notes"][0] and "8 to 9 months" in gap["notes"][0]


def clause(value, cond):
    return {"observation": "hoppers", "value": value, "unit": "count", "sampling_unit": "per_tiller",
            "raw": "%d hopper/ tiller" % value, "conditions": [cond]}


BPH = row("rec:bph", "PestThreshold", clauses=[
    clause(1.0, {"variable": "spider_count_per_hill", "op": "<", "value": 1.0, "any_of_group": 1,
                 "raw": "in the absence of predatory spider"}),
    clause(2.0, {"variable": "spider_count_per_hill", "op": ">=", "value": 1.0, "any_of_group": 1,
                 "raw": "when spider is present at 1/hill"})])


def test_threshold_asks_for_spiders_and_keeps_both_clauses_until_counted():
    c = ctx(pest="pest:brown_planthopper")
    out = answer(FakeDriver([BPH]), "threshold", c)
    assert [a["variable"] for a in out["asks"]] == ["spider_count_per_hill"]
    (f,) = out["slots"][0]["facts"]
    assert [cl["value"] for cl in f["clauses"]] == [1.0, 2.0] and f["labels"] == [LABEL_UNREVIEWED]
    counted = answer(FakeDriver([BPH]), "threshold", ctx(pest="pest:brown_planthopper",
                                                         observations={"spider_count_per_hill": 0}))
    assert counted["asks"] == [] and [cl["value"] for cl in counted["slots"][0]["facts"][0]["clauses"]] == [1.0]
    assert answer(FakeDriver([BPH]), "threshold", ctx())["asks"][0]["variable"] == "pest"


def test_scope_in_unmapped_hides_the_fact_until_approved():
    scoped = {**BPH, "fact": {**BPH["fact"], "scope_in_unmapped": ["in tungro endemic area"]}}
    out = answer(FakeDriver([scoped]), "threshold", ctx(pest="pest:brown_planthopper"))
    assert out["slots"] == [] and out["hidden"] == [{
        "fact": BPH["fact"]["id"], "quote": "q",
        "reason": "scope in unmapped: served scope would be wider than printed (in tungro endemic area)"}]
    approved = {**scoped, "fact": {**scoped["fact"], "status": "approved"}}
    assert answer(FakeDriver([approved]), "threshold", ctx(pest="pest:brown_planthopper"))["slots"]


def test_scope_in_unmapped_never_hides_a_caution():
    """A caution served more widely than printed only warns more; it stays labelled unverified."""
    from kg.query.answer import render
    from kg.query.templates import Template
    caution = row("rec:c", "Caution", text_en="avoid synthetic pyrethroids",
                  scope_in_unmapped=["In BPH prone areas/seasons"])
    c = {"row": caution, "unknown": {}, "explicit": 0, "variety": 0}          # as candidates() builds it
    served, reasons = render(c, ctx(), Template("Caution", ("text_en",)), "local", None, {})
    assert served and served["labels"] == [LABEL_UNREVIEWED] and not reasons


def test_conservative_unknown_withholds_an_action():
    rain = {"variable": "forecast_rain_mm_24h", "op": "<", "value": 5.0, "any_of_group": 1, "raw": "no rain"}
    r = row("rec:dry", "DryingSpec", purposes=["purpose:grain"], target_moisture_pct_max=12.0, conditions=[rain])
    out = answer(FakeDriver([r]), "drying_target", ctx(purpose="purpose:grain"))
    assert out["slots"] == [] and out["hidden"] == [{"fact": "rec:dry", "quote": "q",
                                                     "reason": "withheld: forecast_rain_mm_24h unknown"}]


def test_cross_state_fallback_only_when_nothing_local_and_labelled():
    other = ctx(purpose="purpose:grain").model_copy(update={"state": "state:test_other"})
    out = answer(FakeDriver([], [GRAIN]), "drying_target", other)
    assert out["scope"] == "fallback"
    assert out["slots"][0]["facts"][0]["labels"] == [LABEL_UNREVIEWED, "From a Tamil Nadu source"]
    none = answer(FakeDriver([], []), "drying_target", other)
    assert none["scope"] == "none" and none["message"] == NO_LOCAL
    local = FakeDriver([GRAIN], [GRAIN])
    answer(local, "drying_target", ctx(purpose="purpose:grain"))
    assert not any("NOT EXISTS { (r)-[:IN_REGION]" in q for q in local.queries)     # local answer: no fallback
    with pytest.raises(ValueError, match="never crosses state lines"):
        query(Template("NutrientDose", ()), "fallback")
    assert "LIMIT" not in query(Template("DryingSpec", ()), "local")


def test_v13_fields_are_served():
    store = row("rec:s", "StorageRule", purposes=["purpose:seed"], storage_months_min=8.0, storage_months_max=9.0,
                min_moisture_pct=12.0, max_moisture_pct=13.0, min_moisture_pct_inclusive=True,
                max_moisture_pct_inclusive=True)
    (f,) = answer(FakeDriver([store]), "storage", ctx(purpose="purpose:seed", storage_months=8))["slots"][0]["facts"]
    assert (f["values"]["min_moisture_pct"], f["values"]["max_moisture_pct"]) == (12.0, 13.0)
    sweeps = row("rec:t", "PestThreshold", clauses=[{"observation": "bugs", "value": 5, "unit": "count",
                                                    "sampling_count": 25, "sampling_object": "net_sweep",
                                                    "raw": "5/25 net sweeps", "conditions": []}])
    (t,) = answer(FakeDriver([sweeps]), "threshold", ctx(pest="pest:earhead_bug"))["slots"][0]["facts"]
    assert (t["clauses"][0]["sampling_count"], t["clauses"][0]["sampling_object"]) == (25, "net_sweep")
    assert ctx(soil={"Zn": "low"}).value("soil_Zn_rating") == "low"


def test_approved_but_missing_is_served_with_the_flag():
    r = row("rec:m", "DryingSpec", status="approved", purposes=["purpose:grain"], target_moisture_pct_max=12.0,
            missing_in_latest_run=True)
    (f,) = answer(FakeDriver([r]), "drying_target", ctx(purpose="purpose:grain"))["slots"][0]["facts"]
    assert f["labels"] == [] and f["citation"]["missing_in_latest_run"] is True
