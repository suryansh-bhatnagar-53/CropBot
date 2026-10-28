"""Answers (step 14): applicability, conditions, ranking per answer slot, visibility, safety joins and
citations, on the rows a template fetched.

- Applicability: a missing optional edge matches anything; an edge must match the farm context; a value
  the farmer has not given is UNKNOWN: the answer asks, and branches on the facts' values.
- Conditions: three-valued, top-down (recommendation, step, clause); FALSE prunes; UNKNOWN follows the
  variable's on_unknown policy (conservative withholds actions; Cautions still fire).
- Ranking, per answer slot (subtype, identity, storage window or term, which values it gives, branch):
  region level, variety match, explicit season/system/soil/purpose matches, authority_tier (lower is
  better), edition_year (newer is better). No LIMIT: the slot keeps its whole top-ranked group; facts
  tied there with different values are a disagreement and both are shown.
- Visibility: rejected and superseded facts are never fetched; a non-approved fact missing from the latest
  run is not fetched either. approved is served; auto_verified is labelled; extracted and needs_review are
  unreviewed: descriptive subtypes are shown labelled "not yet verified by an expert", doses are hidden.
  A fact with scope in its unmapped phrases (step 11) is hidden until approved, unless it is a Caution: a
  caution served more widely than printed only warns more.
- Safety: a step applying an active ingredient whose reg_status is not "registered" is dropped (fail
  closed, stricter than schema v1.2); templates with safety joins add the Cautions on their ingredients.
- Cross-state: only when the farmer's own regions return nothing, and only for the subtypes the schema
  allows, labelled with the source's state.
"""

import json

from kg.schema.vocab import SCOPE_IN_UNMAPPED_REASON, OnUnknown

from .logic import FALSE, TRUE, UNKNOWN, combine, policy, question
from .templates import CROSS_FREELY, FALLBACK_ONLY, STATE_NAMES, TEMPLATES, fetch

UNREVIEWED = {"extracted", "needs_review"}
# shown while unreviewed, labelled; QualitySpec (schema v1.5, 2026-10-23) is a printed limit, not a dose
DESCRIPTIVE = {"DryingSpec", "StorageRule", "HarvestRule", "PestThreshold", "Caution", "QualitySpec"}
ALL_GRADES = {"grade_a", "common"}
ASKED_PARAMETERS = {"moisture": "grain_moisture_pct"}   # quality_check asks for these when unknown
# a grade rule decides which grade the produce is, not whether it is accepted ("L:B >= 2.5 is Grade 'A'")
CLASSIFYING = {"length_breadth_ratio"}
LABEL_AUTO = "checked automatically against the source"
LABEL_UNREVIEWED = "not yet verified by an expert"
NO_LOCAL = "No local guidance available"
NO_VERIFIED = "No verified guidance available"
WINDOW = ("storage_months_min", "storage_months_max", "storage_months_min_inclusive", "storage_months_max_inclusive")
VALUE_SKIP = {"id", "status", "verifier", "verifier_score", "verifier_claims", "verifier_claim_p_yes",
              "verifier_notes", "review_reasons", "review_notes", "extraction_flags", "created_at",
              "missing_in_latest_run", "summary_en", "text_en", "conflict_key", "value_key", "fact_key",
              "extraction_model", "reviewed_by", "scope_in_unmapped"}


def quote_of(row: dict) -> str | None:
    return row["evidence"][0]["span"].get("quote") if row.get("evidence") else None


def num(v) -> str:
    return ("%.4f" % v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def window_text(f: dict) -> str:
    lo, hi = f.get("storage_months_min"), f.get("storage_months_max")
    if lo is not None and hi is not None:
        return "%s to %s months" % (num(lo), num(hi))
    if lo is not None:
        return "%s %s months" % ("more than" if f.get("storage_months_min_inclusive") is False else "at least", num(lo))
    if hi is not None:
        return "%s %s months" % ("less than" if f.get("storage_months_max_inclusive") is False else "up to", num(hi))
    return f.get("storage_term_raw") or "any period"


def window_state(f: dict, months) -> str:
    """'wild' (no months in the fact), or TRUE / FALSE / UNKNOWN for the farmer's storage months."""
    lo, hi = f.get("storage_months_min"), f.get("storage_months_max")
    if lo is None and hi is None:
        return "wild"
    if months is None:
        return UNKNOWN
    ok_lo = lo is None or lo < months or (lo == months and f.get("storage_months_min_inclusive") is not False)
    ok_hi = hi is None or months < hi or (months == hi and f.get("storage_months_max_inclusive") is not False)
    return TRUE if ok_lo and ok_hi else FALSE


def applicability(row: dict, ctx) -> tuple[bool, dict, int, int]:
    """(matches, {unknown variable: the fact's values}, explicit matches, variety match)."""
    unknown, explicit, variety = {}, 0, 0
    checks = (("variety_ids", "variety", [ctx.variety] if ctx.variety else None),
              ("season_ids", "season", [x for x in [ctx.season, *ctx.local_seasons] if x] or None),
              ("system_ids", "system", ctx.systems or None),
              ("soil_ids", "soil_type", ctx.soil_types or None),
              ("purpose_ids", "purpose", [ctx.purpose] if ctx.purpose else None),
              ("stage_ids", "stage", [ctx.stage] if ctx.stage else None))
    for key, var, have in checks:
        values = row.get(key) or []
        if not values:
            continue                                         # no edge: matches anything
        if have is None:
            unknown[var] = sorted(values)
            continue
        if not set(values) & set(have):
            return False, {}, 0, 0
        if var == "variety":
            variety = 1
        elif var in ("season", "system", "soil_type", "purpose"):
            explicit += 1
    dg = row["fact"].get("duration_group")
    if dg:
        if ctx.duration_group is None:
            unknown["duration_group"] = [dg]
        elif dg != ctx.duration_group:
            return False, {}, 0, 0
    f = row["fact"]
    if f["subtype"] == "QualitySpec":            # schema v1.5: what is sold, and its grade
        form = f.get("commodity_form")
        if ctx.commodity_form is None:
            unknown["commodity_form"] = [form]
        elif form != ctx.commodity_form:
            return False, {}, 0, 0
        grades = set(f.get("grades") or [])
        if ctx.grade is None:
            # a limit for every grade needs no question; a grade rule is how the grade is found, so it never asks
            if grades != ALL_GRADES and f.get("parameter") not in CLASSIFYING:
                unknown["grade"] = sorted(grades)
        elif ctx.grade not in grades:
            return False, {}, 0, 0
    return True, unknown, explicit, variety


def quality_check(f: dict, ctx) -> dict:
    """Schema v1.5: the farmer's value against one limit: pass, fail, or unknown when not given."""
    if f["limit_type"] == "absent":
        found = ctx.present.get(f["parameter"])
        result = UNKNOWN if found is None else (FALSE if found else TRUE)
        return {"parameter": f["parameter"], "value": found, "result": {TRUE: "pass", FALSE: "fail"}.get(result, "unknown")}
    v = ctx.quality_value(f["parameter"])
    if v is None:
        return {"parameter": f["parameter"], "value": None, "result": "unknown"}
    limit, inclusive = f["limit_value"], f.get("limit_inclusive") is not False
    ok = (v < limit or (inclusive and v == limit)) if f["limit_type"] == "max" else \
        (v > limit or (inclusive and v == limit))
    return {"parameter": f["parameter"], "value": v, "result": "pass" if ok else "fail"}


def candidates(rows: list[dict], ctx, t) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    """(candidates, facts left out only by the storage window, withheld facts, notes)."""
    out, outside, withheld, notes = [], [], [], []
    for row in rows:
        f = row["fact"]
        ok, unknown, explicit, variety = applicability(row, ctx)
        if not ok:
            continue
        state, cvars = combine(row["conditions"], ctx)
        if state == FALSE:
            continue
        if state == UNKNOWN and f["subtype"] != "Caution" and any(policy(v) is OnUnknown.CONSERVATIVE for v in cvars):
            withheld.append({"fact": f["id"], "quote": quote_of(row),
                             "reason": "withheld: %s unknown" % ", ".join(cvars)})
            continue
        if t.window:
            w = window_state(f, ctx.storage_months)
            if w == FALSE:
                outside.append(row)
                continue
            if w == UNKNOWN or (w == "wild" and f.get("storage_term_raw") and ctx.storage_months is None):
                unknown["storage_months"] = [window_text(f)]
            elif w == "wild" and f.get("storage_term_raw"):
                notes.append("the source gives %r without months; it is not mapped to %s months"
                              % (f["storage_term_raw"], num(ctx.storage_months)))
        out.append({"row": row, "unknown": unknown, "explicit": explicit, "variety": variety,
                    "condition_unknown": cvars})
    return out, outside, withheld, notes


def slot(c: dict, t) -> str:
    row, f = c["row"], c["row"]["fact"]
    gives = sorted(k for k in t.fields if f.get(k) not in (None, []) and not k.endswith("_inclusive"))
    quality = [f.get(k) for k in ("commodity_form", "grades", "parameter", "limit_type", "part_of")] \
        if f["subtype"] == "QualitySpec" else []          # schema v1.5: one slot per limit
    if f["subtype"] == "SowingWindow":                    # schema v1.6: one slot per operation the window is for
        quality = [f.get("window_for") or "sowing"]
    return json.dumps([f["subtype"], sorted(row["pest_ids"]), sorted(row["target_ids"]), sorted(row["concerns"]),
                       f.get("kind"), f.get("storage_term_raw"), [f.get(k) for k in WINDOW], gives,
                       sorted({s.get("operation") for s in row["steps"]}), sorted(c["unknown"].items()), quality],
                      default=str)


def rank(c: dict, ctx, scope: str) -> tuple:
    row = c["row"]
    region = max([g["level"] or 0 for g in row["regions"] if g["id"] in ctx.region_ids()] or [0]) if scope == "local" else 0
    src = row["evidence"][0]["source"] if row["evidence"] else {}
    tier, year = src.get("authority_tier") or 9, src.get("edition_year") or 0
    return (region, c["variety"], c["explicit"], -tier, year)


def value_signature(row: dict) -> str:
    f = {k: v for k, v in row["fact"].items() if k not in VALUE_SKIP and not k.startswith("raw_")}
    steps = sorted([[s.get("order"), s.get("operation"), s.get("offset_min"), s.get("offset_max"),
                     sorted([a["target_id"], a.get("value"), a.get("min"), a.get("max"), a.get("unit"), a.get("basis")]
                            for a in s["applies"])] for s in row["steps"]], key=str)
    clauses = sorted([[c.get("observation"), c.get("value"), c.get("unit"), c.get("sampling_unit")]
                      for c in row["clauses"]], key=str)
    return json.dumps([f, steps, clauses], sort_keys=True, default=str)


def render(c: dict, ctx, t, scope: str, label_fallback: str | None, asks: dict) -> tuple[dict | None, list[str]]:
    """The fact as served, or None with the reasons it is hidden."""
    row, f = c["row"], c["row"]["fact"]
    status = f["status"]
    unreviewed = status in UNREVIEWED
    if unreviewed and f["subtype"] not in DESCRIPTIVE:
        return None, ["%s not yet verified by an expert" % f["subtype"]]
    if status != "approved" and f.get("scope_in_unmapped") and f["subtype"] != "Caution":
        return None, ["%s (%s)" % (SCOPE_IN_UNMAPPED_REASON, "; ".join(f["scope_in_unmapped"]))]
    shown_steps, hidden_steps = [], []
    for s in sorted(row["steps"], key=lambda s: (s.get("order") or 0, s.get("alt_group") or 0, s.get("alt_option") or 0)):
        state, svars = combine(s["conditions"], ctx)
        if state == FALSE:
            continue
        bad = [a for a in s["applies"] if a.get("is_ai") and a.get("reg_status") != "registered"]
        reason = None
        if bad:
            reason = "ingredient not registered (fail closed): %s" % ", ".join(
                "%s=%s" % (a["target_id"], a.get("reg_status") or "not seeded") for a in bad)
        elif s["applies"] and status != "approved" and any(a.get("basis_inferred") or a.get("inherited")
                                                           for a in s["applies"]):
            reason = "inferred basis or inherited amount"
        elif s["applies"] and unreviewed:
            reason = "dose not yet verified by an expert"
        elif state == UNKNOWN and any(policy(v) is OnUnknown.CONSERVATIVE for v in svars):
            reason = "withheld: %s unknown" % ", ".join(svars)
        for v in svars:
            asks.setdefault(v, question(v))
        step = {"operation": s.get("operation"), "method": s.get("method"), "timing_raw": s.get("timing_raw"),
                "instruction_en": s.get("instruction_en"),
                "if": [x["raw"] for x in s["conditions"]] if state == UNKNOWN else []}
        (hidden_steps.append({**step, "reason": reason}) if reason else shown_steps.append(step))
    clauses = []
    for cl in row["clauses"]:
        state, cvars = combine(cl["conditions"], ctx)
        if state == FALSE:
            continue
        for v in cvars:
            asks.setdefault(v, question(v))
        clauses.append({"observation": cl.get("observation"), "value": cl.get("value"), "unit": cl.get("unit"),
                        "sampling_unit": cl.get("sampling_unit"), "sampling_count": cl.get("sampling_count"),
                        "sampling_object": cl.get("sampling_object"), "raw": cl.get("raw"),
                        "conditions": [{"raw": x["raw"], "state": combine([x], ctx)[0]} for x in cl["conditions"]]})
    # an inclusive flag is shown only beside its bound; on its own it is not an answer
    values = {k: f[k] for k in t.fields if f.get(k) not in (None, [])
              and (not k.endswith("_inclusive") or f.get(k.removesuffix("_inclusive")) is not None)}
    if row.get("recommends"):                              # schema v1.6: the varieties are edges, not properties
        values["recommends"] = sorted(row["recommends"], key=lambda v: v["id"])
    if not values and not shown_steps and not clauses:
        return None, [h["reason"] for h in hidden_steps] or ["nothing applies"]
    span = row["evidence"][0]["span"] if row["evidence"] else {}
    src = row["evidence"][0]["source"] if row["evidence"] else {}
    labels = [x for x in (LABEL_AUTO if status == "auto_verified" else LABEL_UNREVIEWED if unreviewed else None,
                          label_fallback) if x]
    served = {
        "id": f["id"], "subtype": f["subtype"], "summary_en": f.get("summary_en"),
        "duration_group": f.get("duration_group"), "labels": labels,
        "branch": c["unknown"], "values": values, "clauses": clauses, "steps": shown_steps,
        "hidden_steps": hidden_steps, "conflicts": row["conflicts"],
        "cautions": [{**k, "labels": [LABEL_UNREVIEWED] if k.get("status") in UNREVIEWED else []}
                     for k in row["cautions"]] if t.safety else [],
        "rank": dict(zip(("region_level", "variety", "explicit", "authority_tier", "edition_year"),
                         [*rank(c, ctx, scope)[:3], -rank(c, ctx, scope)[3], rank(c, ctx, scope)[4]])),
        "citation": {"quote": span.get("quote"), "pdf_page": span.get("pdf_page"),
                     "printed_page": span.get("printed_page"), "source_title": src.get("title"),
                     "source_id": src.get("id"),
                     "status": status, "verifier_score": f.get("verifier_score"),
                     "missing_in_latest_run": bool(f.get("missing_in_latest_run")),
                     # schema v1.5: a quote from an approved page transcription names it
                     "extraction_method": span.get("extraction_method"), "transcription": span.get("transcription")},
    }
    if f["subtype"] == "QualitySpec":
        served["check"] = quality_check(f, ctx)
    return served, []


def answer(driver, template_name: str, ctx, database=None) -> dict:
    t = TEMPLATES[template_name]
    out = {"template": template_name, "scope": "local", "asks": [], "slots": [], "hidden": [], "notes": [],
           "message": None}
    if t.needs_pest and not ctx.pest:
        out |= {"scope": "none", "asks": [question("pest")], "message": "Which pest is this about?"}
        return out
    cands, outside, withheld, notes = candidates(fetch(driver, t, ctx, "local", database), ctx, t)
    scope, state_names = "local", {}
    if not cands and not outside and not withheld and t.subtype in FALLBACK_ONLY | CROSS_FREELY:
        cands, outside, withheld, notes = candidates(fetch(driver, t, ctx, "fallback", database), ctx, t)
        if cands:
            scope = "fallback"
            rows, _, _ = driver.execute_query(STATE_NAMES, database_=database)
            state_names = {r["id"]: r["name"] for r in rows}
    out["hidden"] += withheld
    out["notes"] += sorted(set(notes))
    asks = {}
    # a storage period between the source's windows gets a question back, never a guess
    gap = (t.window and outside and ctx.storage_months is not None
           and not any(window_state(c["row"]["fact"], ctx.storage_months) == TRUE for c in cands))
    if gap:
        out["notes"].append("the source has no rule for %s months; it gives: %s" % (
            num(ctx.storage_months), "; ".join(sorted({window_text(r["fact"]) for r in outside}))))
        asks["storage_months"] = question("storage_months")
    if not cands:
        if gap:
            out["message"] = "No rule for this storage period in the source"
        else:
            out["scope"], out["message"] = "none", NO_LOCAL
        out["asks"] = list(asks.values())
        return out
    out["scope"] = scope
    for c in cands:
        for v in list(c["unknown"]) + c["condition_unknown"]:
            asks.setdefault(v, question(v))
    slots = {}
    for c in cands:
        slots.setdefault(slot(c, t), []).append(c)
    for key, members in slots.items():
        best = max(rank(c, ctx, scope) for c in members)
        top = [c for c in members if rank(c, ctx, scope) == best]
        out["hidden"] += [{"fact": c["row"]["fact"]["id"], "quote": quote_of(c["row"]),
                           "reason": "outranked in its answer slot"}
                          for c in members if c not in top]
        facts = []
        for c in top:
            src_state = (c["row"]["evidence"][0]["source"].get("state_id") if c["row"]["evidence"] else None)
            label = ("From a %s source" % state_names.get(src_state, src_state)
                     if scope == "fallback" and t.subtype in FALLBACK_ONLY else None)
            served, reasons = render(c, ctx, t, scope, label, asks)
            if served is None:
                out["hidden"] += [{"fact": c["row"]["fact"]["id"], "quote": quote_of(c["row"]), "reason": r}
                                  for r in reasons]
            else:
                facts.append(served)
        if facts:
            sigs = {value_signature(c["row"]) for c in top if c["row"]["fact"]["id"] in {x["id"] for x in facts}}
            out["slots"].append({"branch": top[0]["unknown"], "facts": facts, "disagreement": len(sigs) > 1})
    out["slots"].sort(key=lambda s: json.dumps(s["branch"], sort_keys=True))
    out["asks"] = list(asks.values())
    if not out["slots"]:
        out["message"] = "No rule for this storage period in the source" if gap else NO_VERIFIED
    if template_name == "quality_check":
        out["verdict"] = verdict(out)
        # the value a farmer can be asked for; other refractions are listed as not checked
        for parameter, variable in ASKED_PARAMETERS.items():
            if parameter in out["verdict"]["not_checked"] and not any(a["variable"] == variable for a in out["asks"]):
                out["asks"].append(question(variable))
    if template_name == "drying_target" and ctx.purpose == "purpose:grain":
        out["procurement_moisture"] = procurement_moisture(driver, ctx, database)
    return out


def verdict(out: dict) -> dict:
    """Schema v1.5: fail if any served limit fails; pass only when every served limit was checked and passed;
    else unknown, with the limits not checked."""
    every = [(f["check"], f) for s in out["slots"] for f in s["facts"] if f.get("check")]
    checks = [(c, f) for c, f in every if c["parameter"] not in CLASSIFYING]
    failed = [c["parameter"] for c, _ in checks if c["result"] == "fail"]
    unchecked = [c["parameter"] for c, _ in checks if c["result"] == "unknown"]
    result = "fail" if failed else "unknown" if unchecked or not checks else "pass"
    return {"result": result, "failed": failed, "not_checked": unchecked,
            "passed": [c["parameter"] for c, _ in checks if c["result"] == "pass"],
            # grade rules are reported, never counted: L:B below 2.5 makes paddy Common, it does not reject it
            "grade_rules": [{"grades": f["values"].get("grades"), **c} for c, f in every
                            if c["parameter"] in CLASSIFYING]}


def procurement_moisture(driver, ctx, database=None) -> list[dict]:
    """Schema v1.5: drying_target for grain also shows the procurement moisture limit, so "dry to X" and
    "accepted up to Y" appear together (the commodity is paddy unless the farmer said otherwise)."""
    sub = answer(driver, "quality_check", ctx.model_copy(update={"commodity_form": ctx.commodity_form or "paddy"}),
                 database)
    return [f for s in sub["slots"] for f in s["facts"] if f["values"].get("parameter") == "moisture"]
