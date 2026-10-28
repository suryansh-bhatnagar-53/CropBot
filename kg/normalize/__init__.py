"""Normalise and link (step 10): raw facts from the latest run of each unit (prompt version
kg.extract.versions.LATEST) -> facts that validate against the final schema models (kg.schema,
v1.3), or held facts with every blocking reason.

  uv run python -m kg.normalize source:tnau_agriculture_2020

Code only, no model. Crop from the chapter's approved crop_id; regions from the unit with their
origin; purposes from the quote (origin text) merged with the section's (origin section); text
exclusions expanded into IN_REGION edges to the state's other zones (origin text_exclusion).
Units and bases are converted in code (kg.normalize.units) and every conversion is logged.
Names link to concepts (kg.normalize.link); nothing is created. Nothing becomes approved here.
Schema v1.4: durations, week offsets and word ratios are read by code from the fixed word table; the
formulation table sets granules and dusts in a "spray" list (flag operation_from_formulation); an option
list at stated times keeps repeat_offsets; endemic_area values link to a pest or disease. A ControlMeasure
with no target naming no pest anywhere around it is a general practice (flag general_practice, 2026-10-22).
Output: data/normalized/<id>/{facts.jsonl, held.jsonl, report.json},
        data/review/proposed_concepts_<id>.csv (all gitignored).
"""

import copy
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict

from pydantic import ValidationError

from kg.extract import EXTRACTED_DIR, get_unit
from kg.extract.versions import source_version
from kg.registry import ROOT
from kg.schema import FACT
from kg.schema.vocab import (CONDITION_VARIABLES, FORMULATION_OPERATION, FORMULATION_OVERRIDES, Basis,
                             CommodityForm, Grade, LimitType, QualityParameter, Unit, ValueType, WindowFor)

from . import calendar_words
from .link import Linker
from .units import (canon_basis, canon_conc_unit, canon_duration_unit, canon_unit, formulation_code, period_offset,
                    ratio_words, repeat, sample, water_l_per_ha)

NORMALIZED_DIR = ROOT / "data" / "normalized"
PROPOSED_CSV = "proposed_concepts"   # data/review/proposed_concepts_<source slug>.csv (kg.registry.review_csv)
APPLIES_TARGETS = ("nutrient", "fertilizer", "organic_input", "ai", "input")      # input: schema v1.3
PEST_TARGETS = ("pest", "disease", "weed", "disorder")
APPLICABILITY = {"varieties": ("variety_ids", ("variety",), "variety"),
                 "seasons": ("season_ids", ("season", "season_local"), "season"),
                 "systems": ("system_ids", ("system",), "system"), "soils": ("soil_ids", ("soil",), "soil"),
                 "stages": ("stage_ids", ("stage",), "stage")}
SAMPLING = {"/ tiller": Basis.PER_TILLER, "/tiller": Basis.PER_TILLER, "per tiller": Basis.PER_TILLER,
            "/hill": Basis.PER_HILL, "/ hill": Basis.PER_HILL, "per hill": Basis.PER_HILL,
            "/m 2": Basis.PER_M2, "/m2": Basis.PER_M2, "per m2": Basis.PER_M2, "/plant": Basis.PER_PLANT}


def sha(obj, n=20) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:n]


class Fact:
    """One raw fact on its way to the final model: the dict being built, what blocks it, why it
    needs review, and everything linked or converted."""

    def __init__(self, run, unit, raw):
        self.run, self.unit, self.raw, self.index = run, unit, raw["fact"], raw["index"]
        self.quote_check = raw["quote_check"]
        self.subheading = raw.get("subheading") or ""
        self.entry = None                 # the registry entry; run() sets it (QualitySpec takes its authority)
        self.blocks, self.review, self.links, self.conversions = [], [], [], []
        self.inherits_from = set()        # (unit id, raw index) of the facts its amounts came from

    def link_many(self, linker, name, prefixes, name_type) -> list[str]:
        """Applicability: a phrase naming several concepts links to all of them."""
        lks = linker.link_many(name, prefixes)
        if len(lks) == 1:
            i = self.link(linker, name, prefixes, name_type)
            return [i] if i else []
        for lk in lks:
            self.links.append({"name": name, "name_type": name_type, "id": lk.id, "method": lk.method,
                               "review_status": lk.review_status, "reason": None})
            if lk.review_status == "needs_review":
                self.review.append("linked to a needs_review concept or label: %r -> %r" % (name, lk.id))
        return [lk.id for lk in lks]

    def link(self, linker, name, prefixes, name_type, required=True):
        lk = linker.link(name, prefixes)
        self.links.append({"name": name, "name_type": name_type, "id": lk.id, "method": lk.method,
                           "review_status": lk.review_status, "reason": lk.reason})
        if lk.id is None:
            if required:
                self.blocks.append("unlinked %s %r (%s)" % (name_type, name, lk.reason))
            return None
        if lk.review_status == "needs_review":
            self.review.append("linked to a needs_review concept or label: %r -> %r" % (name, lk.id))
        if lk.method == "npk_convention":
            self.review.append("%r read as %r by the N:P2O5:K2O convention" % (name, lk.id))
            self.conversions.append({"fact": self.index, "field": "target", "from": name, "to": lk.id,
                                     "rule": "NPK convention: %s -> %s" % (name, lk.id)})
        return lk.id


def _is_nursery(unit) -> bool:
    return "nursery" in unit["section_path"].lower()


def convert_quantity(f: Fact, q: dict, linker, subtype: str, step_order) -> dict | None:
    target = f.link(linker, q["target"], APPLIES_TARGETS, "applies target")
    out = {"target_id": target, "raw": q["raw"], "formulation": q["formulation"],
           "basis_inferred": q["basis_inferred"], "quantity_ref": q["quantity_ref"]}
    if q["basis_inferred"]:
        f.review.append("basis inferred for %r (%r)" % (q["target"], q["basis"]))
    w = water_l_per_ha(q["water_raw"])
    if w is not None:
        out["water_l_per_ha"] = w
    elif q["water_raw"]:
        f.unmapped_extra.append(q["water_raw"])
    if not strength_ratio_share(f, q, out, step_order):
        return None
    has_amount = any(q[k] is not None for k in ("value", "min", "max"))
    if not has_amount:
        return out                                   # quantity_ref (resolved later), or a strength/ratio/share
    u = canon_unit(q["unit"])
    if u is None:
        f.blocks.append("no canonical unit for %r; raw %r" % (q["unit"], q["raw"]))
        return None
    seed = subtype == "SeedTreatment" or (subtype == "StorageRule" and q["basis"] and "kg" in q["basis"])
    if q["basis"] is None:
        f.blocks.append("no basis printed or given by a rule (a concentration or share); raw %r" % q["raw"])
        return None
    b = canon_basis(q["basis"], nursery=_is_nursery(f.unit), seed_treatment=seed)
    if b is None:
        f.blocks.append("no canonical basis for %r; raw %r" % (q["basis"], q["raw"]))
        return None
    if q["basis_rule"] and q["basis_rule"] not in f.unit["default_scope"]:
        f.blocks.append("basis rule %r is not approved for this unit" % q["basis_rule"])
        return None
    if b.inference:
        f.review.append("basis read from context: %s" % b.rule)
    factor = u.factor * b.factor
    for k in ("value", "min", "max"):
        if q[k] is not None:
            out[k] = round(q[k] * factor, 6)
    out.update(min_inclusive=q["min_inclusive"], max_inclusive=q["max_inclusive"], unit=u.unit.value,
               basis=b.basis.value)
    if b.area_cents is not None:
        out["area_cents"] = b.area_cents
    f.conversions.append({"fact": f.index, "step": step_order, "target": q["target"], "raw": q["raw"],
                          "from": {k: q[k] for k in ("value", "min", "max", "unit", "basis") if q[k] is not None},
                          "to": {k: out[k] for k in ("value", "min", "max", "unit", "basis", "area_cents") if k in out},
                          "rule": "; ".join([u.rule, b.rule])})
    return out


def strength_ratio_share(f: Fact, q: dict, out: dict, step_order) -> bool:
    """Schema v1.3 strength (conc_*), mixing ratio and dose share; False when the fact must be held.
    The ratio's whole is part + rest, computed here (the model gives the printed parts)."""
    if any(q.get(k) is not None for k in ("conc_value", "conc_min", "conc_max")):
        cu = canon_conc_unit(q.get("conc_unit"))
        if cu is None:
            f.blocks.append("no canonical strength unit for %r; raw %r" % (q.get("conc_unit"), q.get("conc_raw")))
            return False
        out.update({k: q[k] for k in ("conc_value", "conc_min", "conc_max") if q.get(k) is not None},
                   conc_unit=cu.value, conc_raw=q["conc_raw"])
        f.conversions.append({"fact": f.index, "step": step_order, "target": q["target"], "raw": q["conc_raw"],
                              "rule": "strength %s -> %s" % (q.get("conc_unit"), cu.value)})
    part, rest = q.get("ratio_part"), q.get("ratio_rest")
    if part is None and q.get("ratio_raw"):          # schema v1.4: a ratio printed only in words
        words = ratio_words(q["ratio_raw"])
        if words is None:
            f.blocks.append("ratio words %r are not in the code word table" % q["ratio_raw"])
            return False
        part, rest, rule = words
        f.conversions.append({"fact": f.index, "step": step_order, "target": q["target"], "raw": q["ratio_raw"],
                              "rule": rule})
    if part is not None:
        out.update(ratio_part=part, ratio_whole=part + rest, ratio_raw=q["ratio_raw"])
        f.conversions.append({"fact": f.index, "step": step_order, "target": q["target"], "raw": q["ratio_raw"],
                              "rule": "ratio %g part with %g parts -> %g in %g" % (part, rest, part, out["ratio_whole"])})
    if q.get("share_pct") is not None:
        out.update(share_pct=q["share_pct"], share_raw=q["share_raw"])
    if q.get("mix_conc_value") is not None:          # schema v1.4: strength in the prepared mix
        mu = canon_conc_unit(q.get("mix_conc_unit"))
        if mu is None:
            f.blocks.append("no canonical mix strength unit for %r; raw %r" % (q.get("mix_conc_unit"),
                                                                            q.get("mix_conc_raw")))
            return False
        out.update(mix_conc_value=q["mix_conc_value"], mix_conc_unit=mu.value, mix_conc_raw=q["mix_conc_raw"])
    if q.get("carrier_raw"):
        out["carrier_raw"] = q["carrier_raw"]
    return True


def convert_repeat(f: Fact, s: dict, step: dict) -> None:
    """repeat_raw -> repeat_count / repeat_interval / repeat_interval_unit by the word table."""
    if not s.get("repeat_raw"):
        return
    parsed = repeat(s["repeat_raw"])
    if parsed is None:
        f.blocks.append("repeat words %r are not in the code word table" % s["repeat_raw"])
        return
    count, interval, unit, rule = parsed
    step.update(repeat_count=count, repeat_interval=interval,
                repeat_interval_unit=unit.value if unit else None, repeat_raw=s["repeat_raw"])
    f.conversions.append({"fact": f.index, "step": s["order"], "raw": s["repeat_raw"], "rule": rule})
    offsets = s.get("repeat_offsets") or []
    if offsets:                                      # schema v1.4: an option list at stated times
        if count != len(offsets) or interval is not None:
            f.blocks.append("repeat words %r do not match the %d stated times %s" % (s["repeat_raw"], len(offsets),
                                                                                  offsets))
            return
        step["repeat_offsets"] = list(offsets)


def convert_timing(f: Fact, s: dict, step: dict) -> None:
    """Schema v1.4: durations (unit read by code), the step's purpose, and a time printed only in words
    ("a week before harvest" -> -1 weeks from the word table)."""
    if s.get("duration_raw"):
        step["duration_raw"] = s["duration_raw"]
        if s.get("duration_min") is not None or s.get("duration_max") is not None:
            du = canon_duration_unit(s.get("duration_unit"))
            if du is None:
                f.blocks.append("no duration unit for %r; raw %r" % (s.get("duration_unit"), s["duration_raw"]))
            else:
                step.update(duration_min=s["duration_min"], duration_max=s["duration_max"],
                            duration_min_inclusive=s["duration_min_inclusive"],
                            duration_max_inclusive=s["duration_max_inclusive"], duration_unit=du.value)
                f.conversions.append({"fact": f.index, "step": s["order"], "raw": s["duration_raw"],
                                      "rule": "duration unit %s -> %s" % (s.get("duration_unit"), du.value)})
    if s.get("purpose_raw"):
        step["purpose_raw"] = s["purpose_raw"]
    if s["offset_min"] is None and s["offset_max"] is None and s["anchor"] and s["timing_raw"]:
        period = period_offset(s["timing_raw"])
        if period is not None:
            n, unit, rule = period
            step.update(offset_min=n, offset_max=n, offset_unit=unit)
            f.conversions.append({"fact": f.index, "step": s["order"], "raw": s["timing_raw"], "rule": rule})


def apply_formulations(f: Fact, d: dict) -> None:
    """Schema v1.4: in a list introduced by "spray", D/DP options become dusting and G/GR/CG options
    application; in a mixed "Dust/ spray" list (no operation, both verbs in the method) every option follows
    its code. Any other printed verb, a carrier, a bait or a seed treatment is never overridden. A changed
    operation flags the fact operation_from_formulation."""
    changed = False
    for s in d["steps"]:
        codes = {formulation_code(a.get("formulation")) for a in s["applies"]}
        if len(codes) != 1 or None in codes or any(a.get("carrier_raw") for a in s["applies"]):
            continue
        code = codes.pop()
        method = (s.get("method") or "").lower()
        mixed = s["operation"] is None and "dust" in method and "spray" in method
        if mixed or (s["operation"] == "spraying" and code in FORMULATION_OVERRIDES):
            new = FORMULATION_OPERATION[code]
            if new != s["operation"]:
                f.conversions.append({"fact": f.index, "step": s["order"], "raw": s["applies"][0].get("formulation"),
                                      "rule": "formulation %s -> %s (printed %s)" % (code, new, s["operation"] or
                                                                                    s.get("method"))})
                s["operation"] = new
                changed = True
    if changed and "operation_from_formulation" not in d["extraction_flags"]:
        d["extraction_flags"].append("operation_from_formulation")
        f.review.append("extraction flags: operation_from_formulation (set by code)")


def general_practice(f: Fact, linker, d: dict) -> None:
    """A ControlMeasure with no printed target (decided 2026-10-22, pending schema v1.5). It is a general
    practice, flagged general_practice by code and reviewed, when nothing around it names a pest: an IPM module
    or a general pest-management list. In a table row, or where the section, the sub-heading or the quote names
    a pest, disease, weed or disorder concept, it still needs its target and holds."""
    if f.raw["table_ref"]:
        f.blocks.append("no target printed in a table row (a pest-specific row needs its target)")
        return
    where = (("section", f.unit["section_path"]), ("sub-heading", f.subheading), ("quote", f.raw["quote"]))
    named = ["%s names %s" % (k, ", ".join(sorted(ids))) for k, t in where
             for ids in [linker.names_in(t, PEST_TARGETS)] if ids]
    if named:
        f.blocks.append("no target printed in a pest-specific place (%s)" % "; ".join(named))
        return
    d["extraction_flags"].append("general_practice")
    f.review.append("general practice: no pest named in its section, sub-heading or quote "
                    "(flag general_practice, set by code)")


def instruction(step: dict, names: dict) -> str:
    """instruction_en, written by code from the step's fields (prompt v2 no longer asks for it)."""
    parts = [(step.get("operation") or "").replace("_", " ").capitalize() or "Do"]
    if step.get("method"):
        parts.append("(%s)" % step["method"])
    for a in step.get("applies", []):
        printed = [x for x in (a.get("raw"), a.get("conc_raw"), a.get("ratio_raw"), a.get("share_raw"),
                               a.get("mix_conc_raw")) if x]
        parts.append("%s %s" % (names.get(a["target_id"], a["target_id"]),
                                ", ".join(dict.fromkeys(printed)) or "(amount stated earlier)"))
        if a.get("carrier_raw"):                     # schema v1.4: what it is applied with or on
            parts.append("on %s" % a["carrier_raw"])
    if step.get("duration_raw"):
        parts.append(step["duration_raw"])
    if step.get("timing_raw"):
        parts.append(step["timing_raw"])
    if step.get("repeat_raw"):
        parts.append(step["repeat_raw"])
    if step.get("purpose_raw"):                      # schema v1.4: the printed purpose stays in the instruction
        parts.append("(%s)" % step["purpose_raw"])
    if step.get("condition_raw"):
        parts.append("if: %s" % step["condition_raw"])
    return " ".join(parts) + "."


def convert_condition(f: Fact, c: dict, linker=None) -> dict | None:
    spec = CONDITION_VARIABLES[c["variable"]]
    out = {k: c[k] for k in ("variable", "op", "value", "value_max", "any_of_group", "raw")}
    out["unit"] = spec.unit.value if spec.unit else None
    if c["unit"] and (canon_unit(c["unit"]) is None or canon_unit(c["unit"]).unit != spec.unit):
        f.blocks.append("condition %s unit %r is not %s" % (c["variable"], c["unit"], spec.unit))
        return None
    if spec.value_type is ValueType.CONCEPT:         # schema v1.4: "in tungro endemic area" -> disease:tungro
        printed = c["value"] if isinstance(c["value"], list) else [c["value"]]
        ids = [f.link(linker, str(v), ("pest", "disease"), "%s value" % c["variable"]) for v in printed]
        if None in ids:
            return None
        out["value"] = ids if isinstance(c["value"], list) else ids[0]
    return out


def build(f: Fact, linker, crop_id, zones_of_state) -> dict | None:
    r, unit = f.raw, f.unit
    f.unmapped_extra = []
    if r["extraction_flags"]:
        f.review.append("extraction flags: %s" % ", ".join(r["extraction_flags"]))
    d = {"subtype": r["subtype"], "summary_en": r["summary_en"], "duration_group": r["duration_group"],
         "extraction_model": f.run["extraction_model"], "crop_ids": [crop_id], "raw": r["raw"],
         "extraction_flags": list(r["extraction_flags"] or [])}                  # kept on the fact (v1.3)
    # regions: the unit's (source or section), or the text's; exclusions expanded by code
    regions = [dict(x) for x in unit["regions"]]
    if r["regions"]:
        # schema v1.6: a printed area naming several zones ("Irrigated Hills") links to all of them
        ids = [i for n in r["regions"] for i in f.link_many(linker, n, ("zone", "district", "state"), "region")]
        regions = [{"id": i, "origin": "text"} for i in dict.fromkeys(ids) if i]
    if r["excluded_regions"]:
        excluded = [(f.link(linker, x["name"], ("zone", "district"), "excluded region"), x["raw"])
                    for x in r["excluded_regions"]]
        d["excluded_regions"] = [{"id": i, "raw": raw} for i, raw in excluded if i]
        gone = {i for i, _ in excluded}
        state = next((x["id"] for x in unit["regions"] if x["id"].startswith("state:")), None)
        regions = [{"id": z, "origin": "text_exclusion"} for z in zones_of_state.get(state, []) if z not in gone]
        if not regions:
            f.blocks.append("exclusion leaves no zone of %s" % state)
        f.review.append("text exclusion: %s" % [x["raw"] for x in r["excluded_regions"]])
    d["regions"] = regions
    # applicability: an unlinked name would widen the fact's scope, so it holds the fact
    for field, (target, prefixes, name_type) in APPLICABILITY.items():
        if field in ("soils", "systems", "seasons"):
            d[target] = sorted({i for n in r[field] for i in f.link_many(linker, n, prefixes, name_type)})
        else:
            d[target] = [i for i in (f.link(linker, n, prefixes, name_type) for n in r[field]) if i]
    purposes = [(f.link(linker, n, ("purpose",), "purpose"), "text") for n in r["purposes"]]
    purposes += [(p["id"], "section") for p in unit.get("purposes", [])]
    origins = defaultdict(list)
    for pid, origin in purposes:
        if pid and origin not in origins[pid]:
            origins[pid].append(origin)
    d["purpose_ids"] = list(origins)
    f.purpose_origins = dict(origins)
    # subtype fields
    names = {}
    st = r["subtype"]
    if st == "VarietyRecommendation":
        # schema v1.6: a printed name group ("Pant Dhan- 10,12, 19, 24 & 26") is a label of every variety it names
        ids = [i for n in r["recommends"] for i in f.link_many(linker, n, ("variety",), "variety")]
        d["recommends"] = list(dict.fromkeys(ids))
        d["note"] = r["note"]
    elif st == "SowingWindow":
        sowing_window(f, d)
    elif st in ("PestThreshold",):
        d["pest_ids"] = [f.link(linker, n, ("pest", "disease"), "pest") for n in r["pests"]]
        d["clauses"] = []
        for c in r["clauses"]:
            unit_ = Unit.PCT if (c["unit"] or "").strip() == "%" else (Unit.COUNT if not c["unit"] else None)
            if unit_ is None:
                f.blocks.append("threshold unit %r has no canonical form" % c["unit"])
            sampling, sampled = None, None
            if c["sampling_unit"]:
                sampling = SAMPLING.get(c["sampling_unit"].strip())
                sampled = None if sampling else sample(c["sampling_unit"])      # v1.3: "/25 net sweeps"
                if sampling is None and sampled is None:
                    f.blocks.append("threshold sampling unit %r is neither a schema basis nor a sample size"
                                    % c["sampling_unit"])
                elif sampled:
                    f.conversions.append({"fact": f.index, "raw": c["sampling_unit"],
                                          "rule": "sample %r -> %d %s" % (c["sampling_unit"], *sampled)})
            if c["stage"]:
                sid = f.link(linker, c["stage"], ("stage",), "clause stage", required=False)
                if sid is None:
                    f.review.append("clause stage %r not linked; kept in raw" % c["stage"])
            conds = [convert_condition(f, x, linker) for x in c["conditions"]]
            d["clauses"].append({"observation": c["observation"], "value": c["value"],
                                 "unit": unit_.value if unit_ else None,
                                 "sampling_unit": sampling.value if sampling else None,
                                 "sampling_count": sampled[0] if sampled else None,
                                 "sampling_object": sampled[1].value if sampled else None,
                                 "raw": c["raw"], "conditions": [x for x in conds if x]})
    elif st == "ControlMeasure":
        d["control_class"] = r["control_class"]
        d["target_ids"] = [f.link(linker, n, PEST_TARGETS, "target") for n in r["targets"]]
    elif st == "StorageRule":
        d["target_ids"] = [f.link(linker, n, ("pest",), "storage pest") for n in r["targets"]]
    elif st == "Caution":
        d["kind"], d["text_en"] = r["kind"], r["text_en"]
        d["concerns"] = [f.link(linker, n, ("ai", "ai_group"), "active ingredient") for n in r["concerns"]]
        d["about_ids"] = [f.link(linker, n, ("pest", "disease"), "caution pest") for n in r.get("about") or []]
    elif st == "DoseFormula":
        f.blocks.append("DoseFormula coefficients are not parsed yet")
    elif st == "QualitySpec":
        quality_spec(f, d)
    copy_fields = {"VarietyRecommendation": (), "SeedRate": ("method",),
                   "Spacing": tuple(k for k in r if k.startswith(("row_cm", "plant_cm", "hills_per_m2",
                                                                   "seedlings_per_hill_"))),
                   "NutrientDose": ("dose_basis",), "IrrigationRule": ("depth_cm", "criterion"),
                   "WeatherRule": ("operation", "advice"),
                   "HarvestRule": tuple(k for k in r if k.startswith(("harvest_", "threshing_")) or k == "maturity_signs"),
                   "DryingSpec": tuple(k for k in r if k.startswith(("target_moisture", "storage_months"))
                                       ) + ("storage_term_raw", "method"),
                   "StorageRule": tuple(k for k in r if k.startswith(("storage_months", "min_moisture", "max_moisture"))
                                        ) + ("structure",)}
    for k in copy_fields.get(st, ()):
        d[k] = r[k]
    if st == "Spacing" and "seedlings_per_hill" in r:
        # a v1/v2 raw fact gives one printed number; schema v1.3 stores it as equal bounds
        if r["seedlings_per_hill"] is not None:
            d["seedlings_per_hill_min"] = d["seedlings_per_hill_max"] = r["seedlings_per_hill"]
        d["raw"] = {("seedlings_per_hill_min" if k == "seedlings_per_hill" else k): v for k, v in d["raw"].items()}
        if "seedlings_per_hill_min" in d["raw"]:
            d["raw"]["seedlings_per_hill_max"] = d["raw"]["seedlings_per_hill_min"]
    # steps
    d["steps"] = []
    for s in r["steps"]:
        step = {k: s[k] for k in ("order", "alt_group", "alt_option", "alt_priority", "condition_raw", "operation",
                                  "method", "anchor", "offset_min", "offset_max", "offset_min_inclusive",
                                  "offset_max_inclusive", "offset_unit", "month_start", "month_end", "timing_raw")}
        if s["stage"]:
            sid = f.link(linker, s["stage"], ("stage",), "step stage", required=False)
            step["stage_id"] = sid
            if sid is None:
                f.review.append("step stage %r not linked; kept in timing_raw" % s["stage"])
        convert_timing(f, s, step)
        convert_repeat(f, s, step)
        step["applies"] = []
        for q in s["applies"]:
            a = convert_quantity(f, q, linker, st, s["order"])
            if a is not None:
                step["applies"].append(a)
                names[a["target_id"]] = q["target"]
        step["conditions"] = [x for x in (convert_condition(f, c, linker) for c in s["conditions"]) if x]
        d["steps"].append(step)
    apply_formulations(f, d)
    for s in d["steps"]:
        if s["operation"] is None:
            f.blocks.append("step %d has no operation; method %r" % (s["order"], s["method"] or ""))
    if st == "ControlMeasure" and not r["targets"]:
        general_practice(f, linker, d)
    d["conditions"] = [x for x in (convert_condition(f, c, linker) for c in r["conditions"]) if x]
    d["unmapped"] = r["unmapped"] + f.unmapped_extra
    f.names = names
    return d


def transcription_of(unit: dict, refs: list[str]) -> tuple[str, str] | None:
    """(file, body hash) of the approved transcription a quote was found in, from its segment refs."""
    from kg.transcribe import read
    tags = {m.group(1) for ref in refs for m in re.finditer(r"tr:(p\d{3,4})#/", ref)}
    files = {i["transcription"] for i in unit["items"] if i.get("transcription")
             and any(i["ref"].startswith("tr:%s#" % t) for t in tags)}
    if not files:
        return None
    if len(files) > 1:
        raise ValueError("one quote in two transcriptions: %s" % sorted(files))
    path = files.pop()
    return path, read(ROOT / path).header.body_sha256


def evidence(f: Fact, entry, ocr_pages) -> dict:
    qc, r, unit = f.quote_check, f.raw, f.unit
    page = min(qc["pdf_pages"]) if qc["pdf_pages"] else unit["pdf_pages"][0]
    method = "table_parse" if r["table_ref"] else ("ocr" if page in ocr_pages else "native_text")
    span = {"id": "span:" + sha([unit["id"], r["quote"]], 16), "source_id": entry.id, "pdf_page": page,
            "printed_page": entry.printed_page(page), "section_path": unit["section_path"], "quote": r["quote"],
            "table_ref": r["table_ref"], "table_row": r["table_row"], "table_col": r["table_col"],
            "extraction_method": method}
    found = transcription_of(unit, qc.get("refs") or [])
    if found:                    # v1.5 candidate: the text comes from an approved page transcription
        span.update(extraction_method="manual_transcription", transcription=found[0],
                    transcription_sha256=found[1])
    return span


def _conditions(d: dict) -> list:
    """Every condition of the fact (on the fact, its steps and its clauses) as (variable, op, raw)."""
    found = list(d.get("conditions") or [])
    found += [c for s in d.get("steps") or [] for c in s.get("conditions") or []]
    found += [c for cl in d.get("clauses") or [] for c in cl.get("conditions") or []]
    return sorted({(c["variable"], c["op"], c["raw"]) for c in found})


QUALITY_IDENTITY = ("commodity_form", "grades", "parameter", "limit_type", "part_of")
VALUE_CUT = re.compile(r"value\s*cut", re.I)


def quality_spec(f: Fact, d: dict) -> None:
    """Schema v1.5 QualitySpec. Authority and season from the registry, never the model; vocabulary values
    checked; grades from the quote (origin text) or an approved section scope (origin section, its heading
    as evidence). A value-cut rule in unmapped holds the fact (v1.5: not modelled yet)."""
    r, e = f.raw, f.entry
    if f.run["prompt_version"] in ("v1", "v2", "v3", "v4"):
        f.blocks.append("QualitySpec needs prompt v5 (schema v1.5)")
        return
    d.update(authority=e.publisher, season_label=e.season_label, marketing_season=e.marketing_season,
             season_start_year=e.edition_year if e.season_label else None)
    for field, enum in (("commodity_form", CommodityForm), ("parameter", QualityParameter),
                        ("limit_type", LimitType), ("part_of", QualityParameter)):
        value = r.get(field)
        if value is None and field == "part_of":
            d[field] = None
        elif value not in {x.value for x in enum}:
            f.blocks.append("%s %r is not in the fixed list" % (field, value))
        else:
            d[field] = value
    if not r.get("parameter_raw"):
        f.blocks.append("parameter_raw (the refraction as printed) is missing")
    d["parameter_raw"] = r.get("parameter_raw")
    d["limit_value"], d["limit_inclusive"] = r["limit_value"], r["limit_inclusive"]
    unit = (r.get("unit") or "").strip()
    d["unit"] = Unit.PCT.value if unit == "%" else None
    if unit and unit != "%":
        f.blocks.append("QualitySpec unit %r is not a percentage" % unit)
    if r.get("grades"):
        bad = [g for g in r["grades"] if g not in {x.value for x in Grade}]
        if bad:
            f.blocks.append("grades %s are not in the fixed list" % bad)
        d.update(grades=list(r["grades"]), grades_origin="text", grades_evidence=None)
    elif f.unit.get("grades"):
        d.update(grades=[g["id"] for g in f.unit["grades"]], grades_origin="section",
                 grades_evidence=f.unit["grades"][0]["evidence"])
    else:
        f.blocks.append("no grade: the quote names none and no approved section scope gives one")
    cuts = [u for u in r["unmapped"] if VALUE_CUT.search(u)]
    if cuts:
        f.blocks.append("value-cut rule held until modelled (schema v1.5): %s" % cuts)


def sowing_window(f: Fact, d: dict) -> None:
    """Schema v1.6. `window_for` from the fixed list (a v1-v5 answer has none: "sowing"). Prompt v6 gives the
    window's calendar words: the program reads the dates from the fixed word table (kg.normalize.calendar_words),
    logs each reading, keeps the words in raw and sends the fact to review. A v1-v5 answer gives the numbers."""
    r = f.raw
    d["window_for"] = r.get("window_for") or WindowFor.SOWING.value
    if d["window_for"] not in {x.value for x in WindowFor}:
        f.blocks.append("window_for %r is not in the fixed list" % d["window_for"])
    if not r.get("start_raw"):
        d.update({k: r[k] for k in ("start_month", "start_day", "end_month", "end_day")})
        return
    got = calendar_words.window(r["start_raw"], r.get("end_raw"))
    if isinstance(got, str):
        f.blocks.append(got)
        return
    dates, readings = got
    d.update(dates)
    end = r.get("end_raw") or r["start_raw"]
    d["raw"] = {**d["raw"], "start_month": r["start_raw"], "start_day": r["start_raw"], "end_month": end,
                "end_day": end}
    for x in readings:
        f.conversions.append({"fact": f.index, "field": x["bound"], "raw": x["raw"], "rule": x["rule"],
                              "to": calendar_words.date_text(x["month"], x["day"])})
    f.review.append("calendar words read by code (schema v1.6): %s" % "; ".join(
        "%s %r -> %s (%s)" % (x["bound"], x["raw"], calendar_words.date_text(x["month"], x["day"]), x["rule"])
        for x in readings))


def fact_key_parts(f: Fact, d: dict) -> dict:
    """source + section path + subtype + applicability + identity + step slots; values excluded.
    Identity includes the fact's conditions (variable, op, raw) and a DryingSpec's storage term.
    A step outside an alternative group is the slot [order, operation, method, anchor, targets]; an
    alternative group is one slot [order, alt_group, "options"], so adding, removing or renumbering an
    option changes the id and value_key, never the fact_key (schema v1.4). The quote's location (first
    segment ref) separates facts the rest cannot tell apart."""
    slots = []
    for s in d["steps"]:
        if s["alt_group"] is None:
            slots.append([s["order"], s["operation"], s.get("method"), s.get("anchor"),
                          sorted(a["target_id"] or "" for a in s["applies"])])
        elif [s["order"], s["alt_group"], "options"] not in slots:
            slots.append([s["order"], s["alt_group"], "options"])
    return {"source": f.unit["source_id"], "section": f.unit["section_path"], "subtype": d["subtype"],
            "applicability": {k: sorted(d.get(k) or []) for k in ("crop_ids", "variety_ids", "season_ids", "system_ids",
                                                                   "soil_ids", "purpose_ids", "stage_ids")}
                             | {"regions": sorted(x["id"] for x in d["regions"]), "duration_group": d["duration_group"]},
            "identity": {k: d.get(k) for k in ("pest_ids", "target_ids", "recommends", "kind", "concerns",
                                               "control_class", "dose_basis", "storage_term_raw", "about_ids")}
                        | {"conditions": _conditions(d)}
                        # schema v1.5; only on QualitySpec, so no other fact's key changes
                        | ({k: d.get(k) for k in QUALITY_IDENTITY} if d["subtype"] == "QualitySpec" else {})
                        # schema v1.6; only on SowingWindow: a zone's nursery and transplanting windows don't collide
                        | ({"window_for": d.get("window_for")} if d["subtype"] == "SowingWindow" else {}),
            "steps": slots,
            "passage": (f.quote_check["refs"] or [None])[0]}


def resolve_quantity_refs(built: list[tuple["Fact", dict]]) -> None:
    """quantity_ref "previous": copy the amount from the one earlier fact in the unit that applies
    the same target with an amount; none or several -> hold."""
    for i, (f, d) in enumerate(built):
        if d is None:
            continue
        for s in d["steps"]:
            for a in s["applies"]:
                if a.get("quantity_ref") != "previous" or a.get("value") is not None or a.get("min") is not None:
                    continue
                cands = [(g.index, b) for g, e in built[:i] if e is not None and g.unit["id"] == f.unit["id"]
                         for t in e["steps"] for b in t["applies"]
                         if b["target_id"] == a["target_id"] and any(b.get(k) is not None for k in ("value", "min", "max"))]
                facts = {ix for ix, _ in cands}
                if len(facts) != 1:
                    f.blocks.append("quantity_ref for %s: %d earlier facts state an amount" % (a["target_id"], len(facts)))
                    continue
                _, b = cands[0]
                for k in ("value", "min", "max", "min_inclusive", "max_inclusive", "unit", "basis", "area_cents"):
                    if k in b:
                        a[k] = b[k]
                a["inherited"], a["raw"] = True, b["raw"]
                f.inherits_from.add((f.unit["id"], cands[0][0]))
                f.review.append("amount for %r inherited from fact %d" % (a["target_id"], cands[0][0]))
                f.conversions.append({"fact": f.index, "target": a["target_id"], "from": "quantity_ref previous",
                                      "to": {k: a[k] for k in ("value", "unit", "basis", "area_cents") if k in a},
                                      "rule": "inherited from fact %d of the same unit" % cands[0][0]})


def latest_runs(entry):
    d = EXTRACTED_DIR / entry.id.split(":", 1)[1] / source_version(entry)
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json")) if p.name != "report.json"]


def run(entry) -> dict:
    linker = Linker.for_source(entry)
    zones_of_state = _zones_of_state()
    ocr = set(json.loads((ROOT / "data" / "docling" / entry.id.split(":", 1)[1] / "meta.json").read_text(
        encoding="utf-8")).get("ocr", {}).get("pages_with_ocr_text", []))
    chapter_crop = {c.path_label(): (c.crop_id if c.status == "approved" else None) for c in entry.chapters}
    built = []
    for rec in latest_runs(entry):
        if not rec["ok"]:
            raise SystemExit("run %s for %s did not pass step 9; not normalised" % (rec["cache_key"][:8], rec["unit_id"]))
        unit = get_unit(entry, rec["unit_id"])
        for raw in rec["facts"]:
            f = Fact(rec, unit, raw)
            f.entry = entry
            crop = chapter_crop.get(unit["chapter"]["title"])
            if crop is None:
                f.blocks.append("chapter %r is not approved: no crop_id" % unit["chapter"]["title"])
            d = build(f, linker, crop, zones_of_state)
            built.append((f, d))
    resolve_quantity_refs(built)
    facts, held = [], []
    keys = Counter()
    staged = []
    for f, d in built:
        d["evidence"] = [evidence(f, entry, ocr)]
        parts = fact_key_parts(f, d)
        d["fact_key"] = "fk:" + sha(parts, 24)
        if not f.blocks:                           # held facts have unlinked IDs; their keys mean nothing
            keys[(f.unit["id"], d["fact_key"])] += 1
        staged.append((f, d, parts))
    validated = {}
    for f, d, parts in staged:
        if not f.blocks and keys[(f.unit["id"], d["fact_key"])] > 1:
            f.blocks.append("fact_key collides with another fact of the unit")
        for s in d["steps"]:
            s["instruction_en"] = instruction(s, f.names)
        d["status"] = "needs_review" if f.review else "extracted"
        values = {k: v for k, v in d.items() if k not in ("id", "fact_key", "summary_en", "extraction_model")}
        d["id"] = "rec:" + sha([d["fact_key"], values], 16)
        if not f.blocks:
            try:
                validated[id(f)] = FACT.validate_python(copy.deepcopy(d)).model_dump(mode="json")
            except ValidationError as e:
                f.blocks += ["schema: %s: %s" % (".".join(map(str, x["loc"])), x["msg"]) for x in e.errors()]
    hold_inheritors([f for f, _, _ in staged])
    for f, d, parts in staged:
        common = {"unit_id": f.unit["id"], "raw_index": f.index, "subtype": d["subtype"],
                  "run": {"prompt_version": f.run["prompt_version"], "cache_key": f.run["cache_key"]},
                  "links": f.links, "conversions": f.conversions, "review_reasons": f.review}
        if f.blocks:
            held.append({**common, "quote": f.raw["quote"], "reasons": f.blocks})
        else:
            fact = validated[id(f)]
            facts.append({**common, "fact": fact, "status": fact["status"], "purpose_origins": f.purpose_origins,
                          "fact_key_parts": parts})
    return {"facts": facts, "held": held, "built": built}


def hold_inheritors(facts: list[Fact]) -> None:
    """A fact that inherits an amount from a held fact is held too, until its source validates;
    repeated until nothing changes, so chains are held as well."""
    changed = True
    while changed:
        changed = False
        held = {(f.unit["id"], f.index) for f in facts if f.blocks}
        for f in facts:
            sources = sorted(f.inherits_from & held)
            if sources and not f.blocks:
                f.blocks.append("inherits its amount from held fact %s" % ", ".join(str(i) for _, i in sources))
                changed = True


def _zones_of_state() -> dict[str, list[str]]:
    out = defaultdict(list)
    with open(ROOT / "concepts" / "zones.csv", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("state_id"):
                out[row["state_id"]].append(row["id"])
    return dict(out)
