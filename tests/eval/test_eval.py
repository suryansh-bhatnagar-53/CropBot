"""Offline tests for step 15 (kg.eval): atoms, matching, comparison, buckets and the statistics.
Nothing here decides a disagreement; the tests check what is listed and how it is counted."""

import pytest

from kg.eval import (_counts, atoms_of, compare, gold_value, granularity, judged_extras, match, needed_n,
                     pair_status, same_basis, wilson)

UNIT = "b879265e483b"            # section A


def row(fid="A1", sheet="A", **kw):
    r = {"_sheet": sheet, "fact_id": fid, "fact_type": "ControlMeasure", "pdf_page": 66, "purpose": None,
         "where": None, "condition": None, "step": None, "alternative": None, "action": None, "input": None,
         "amount": None, "unit": None, "per": None, "timing": None, "other_values": None, "quote": "q"}
    return {**r, **kw}


def fact_rec(steps=(), pages=(66,), **kw):
    fact = {"subtype": "ControlMeasure", "quote": "Spray Acephate 75 % SP 666-1000 g or Imidacloprid 17.8 SL 100-125 ml",
            "steps": list(steps), "conditions": [], "purposes": [], "raw": {}, **kw}
    return {"fact": fact, "quote_check": {"pdf_pages": list(pages)}, "subheading": None}


def option(i, target, form, lo, hi, unit, method="direct spray towards the base of the plants"):
    return {"order": 1, "alt_group": 1, "alt_option": i, "alt_priority": None, "operation": "spraying",
            "method": method, "timing_raw": None, "conditions": [],
            "applies": [{"target": target, "formulation": form, "value": None, "min": lo, "max": hi, "unit": unit,
                         "basis": "/ha", "raw": "%s %s %g-%g %s" % (target, form, lo, hi, unit)}]}


def atoms(rec, idx=0, stem=UNIT, **flags):
    out = atoms_of(stem, idx, rec, {"purposes": []})
    for a in out:
        a.update({"section": "A", "in_scope": True, "other_pest": False, "validated": True, **flags})
    return out


def test_wilson_and_the_rows_a_threshold_needs():
    assert wilson(0, 60)[0] == 0.0 and wilson(60, 60)[1] == 1.0                   # clamped, no "-0"
    lo, hi = wilson(9, 10)
    assert 0.59 < lo < 0.6 and 0.98 < hi < 0.99
    assert needed_n(1.0) == 35                                                   # 35/35 -> lower bound 0.901
    assert needed_n(0.9) is None and needed_n(0.85) is None                      # can never reach 0.90


def test_gold_amounts_are_read_as_printed():
    v = gold_value(row(amount="666-1000"))
    assert (v["lo"], v["hi"]) == (666, 1000)
    v = gold_value(row(amount="<8%"))
    assert (v["lo"], v["hi"], v["hi_incl"], v["pct"]) == (None, 8, False, True)
    assert gold_value(row(amount=None)) is None


def test_options_get_their_own_atom_ids_and_signs_keep_their_printed_number():
    rec = fact_rec([option(1, "Acephate", "75 % SP", 666, 1000, "g"), option(2, "Imidacloprid", "17.8 SL", 100, 125, "ml")])
    ids = [a["atom"] for a in atoms(rec)]
    assert ids == ["b879#0/q1.1", "b879#0/q2.1"]                                 # options share order 1
    harvest = fact_rec([], subtype="HarvestRule", quote="When 90 % of the panicle are golden yellow",
                       maturity_signs=["90 % of the panicle are in golden yellow colour"],
                       harvest_moisture_pct_min=20, harvest_moisture_pct_max=20)
    kinds = {a["kind"]: (a["lo"], a["unit_printed"]) for a in atoms(harvest)}
    assert kinds == {"m": (90, "%"), "v": (20, "%")}


def test_numbers_choose_between_values_in_one_quote_and_a_method_row_takes_no_product():
    rec = fact_rec([option(1, "Acephate", "75 % SP", 666, 1000, "g"), option(2, "Imidacloprid", "17.8 SL", 100, 125, "ml")])
    a = atoms(rec)
    rows = [row("A1", input="Imidacloprid 17.8% SL", amount="100-125", quote="Imidacloprid 17.8 SL 100-125 ml"),
            row("A2", input="towards base of plants", quote="Direct spray towards the base of the plants.",
                action="direct spray"),
            row("A3", input="Acephate 75 % SP", amount="666-1000", quote="Acephate 75 % SP 666-1000 g")]
    rec["fact"]["quote"] += " Direct spray towards the base of the plants."
    a = atoms(rec)
    pairs = match(rows, a)
    assert [(rows[g]["fact_id"], a[i]["name"]) for g, i, _ in pairs] == [("A1", "Imidacloprid"), ("A3", "Acephate")]
    found, _, covered = granularity(rows, a, pairs)
    assert covered == {1} and "the method of 2 extracted steps" in found[0]["extracted"]


def test_a_bph_row_never_takes_an_atom_about_another_pest():
    wbph = atoms(fact_rec([option(1, "Pymetrozine", "50% WG", 300, 300, "g")]), stem="e63c6fbba0e4", other_pest=True)
    for x in wbph:
        x["section"] = "B"
    r = row("B23", sheet="B", condition="BPH; spray any one", input="Pymetrozine 50% WG", amount="300",
            quote="Pymetrozine 50% WG 300 g")
    wbph[0]["quote"] = "WBPH: Pymetrozine 50% WG 300 g"
    assert match([r], wbph) == []
    for x in wbph:
        x["other_pest"] = False
    assert len(match([r], wbph)) == 1


def test_differences_are_listed_with_both_sides_and_step_10_tables_decide_equality():
    a = atoms(fact_rec([option(1, "Acephate", "75 % SP", 666, 1000, "g")]))[0]
    same = row(input="Acephate", amount="666-1000", unit="g", per="hectare", alternative="option", step=1,
               quote="Spray Acephate 75 % SP 666-1000 g")
    assert compare(same, a, True) == []                                          # "hectare" = "/ha" by the table
    other = {**same, "amount": "666-1000", "unit": "kg", "per": "kg seed", "timing": "8 DAS", "alternative": None}
    fields = {d["field"]: (d["gold"], d["extracted"]) for d in compare(other, a, False)}
    assert fields["unit"] == ("kg", "g") and fields["basis"][0] == "kg seed" and fields["timing"] == ("8 DAS", "")
    assert fields["alternative"] == ("", "option") and fields["page"] == ("66", "66")
    assert same_basis("not stated", {**a, "per": None, "basis_inferred": True})


def test_dry_to_12_percent_against_an_upper_bound_is_listed_not_decided():
    dry = fact_rec([], subtype="DryingSpec", quote="Dry the grains to 12% moisture level for storage.",
                   target_moisture_pct_max=12, raw={"target_moisture_pct_max": "12%"})
    a = [x for x in atoms(dry) if x["kind"] == "v"][0]
    d = compare(row(fact_type="DryingSpec", amount="12%", unit="moisture", quote=dry["fact"]["quote"]), a, True)
    assert [(x["field"], x["gold"], x["extracted"]) for x in d] == [("value", "12%", "<=12")]


def test_only_a_person_closes_a_disagreement():
    diffs = [{"field": "unit"}, {"field": "basis"}]
    assert pair_status([], {}, "A6") == "agree"
    assert pair_status(diffs, {}, "A6") == "open"
    both = {("A6", "unit"): {"verdict": "both"}, ("A6", "basis"): {"verdict": "extraction"}}
    assert pair_status(diffs, both, "A6") == "agree"
    assert pair_status(diffs, {**both, ("A6", "basis"): {"verdict": "gold"}}, "A6") == "wrong"
    assert pair_status(diffs, {("A6", "unit"): {"verdict": "both"}}, "A6") == "open"


def test_an_extra_is_judged_by_name_and_quote_not_by_its_atom_id():
    a = atoms(fact_rec([option(1, "Acephate", "75 % SP", 666, 1000, "g")]))
    verdict = {"gold_id": "", "field": "extra", "verdict": "extraction", "note": "n", "atom": "e63c#99/k1",
               "name": "Acephate", "quote": a[0]["quote"]}
    assert set(judged_extras(a, set(), [verdict])) == {0}                     # the stored id differs: still found
    assert judged_extras(a, {0}, [verdict]) == {}                             # matched atoms are not extras
    assert judged_extras(a, set(), [{**verdict, "name": "Carbofuran"}]) == {}


def test_a_gold_row_naming_two_values_is_a_granularity_disagreement():
    step = option(1, "FYM", None, 1, 1, "tonne")
    step["applies"].append({**step["applies"][0], "target": "compost"})
    step["applies"][0]["formulation"] = step["applies"][1]["formulation"] = ""
    a = atoms(fact_rec([step], quote="Apply 1 tonne of FYM or compost"))
    r = row(input="FYM or compost", amount="1", quote="Apply 1 tonne of FYM or compost")
    pairs = match([r], a)
    found, covered_atoms, _ = granularity([r], a, pairs)
    assert len(pairs) == 1 and len(covered_atoms) == 1 and found[0]["rule"] == "one gold row names several values"


@pytest.mark.parametrize("row_status, lower, upper", [("agree", 2, 2), ("open", 0, 2), ("wrong", 0, 0)])
def test_a_covered_atom_takes_its_gold_rows_status_in_agreeing_precision(row_status, lower, upper):
    """Atom 0 is matched to gold row 0; atom 1 is covered by the same row through granularity."""
    a = [{"in_scope": True, "validated": True} for _ in range(2)]
    outcome = [{"gi": 0, "row": row(), "scored": True, "not_extracted": None,
                "match": {"ai": 0, "diffs": [], "status": row_status}}]
    m = _counts(outcome, a, {1: 0}, set(), {}, lambda r: True, lambda x: True)
    assert m["precision_found"]["k"] == 2
    assert (m["precision_agree_lower"]["k"], m["precision_agree_upper"]["k"]) == (lower, upper)
