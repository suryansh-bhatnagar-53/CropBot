"""Claims for Jev, built by code from a fact's stored fields; no model writes or rewrites them.

One yes/no claim per step and value ("Does the passage state that DAP is applied at 40 kg per 20 cents
of nursery before the last puddling?"), per threshold clause, per moisture / months / depth field and
per ingredient a Caution concerns. A fact none of these apply to gets no claim and needs human review.

Wording follows the book: names as printed (from the step 9 fact, `printed_names`), a condition's own
raw text, bound words ("at most", "below", "more than") only when the printed raw has one, and a
fallback's condition kept with the whole fallback ("the alternative to DAP, if not readily available,
is urea 16 kg and super phosphate 120 kg per 20 cents of nursery").
"""

import copy
import hashlib
import re
from difflib import SequenceMatcher

from kg.normalize.calendar_words import MONTH_END, MONTH_TEXT
from kg.schema.vocab import COUNT_WORDS, INTERVAL_WORDS

BASIS = {"per_ha": "per hectare", "per_kg_seed": "per kg of seed", "per_l_water": "per litre of water",
         "per_m2": "per square metre", "per_hill": "per hill", "per_tiller": "per tiller", "per_plant": "per plant",
         "absolute": ""}
UNIT = {"kg": "kg", "g": "g", "t": "tonnes", "l": "litres", "ml": "ml", "pct": "%", "count": "", "cm": "cm",
        "m": "m", "days": "days", "months": "months"}
ANCHOR = {"sowing": "sowing", "transplanting": "transplanting", "PI": "panicle initiation", "flowering": "flowering",
          "harvest": "harvest", "last_puddling": "the last puddling", "pulling_out": "pulling out the seedlings",
          "storage_start": "the start of storage"}
OPS = {"<": "fewer than", "<=": "at most", ">": "more than", ">=": "at least", "==": "exactly", "!=": "other than"}
NO_CLAIM = "human review required: no code-built claim"
# a printed bound word for an upper or lower bound; which phrase is used comes from the inclusive flag
BOUND_WORDS = {"max": re.compile(r"less than|below|under|at most|not (?:more than|exceed)|maximum|max\b|up to|<|≤", re.I),
               "min": re.compile(r"more than|above|over|exceed|at least|minimum|min\b|>|≥", re.I)}
BOUND_PHRASE = {("max", True): "at most", ("max", False): "below", ("min", True): "at least", ("min", False): "more than"}


def printed_names(raw: dict, fact: dict) -> dict:
    """The names as printed in the step 9 fact, in the positions of the normalised fact's ids
    (step 10 links them one to one). Raises if they don't line up."""
    out = {"applies": [[q["target"] for q in s["applies"]] for s in raw.get("steps") or []],
           "pest_ids": list(raw.get("pests") or []), "target_ids": list(raw.get("targets") or []),
           "concerns": list(raw.get("concerns") or []), "about_ids": list(raw.get("about") or [])}
    shape = [len(s["applies"]) for s in fact.get("steps") or []]
    if [len(a) for a in out["applies"]] != shape or any(
            len(out[k]) != len(fact.get(k) or []) for k in ("pest_ids", "target_ids", "concerns", "about_ids")):
        raise ValueError("printed names don't line up with %s" % fact["id"])
    # schema v1.6: places and variety groups as printed; one printed group may name several linked ids
    out["regions"], out["recommends"] = list(raw.get("regions") or []), list(raw.get("recommends") or [])
    return out


def _names(fact: dict, key: str, names: dict, printed: dict | None) -> list[str]:
    if printed is not None:
        return printed.get(key, [])
    return [names.get(i, i) for i in fact.get(key) or []]


def bounded(fact: dict, field: str, side: str, value: float) -> str:
    """"below 8", "at most 8" or "8": a bound word only when the printed raw has one."""
    raw = (fact.get("raw") or {}).get(field) or ""
    if not BOUND_WORDS[side].search(raw):
        return num(value)
    return "%s %s" % (BOUND_PHRASE[side, fact.get(field + "_inclusive", True) is not False], num(value))


def num(v: float) -> str:
    return ("%.4f" % v).rstrip("0").rstrip(".")


def span(lo, hi) -> str:
    return num(lo) if lo == hi or hi is None else "%s to %s" % (num(lo), num(hi))


def amount(a: dict) -> str:
    """The quantity in the source's own terms: per_cent_nursery is rebuilt as value x area_cents."""
    qty, per = _amount(a)
    return (qty + " " + per).strip()


def _amount(a: dict) -> tuple[str, str]:
    """("40 kg", "per 20 cents of nursery"); with no amount, the mixing ratio or dose share
    ("1 part with 49 parts", "50% of the dose"), or ("", "") when only a strength is given."""
    lo = a.get("value") if a.get("value") is not None else a.get("min")
    hi = a.get("value") if a.get("value") is not None else a.get("max")
    if lo is None and hi is None:
        if a.get("ratio_part") is not None:
            return "%s part with %s parts" % (num(a["ratio_part"]), num(a["ratio_whole"] - a["ratio_part"])), ""
        if a.get("share_pct") is not None:
            return "%s%% of the dose" % num(a["share_pct"]), ""
        return "", ""
    if a["basis"] == "per_cent_nursery":
        area = a["area_cents"]
        lo, hi = lo * area, hi * area
        per = "per cent of nursery" if area == 1 else "per %s cents of nursery" % num(area)
    else:
        per = BASIS[a["basis"]]
    unit = UNIT[a["unit"]]
    if unit == "tonnes" and lo == hi == 1:
        unit = "tonne"
    return span(lo, hi) + ("%s" % unit if unit == "%" else (" " + unit if unit else "")), per


def _unit(unit: str, a: float, b: float | None = None) -> str:
    """"1 week", "2 weeks": a singular unit only for exactly one."""
    return unit[:-1] if a == 1 and (b is None or b == 1) and unit.endswith("s") else unit


def timing(s: dict) -> str:
    if s.get("repeat_offsets"):                      # schema v1.4: " at 15 and 30 days after transplanting"
        offs = s["repeat_offsets"]
        side = "before" if offs[0] < 0 else "after"
        anchor = ANCHOR.get(s.get("anchor"), s.get("anchor"))
        return " at %s %s %s %s" % (" and ".join(num(abs(x)) for x in offs), s.get("offset_unit") or "days", side,
                                     anchor)
    if s.get("offset_min") is not None or s.get("offset_max") is not None:
        lo, hi = s.get("offset_min"), s.get("offset_max")
        lo = lo if lo is not None else hi
        unit = s.get("offset_unit") or "days"
        anchor = ANCHOR.get(s.get("anchor"), s.get("anchor"))
        if (hi is None or hi == lo) and lo == 0:
            return " at %s" % anchor
        if hi is None:
            return " from %s %s after %s onwards" % (num(abs(lo)), _unit(unit, abs(lo)), anchor)
        side = "before" if lo < 0 else "after"
        a, b = sorted((abs(lo), abs(hi)))
        return " %s %s %s" % (span(a, b), _unit(unit, a, b), side + " " + anchor)
    if s.get("timing_raw"):
        return " " + s["timing_raw"]
    return ""


def duration(s: dict) -> str:
    """Schema v1.4: " for 12 to 16 hours", or the printed words when there is no number (" overnight")."""
    if s.get("duration_min") is not None or s.get("duration_max") is not None:
        lo = s["duration_min"] if s.get("duration_min") is not None else s["duration_max"]
        hi = s["duration_max"] if s.get("duration_max") is not None else lo
        return " for %s %s" % (span(lo, hi), _unit(s["duration_unit"], lo, hi))
    return " " + s["duration_raw"] if s.get("duration_raw") else ""


INTERVAL_TEXT = {(v[0], v[1]): w for w, v in INTERVAL_WORDS.items()}
COUNT_TEXT = {n: w for w, n in COUNT_WORDS.items()}
CONC_SIGN = {"pct": "%", "normal": " N", "micromolar": " µM"}
SAMPLE_TEXT = {"net_sweep": "net sweeps", "earhead": "earheads", "pass": "passes"}


def repeats(s: dict) -> str:
    """" thrice at weekly interval", in the word table's words (schema v1.3 repeat_* fields). With stated
    times (v1.4 repeat_offsets) the count is the list of times, already in timing()."""
    out = ""
    if s.get("repeat_offsets"):
        return out
    if s.get("repeat_count") is not None:
        out += " " + COUNT_TEXT.get(s["repeat_count"], "%d times" % s["repeat_count"])
    if s.get("repeat_interval") is not None:
        word = INTERVAL_TEXT.get((s["repeat_interval"], s.get("repeat_interval_unit")))
        out += " at %s interval" % word if word else " every %s %s" % (num(s["repeat_interval"]),
                                                                        s.get("repeat_interval_unit"))
    return out


def strength(a: dict) -> str:
    """"5%", "0.1 N", "80 µM" from a quantity's conc_* fields, or ""."""
    lo = a.get("conc_value") if a.get("conc_value") is not None else a.get("conc_min")
    hi = a.get("conc_value") if a.get("conc_value") is not None else a.get("conc_max")
    if lo is None:
        return ""
    return span(lo, hi) + CONC_SIGN.get(a.get("conc_unit"), "")


def lead(fact: dict, names: dict) -> str:
    """", for short duration varieties grown for seed on clay soils, " or ""."""
    subject = "%s duration varieties" % fact["duration_group"] if fact.get("duration_group") else None
    mods = []
    if fact.get("variety_ids"):
        subject = "the variety " + " or ".join(names.get(i, i) for i in fact["variety_ids"])
    if fact.get("purpose_ids"):
        mods.append("grown for " + " or ".join(names.get(i, i).lower() for i in fact["purpose_ids"]))
    if fact.get("soil_ids"):
        mods.append("on " + " or ".join(names.get(i, i).lower() for i in fact["soil_ids"]) + " soils")
    if fact.get("system_ids"):
        mods.append("under " + " or ".join(names.get(i, i).lower() for i in fact["system_ids"]))
    if not subject and not mods:
        return ""
    return ", for %s, " % " ".join([subject or "the crop"] + mods)


def conditions(cs: list[dict] | None) -> str:
    """" in the absence of predatory spider": a condition's raw text when it has one, else the variable."""
    return "".join(" " + c["raw"] if c.get("raw") else " when " + condition(c) for c in cs or [])


def condition(c: dict) -> str:
    what = "the " + c["variable"].replace("_", " ")
    if c["op"] == "between":
        return "%s is between %s and %s" % (what, num(c["value"]), num(c["value_max"]))
    value = c["value"] if not isinstance(c["value"], list) else ", ".join(map(str, c["value"]))
    return "%s is %s %s" % (what, OPS.get(c["op"], c["op"]), num(value) if isinstance(value, float) else value)


def _q(text: str) -> str:
    """"that, for x, y" when there is a lead-in, else "that y"."""
    return "Does the passage state that%s?" % (text if text.startswith(",") else " " + text)


def _name(a: dict, names: dict, printed: str | None = None) -> str:
    """Target, strength and formulation: "Acephate 75 % SP", "KCl 1%", "Azospirillum (Carrier based)"."""
    name, form = printed or names.get(a["target_id"], a["target_id"]), a.get("formulation")
    if strength(a):
        name = "%s %s" % (name, strength(a))
    if not form:
        return name
    return "%s %s" % (name, form) if form[0].isdigit() else "%s (%s)" % (name, form)


def _at(a: dict) -> str:
    """" at 40 kg per hectare", or "" when only a strength is given; v1.4 adds the strength in the prepared
    mix (" at 0.005% in the prepared mix") and the carrier (" with chopped paddy straw")."""
    dose = amount(a)
    out = " at %s" % dose if dose else ""
    if a.get("mix_conc_value") is not None:
        out += " at %s%s in the prepared mix" % (num(a["mix_conc_value"]), CONC_SIGN.get(a.get("mix_conc_unit"), ""))
    if a.get("carrier_raw"):
        out += " with %s" % a["carrier_raw"]
    return out


def _together(applies: list[dict], step_names: list[str]) -> str:
    """"urea 16 kg and super phosphate 120 kg per 20 cents of nursery" (one basis shared, else each its own)."""
    parts = [(n, *_amount(a)) for n, a in zip(step_names, applies)]
    if len({per for _, _, per in parts}) == 1:
        return (" and ".join(("%s %s" % (n, q)).strip() for n, q, _ in parts) + " " + parts[0][2]).strip()
    return " and ".join(("%s %s %s" % (n, q, per)).strip() for n, q, per in parts)


def step_claims(fact: dict, names: dict, printed: dict | None = None) -> list[str]:
    out = []
    targets = " or ".join(_names(fact, "target_ids", names, printed))
    against = " against %s" % targets if targets and fact["subtype"] == "ControlMeasure" else ""
    ld = lead(fact, names)
    for si, s in enumerate(fact["steps"]):
        step_names = [_name(a, names, printed["applies"][si][ai] if printed else None)
                      for ai, a in enumerate(s["applies"])]
        cond = " (%s)" % s["condition_raw"] if s.get("condition_raw") else ""
        conds = conditions((fact.get("conditions") or []) + (s.get("conditions") or []))
        when = timing(s) + repeats(s) + duration(s)
        primary = [t for t in fact["steps"] if s.get("alt_group") is not None and t.get("alt_group") == s["alt_group"]
                   and (t.get("alt_option") or 0) < (s.get("alt_option") or 0)]
        if s["applies"] and s.get("condition_raw") and (primary or len(s["applies"]) > 1):
            # the condition belongs to the whole fallback (or the whole step), never to one product
            if primary:
                first = min(primary, key=lambda t: t.get("alt_option") or 0)
                fi = fact["steps"].index(first)
                instead = " and ".join(_name(a, names, printed["applies"][fi][ai] if printed else None)
                                       for ai, a in enumerate(first["applies"])) or (first.get("method") or "")
                out.append(_q("%sthe alternative to %s, %s, is %s%s%s%s" % (
                    ld, instead, s["condition_raw"], _together(s["applies"], step_names), against, when, conds)))
            else:
                out.append(_q("%s%s, %s %s applied%s%s%s" % (
                    ld.rstrip(", ") + ", " if ld else ", ", s["condition_raw"], _together(s["applies"], step_names),
                    "is" if len(s["applies"]) == 1 else "are", against, when, conds)))
            continue
        for a, name in zip(s["applies"], step_names):
            out.append(_q("%s%s is applied%s%s%s%s%s" % (ld, name, against, _at(a), when, conds, cond)))
        if not s["applies"] and (timing(s) or duration(s)) and fact.get("depth_cm") is None:
            op = (s.get("operation") or "").replace("_", " ")
            method = " (%s)" % s["method"] if s.get("method") else ""
            out.append(_q("%s%s%s is done%s%s%s" % (lead(fact, names), op, method, when, conds, cond)))
    return out


def fallback_claims(fact: dict, names: dict) -> list[str]:
    """A fact whose only content is untimed steps: one claim per step from its operation and method."""
    out = []
    for s in fact["steps"]:
        if s.get("method"):
            op = (s.get("operation") or "").replace("_", " ")
            cond = " (%s)" % s["condition_raw"] if s.get("condition_raw") else ""
            out.append(_q("%sthe advice includes %s: %s%s" % (lead(fact, names), op, s["method"], cond)))
    return out


def field_claims(fact: dict, names: dict, printed: dict | None = None) -> list[str]:
    st, out, ld = fact["subtype"], [], lead(fact, names)

    def pct(prefix):
        lo, hi = fact.get(prefix + "_min"), fact.get(prefix + "_max")
        if lo is None and hi is None:
            return None
        if lo is None:
            return bounded(fact, prefix + "_max", "max", hi) + "%"
        if hi is None:
            return bounded(fact, prefix + "_min", "min", lo) + "%"
        return "%s%%" % span(lo, hi)

    if st == "HarvestRule":
        if pct("harvest_moisture_pct"):
            out.append(_q("%sthe crop is harvested at %s moisture" % (ld, pct("harvest_moisture_pct"))))
        if pct("threshing_moisture_pct"):
            out.append(_q("%sthreshing is done at %s moisture" % (ld, pct("threshing_moisture_pct"))))
    elif st == "DryingSpec" and pct("target_moisture_pct"):
        term = " for %s" % fact["storage_term_raw"] if fact.get("storage_term_raw") else ""
        out.append(_q("%sthe produce is dried to %s moisture%s" % (ld, pct("target_moisture_pct"), term)))
    elif st == "StorageRule" and any(fact.get(k) is not None for k in ("storage_months_min", "min_moisture_pct",
                                                                       "max_moisture_pct")):
        lo, hi = fact.get("storage_months_min"), fact.get("storage_months_max")
        if lo is not None and hi is None:
            months = "for %s months" % bounded(fact, "storage_months_min", "min", lo)
        elif lo is not None:
            months = "for %s months" % span(lo, hi)
        else:
            months = ""
        m_lo, m = fact.get("min_moisture_pct"), fact.get("max_moisture_pct")
        if m_lo is not None and m is not None:                    # schema v1.3: "12 - 13 %" keeps both bounds
            b = span(m_lo, m)
        elif m_lo is not None:
            b = bounded(fact, "min_moisture_pct", "min", m_lo)
        else:
            b = None if m is None else bounded(fact, "max_moisture_pct", "max", m)
        moist = "" if b is None else " at a moisture content %s%%" % (b if b.startswith("below") else "of " + b)
        where = " in %s" % fact["structure"] if fact.get("structure") else ""
        out.append(_q("%sit is stored %s%s%s" % (ld, months, moist, where)))
    elif st == "IrrigationRule" and fact.get("depth_cm") is not None:
        when = timing(fact["steps"][0]) if fact["steps"] else ""
        out.append(_q("%sa water depth of %s cm is kept%s" % (ld, num(fact["depth_cm"]), when)))
    elif st == "PestThreshold":
        pests = " or ".join(_names(fact, "pest_ids", names, printed))
        for c in fact["clauses"]:
            unit = "%" if c["unit"] == "pct" else ""
            per = " " + BASIS.get(c.get("sampling_unit") or "absolute", "") if c.get("sampling_unit") else ""
            if c.get("sampling_count") is not None:                  # schema v1.3: "/25 net sweeps"
                per = " per %d %s" % (c["sampling_count"], SAMPLE_TEXT[c["sampling_object"]])
            out.append(_q("action against %s is needed at %s%s %s%s%s" % (pests, num(c["value"]), unit, c["observation"],
                                                                           per, conditions(c.get("conditions")))))
    elif st == "Spacing":
        lo, hi = fact.get("seedlings_per_hill_min"), fact.get("seedlings_per_hill_max")
        if lo is not None or hi is not None:
            out.append(_q("%s%s seedlings are planted per hill" % (ld, span(lo if lo is not None else hi, hi))))
        if fact.get("row_cm") is not None and fact.get("plant_cm") is not None:
            out.append(_q("%sthe spacing is %s x %s cm" % (ld, num(fact["row_cm"]), num(fact["plant_cm"]))))
        if fact.get("hills_per_m2") is not None:
            out.append(_q("%s%s hills are planted per square metre" % (ld, num(fact["hills_per_m2"]))))
    elif st == "Caution":
        about = " or ".join(_names(fact, "about_ids", names, printed))
        for name in _names(fact, "concerns", names, printed):
            out.append(_q("%sit advises against using %s%s" % (ld, name, " for %s" % about if about else "")))
    elif st == "QualitySpec":
        out.append(_q(quality_claim(fact)))
    elif st == "VarietyRecommendation":
        for name in (printed or {}).get("recommends") or [names.get(i, i) for i in fact["recommends"]]:
            several = re.search(r",|&|\band\b", name)
            out.append(_q("%s%s %s recommended%s" % (ld, name, "are" if several else "is", place(fact, names, printed))))
    elif st == "SowingWindow" and fact.get("start_month"):
        out.append(_q("%s%s%s %s" % (ld, WINDOW_TEXT[fact.get("window_for") or "sowing"], place(fact, names, printed),
                                     window_text(fact))))
    return out


WINDOW_TEXT = {"nursery_sowing": "the nursery is sown", "transplanting": "transplanting is done",
               "direct_seeding": "the direct-seeded crop is sown", "sowing": "the crop is sown"}


def place(fact: dict, names: dict, printed: dict | None = None) -> str:
    """Schema v1.6: " in Tarai, Bhabhar & Plain", the places the fact's text names (as printed), or ""."""
    where = (printed or {}).get("regions") or [names.get(r["id"], r["id"]) for r in fact.get("regions") or []
                                                if r.get("origin") == "text"]
    return " in %s" % " or ".join(where) if where else ""


def window_text(fact: dict) -> str:
    """"from 16 May to 7 June"; "on 15 March" for one day; a bound with no day names the month only."""
    def day(m, d):
        return "%s %s" % (d, MONTH_TEXT[m]) if d else MONTH_TEXT[m]
    a, b = day(fact["start_month"], fact.get("start_day")), day(fact["end_month"], fact.get("end_day"))
    return "on %s" % a if a == b else "from %s to %s" % (a, b)


COMMODITY = {"paddy": "paddy", "raw_rice": "raw rice", "parboiled_rice": "parboiled rice"}
GRADE_TEXT = {"grade_a": "Grade 'A'", "common": "Common"}


def quality_claim(fact: dict) -> str:
    """Schema v1.5: "for paddy (Grade 'A' and Common), Moisture content is at most 17%"; an absent limit is
    "paddy is free from Argemone mexicana"; a sub-limit names the limit it sits in."""
    grades = " and ".join(GRADE_TEXT[g] for g in fact["grades"])
    what = "%s (%s)" % (COMMODITY[fact["commodity_form"]], grades)
    if fact["limit_type"] == "absent":
        return "%s is free from %s" % (what, fact["parameter_raw"])
    v = num(fact["limit_value"]) + ("%" if fact.get("unit") == "pct" else "")
    inclusive = fact.get("limit_inclusive", True)
    bound = {("max", True): "at most", ("max", False): "below", ("min", True): "at least",
             ("min", False): "more than"}[(fact["limit_type"], inclusive)]
    within = " within the limit for %s" % fact["part_of"].replace("_", " ") if fact.get("part_of") else ""
    return ", for %s, %s is %s %s%s" % (what, fact["parameter_raw"], bound, v, within)


def claims_for(fact: dict, names: dict, printed: dict | None = None) -> list[str]:
    """[] means no code-built claim: the fact needs human review and can never be auto_verified.
    `printed` (from `printed_names`) gives the names as the book prints them; without it, name_en."""
    out = field_claims(fact, names, printed) + step_claims(fact, names, printed)
    if not out and fact["subtype"] != "Caution":
        out = fallback_claims(fact, names)
    return out


def claim_key(fact_key: str, claim: str, control: bool = False) -> str:
    return ("x_" if control else "c_") + hashlib.sha1(("%s|%s" % (fact_key, claim)).encode("utf-8")).hexdigest()[:16]


PCT_FIELDS = ("target_moisture_pct", "harvest_moisture_pct", "threshing_moisture_pct")


def _changed(fact: dict) -> dict | None:
    """A copy with the first number changed: x2, or +10 points for a percentage. None if no number."""
    f = copy.deepcopy(fact)
    for s in f["steps"]:
        for a in s["applies"]:
            if any(a.get(k) is not None for k in ("value", "min", "max")):
                for k in ("value", "min", "max"):
                    if a.get(k) is not None:
                        a[k] = a[k] + 10 if a["unit"] == "pct" else a[k] * 2
                return f
    for p in PCT_FIELDS:
        if f.get(p + "_min") is not None or f.get(p + "_max") is not None:
            for k in (p + "_min", p + "_max"):
                if f.get(k) is not None:
                    f[k] += 10
            return f
    for k, step in (("max_moisture_pct", 10), ("depth_cm", None)):
        if f.get(k) is not None:
            f[k] = f[k] + step if step else f[k] * 2
            return f
    if f.get("clauses"):
        f["clauses"][0]["value"] *= 2
        return f
    if f.get("limit_value") is not None:                            # schema v1.5 QualitySpec
        # always stricter than printed: a looser limit ("at most 27%" for 17%) is implied by the true one
        f["limit_value"] = f["limit_value"] / 2 if f["limit_type"] == "max" else f["limit_value"] * 2
        return f
    if f["subtype"] == "SowingWindow" and f.get("start_month"):    # schema v1.6: the window three months later
        for m, d in (("start_month", "start_day"), ("end_month", "end_day")):
            f[m] = (f[m] + 2) % 12 + 1
            if f.get(d):
                f[d] = min(f[d], MONTH_END[f[m]])
        return f
    return None


CONTROL_KINDS = ("number", "unit", "pest")
UNIT_SWAP = {"kg": "g", "g": "kg", "l": "ml", "ml": "l", "t": "kg"}       # same kind of unit, wrong size
PEST_KEYS = ("pest_ids", "target_ids", "about_ids")


def _changed_unit(fact: dict) -> dict | None:
    """A copy with the first quantity's unit swapped (kg <-> g, l <-> ml, t -> kg). None if no such unit."""
    f = copy.deepcopy(fact)
    for s in f["steps"]:
        for a in s["applies"]:
            if a.get("unit") in UNIT_SWAP and any(a.get(k) is not None for k in ("value", "min", "max")):
                a["unit"] = UNIT_SWAP[a["unit"]]
                return f
    return None


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def subject_terms(fact: dict, printed: dict | None) -> list[str]:
    """What a pest-swapped claim pairs the new pest with: the products as printed, the concerns, and
    the threshold observations."""
    p = printed or {}
    terms = [t for s in p.get("applies") or [] for t in s] + list(p.get("concerns") or [])
    terms += [c["observation"] for c in fact.get("clauses") or [] if c.get("observation")]
    return [t for t in terms if t]


def _changed_pest(fact: dict, names: dict, printed: dict | None, unit_text: str | None = None,
                  pest_terms: dict | None = None) -> tuple[dict, dict | None] | None:
    """A copy naming another seeded pest in place of the fact's first pest, target or ABOUT pest: the
    first `pest:` id in sorted order that the fact does not name. Given the unit text, the new pest must
    share no line with the fact's subject (`subject_terms`): every pest is discussed somewhere in a pest
    unit, but a claim pairing it with this product, concern or observation is only true on such a line.
    Pest names, labels ("BPH") and scientific names (`pest_terms`) are compared with spaces removed
    ("Blue leafhopper/ white leafhopper"). None if no pest qualifies."""
    named = {i for k in PEST_KEYS for i in fact.get(k) or []}
    if unit_text is not None:
        lines = [_squash(line) for line in unit_text.splitlines()]
        subject = [_squash(t) for t in subject_terms(fact, printed)]
        if not subject:
            return None                                     # nothing to check the new pest against

    def clear(pid):
        if unit_text is None:
            return True
        terms = [_squash(t) for t in (pest_terms or {}).get(pid, {names[pid]})]
        return not any(any(t in line for t in terms) and any(s in line for s in subject) for line in lines)

    other = next((i for i in sorted(names) if i.startswith("pest:") and i not in named and clear(i)), None)
    for key in PEST_KEYS:
        if fact.get(key) and other:
            f, p = copy.deepcopy(fact), copy.deepcopy(printed)
            f[key] = [other] + f[key][1:]
            if p is not None:
                p[key] = [names[other]] + p[key][1:]
            return f, p
    return None


def control_pair(fact: dict, names: dict, printed: dict | None = None, kind: str = "number",
                 unit_text: str | None = None, pest_terms: dict | None = None) -> tuple[str, str] | None:
    """(the true claim, its deliberately wrong copy), or None; see control_claim."""
    if kind == "number":
        changed, changed_printed = _changed(fact), printed
    elif kind == "unit":
        changed, changed_printed = _changed_unit(fact), printed
    elif kind == "pest":
        changed, changed_printed = _changed_pest(fact, names, printed, unit_text, pest_terms) or (None, None)
    else:
        raise ValueError("unknown control kind %r" % kind)
    if changed is None:
        return None
    pairs = zip(claims_for(fact, names, printed), claims_for(changed, names, changed_printed))
    return next(((a, b) for a, b in pairs if a != b), None)


def printed_in_unit(claim: str, control: str, unit_text: str) -> bool:
    """Whether the control's changed words, each with a neighbouring word ("60 kg", "2 hoppers"), are
    printed in the unit: then the control may be true elsewhere in the unit, or false only through its
    condition ("60 kg for short duration" made into long duration's 60 kg), and is not used."""
    text = re.sub(r"\s+", " ", unit_text).casefold()
    a, b = claim.casefold().split(), control.casefold().split()
    for op, _, _, j1, j2 in SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        window = b[max(j1 - 1, 0):j2 + 1]
        for k in range(len(window) - 1):
            pair = window[k:k + 2]
            if " ".join(pair) in text or "".join(pair) in text:
                return True
    return False


def control_claim(fact: dict, names: dict, printed: dict | None = None, kind: str = "number",
                  unit_text: str | None = None, pest_terms: dict | None = None) -> str | None:
    """A deliberately wrong claim: the fact's first claim that the change alters. `number`: one number
    changed (x2, or +10 points for a percentage); `unit`: one unit swapped; `pest`: another pest named,
    one no line of the unit pairs with the fact's subject."""
    pair = control_pair(fact, names, printed, kind, unit_text, pest_terms)
    return pair[1] if pair else None
