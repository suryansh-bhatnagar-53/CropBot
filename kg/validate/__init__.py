"""Validate (step 11): code checks on the facts step 10 validated against the schema. No model.

  uv run python -m kg.validate source:tnau_agriculture_2020

Every check returns pass, fail or skip with a reason. A failure only adds a review reason: an
`extracted` fact becomes `needs_review`; nothing is corrected, nothing becomes approved (Jev, step 12,
decides auto_verified). Input: data/normalized/<id>/facts.jsonl and the step 9 runs it came from.
Output: data/validated/<id>/{facts.jsonl, report.json} and data/review/validation_<id>.csv (gitignored).

  1 quote_location   the quote is found exactly once in its unit; a fact's table_ref/row is where it was found
  2 raw_numbers      every raw text is in the quote; every parsed number is printed in its raw text
  3 value_ranges     moisture, months, offsets, depths and doses within approved bounds; a.i. per ha <= 3 kg
  4 alternatives     fertilizer alternatives agree within 15 % on N, P2O5, K2O (approved percentages only)
  5 ingredients      every applied active ingredient is registered; unknown, restricted, banned fail (closed)
  6 review_kept      a flagged or inferred fact is needs_review
  7 range_narrowed   a printed range ("12 - 13 %") is not stored as a single bound
  8 lost_glyph       no stored text, on the fact or its step 9 fact, contains U+FFFD
  9 printed_text     every text the extraction copies (names, units, bases, formulations, stages, observations,
                     structures, methods, maturity signs, unmapped phrases) appears in its quote
 10 scope_in_unmapped  no unmapped phrase looks like scope (a variety type, area, condition or moisture); a
                     failure gives the review reason "scope in unmapped: served scope would be wider than printed"
                     and the phrases are stored on the fact (step 14 hides it, unless a Caution, until approved)
 11 number_in_text   no number survives only in text (an unmapped phrase or a step's purpose_raw); schema v1.4
v1.4 also extends 2 (durations, stated times, mix strength, carrier, purpose), 3 (durations, week offsets),
7 (durations) and 9 (purpose, duration, carrier and mix strength texts).
"""

import json
import re
from collections import Counter

from kg.extract import EXTRACTED_DIR, get_unit, load_tables, render_unit
from kg.extract.numbers import printed_numbers
from kg.extract.quotes import normalise
from kg.load.seed import read_seed
from kg.registry import ROOT
from kg.schema.concepts import ActiveIngredient, Fertilizer
from kg.schema.vocab import NOT_SCOPE, SCOPE_IN_UNMAPPED, SCOPE_IN_UNMAPPED_REASON

NORMALIZED_DIR = ROOT / "data" / "normalized"
VALIDATED_DIR = ROOT / "data" / "validated"
REVIEW_CSV = "validation"      # data/review/validation_<source slug>.csv (kg.registry.review_csv)
CHECKS = ("quote_location", "raw_numbers", "value_ranges", "alternatives", "ingredients", "review_kept",
          "range_narrowed", "lost_glyph", "printed_text", "scope_in_unmapped", "number_in_text")
NARROWED = "printed range stored as a single bound"
LOST_GLYPH = "�"                       # the Unicode replacement character
PLACEHOLDER_UNITS = {"count"}               # prompt v2: organisms or items with no printed unit
PRINTED_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*%?\s*(?:-|to)\s*(\d+(?:\.\d+)?)")
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "twenty": 20, "hundred": 100}
AI_MAX_KG_PER_HA = 3.0


def result(status, reason=None, **detail):
    return {"status": status, "reason": reason, **detail}


# --- 1 quote location ----------------------------------------------------------------------

def _rows(refs: list[str]) -> set[tuple[str, int]]:
    """"#/tables/56 row 4 + #/tables/57 row 0" -> {("#/tables/56", 4), ("#/tables/57", 0)}."""
    return {(m.group(1), int(m.group(2))) for ref in refs
            for m in re.finditer(r"((?:tr:p\d{3,4})?#/tables/\d+) row (\d+)", ref)}


def check_quote_location(fact: dict, quote_check: dict) -> dict:
    n = quote_check["occurrences"]
    if n != 1:
        return result("fail", "quote found %d times in its unit" % n)
    span = fact["evidence"][0]
    if span["table_ref"] is not None:
        if (span["table_ref"], span["table_row"]) not in _rows(quote_check["refs"]):
            return result("fail", "table_ref %s row %s is not where the quote was found (%s)"
                          % (span["table_ref"], span["table_row"], quote_check["refs"]))
    return result("pass")


# --- 2 raw numbers -------------------------------------------------------------------------

def _printed(text: str) -> set[float]:
    found = set(printed_numbers(text))
    found |= {float(v) for w, v in NUMBER_WORDS.items() if re.search(r"\b%s\b" % w, text, re.I)}
    return found


def _same(v: float, found: set[float]) -> bool:
    return any(abs(abs(v) - f) < 1e-9 for f in found)


def check_raw_numbers(raw_fact: dict) -> dict:
    """On the step 9 fact: the printed values, before any conversion."""
    q = normalise(raw_fact["quote"])
    problems = []

    def in_quote(text, what):
        if text and normalise(text) not in q:
            problems.append("%s %r is not in the quote" % (what, text))

    def printed(value, text, what):
        if value is not None and not _same(value, _printed(text or "")):
            problems.append("%s %g is not printed in %r" % (what, value, text))

    for name, text in raw_fact["raw"].items():
        in_quote(text, "raw[%s]" % name)
        printed(raw_fact.get(name), text, name)
    for s in raw_fact["steps"]:
        in_quote(s["timing_raw"], "timing_raw")
        for k in ("offset_min", "offset_max"):
            printed(s[k], s["timing_raw"], "step %d %s" % (s["order"], k))
        for t in s.get("repeat_offsets") or []:              # prompt v4: every stated time is printed
            printed(t, s["timing_raw"], "step %d repeat offset" % s["order"])
        in_quote(s.get("repeat_raw"), "repeat_raw")          # its count and interval come from code's word table
        in_quote(s.get("duration_raw"), "duration_raw")      # prompt v4
        for k in ("duration_min", "duration_max"):
            printed(s.get(k), s.get("duration_raw"), "step %d %s" % (s["order"], k))
        in_quote(s.get("purpose_raw"), "purpose_raw")
        for a in s["applies"]:
            in_quote(a["raw"], "raw of %s" % a["target"])
            for k in ("value", "min", "max"):
                printed(a[k], a["raw"], "%s %s" % (a["target"], k))
            in_quote(a.get("carrier_raw"), "carrier_raw of %s" % a["target"])
            # prompt v3: strength, mixing parts and share, each printed in its own raw text (v4: mix strength)
            for raw_key, keys in (("conc_raw", ("conc_value", "conc_min", "conc_max")),
                                  ("ratio_raw", ("ratio_part", "ratio_rest")), ("share_raw", ("share_pct",)),
                                  ("mix_conc_raw", ("mix_conc_value",))):
                if a.get(raw_key):
                    in_quote(a[raw_key], "%s of %s" % (raw_key, a["target"]))
                    for k in keys:
                        printed(a.get(k), a[raw_key], "%s %s" % (a["target"], k))
        for c in s["conditions"]:
            in_quote(c["raw"], "condition raw")
            printed(c["value"] if isinstance(c["value"], (int, float)) else None, c["raw"], c["variable"])
    for cl in raw_fact.get("clauses", []):
        in_quote(cl["raw"], "clause raw")
        printed(cl["value"], cl["raw"], "clause %s" % cl["observation"])
        for c in cl["conditions"]:
            in_quote(c["raw"], "condition raw")
            printed(c["value"] if isinstance(c["value"], (int, float)) else None, c["raw"], c["variable"])
    for c in raw_fact["conditions"]:
        in_quote(c["raw"], "condition raw")
        printed(c["value"] if isinstance(c["value"], (int, float)) else None, c["raw"], c["variable"])
    return result("fail", "; ".join(problems)) if problems else result("pass")


# --- 3 value ranges --------------------------------------------------------------------------

FIELD_RANGES = {
    "harvest_moisture_pct": (10, 30), "threshing_moisture_pct": (10, 25), "target_moisture_pct": (5, 20),
    "max_moisture_pct": (5, 20), "min_moisture_pct": (5, 20), "storage_months": (0, 60), "depth_cm": (0, 20),
}
TO_KG = {"kg": 1, "g": 0.001, "t": 1000, "l": 1, "ml": 0.001}      # l and ml read as kg (density ~1)
DURATION_RANGES = {"minutes": (1, 240), "hours": (1, 72), "days": (1, 60)}    # approved 2026-10-22
# schema v1.5 QualitySpec limits (item H, 2026-10-23): a refraction is a percentage of the lot; procurement
# moisture limits sit between 5 and 25 %; a length/breadth ratio between 1 and 5
QUALITY_RANGES = {"moisture": (5, 25), "length_breadth_ratio": (1, 5)}
QUALITY_PCT_RANGE = (0, 100)
OFFSET_LIMITS = {"days": 180, "hours": 72, "weeks": 26}


def _amounts(a: dict) -> list[float]:
    return [a[k] for k in ("value", "min", "max") if a.get(k) is not None]


def _formulation_pct(formulation: str | None) -> float | None:
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*%", formulation or "")
    return float(m.group(1)) if m else None


def check_value_ranges(fact: dict) -> dict:
    problems, skipped = [], []
    for field, (lo, hi) in FIELD_RANGES.items():
        for name in (field, field + "_min", field + "_max"):
            v = fact.get(name)
            if v is not None and not lo <= v <= hi:
                problems.append("%s %g outside %g-%g" % (name, v, lo, hi))
    if fact.get("subtype") == "QualitySpec" and fact.get("limit_value") is not None:
        lo, hi = QUALITY_RANGES.get(fact["parameter"], QUALITY_PCT_RANGE)
        if not lo <= fact["limit_value"] <= hi:
            problems.append("%s limit %g outside %g-%g" % (fact["parameter"], fact["limit_value"], lo, hi))
    for s in fact["steps"]:
        limit = OFFSET_LIMITS[s["offset_unit"]]
        for k in ("offset_min", "offset_max", "repeat_offsets"):
            for v in (s.get(k) or []) if k == "repeat_offsets" else [s[k]]:
                if v is not None and abs(v) > limit:
                    problems.append("step %d %s %g beyond +-%d %s" % (s["order"], k, v, limit, s["offset_unit"]))
        if s.get("duration_unit"):                                   # schema v1.4 durations
            lo, hi = DURATION_RANGES[s["duration_unit"]]
            for k in ("duration_min", "duration_max"):
                if s.get(k) is not None and not lo <= s[k] <= hi:
                    problems.append("step %d %s %g outside %g-%g %s" % (s["order"], k, s[k], lo, hi, s["duration_unit"]))
        for a in s["applies"]:
            kind, unit, basis, vals = a["target_id"].split(":", 1)[0], a.get("unit"), a.get("basis"), _amounts(a)
            if not vals:
                continue
            kg = [v * TO_KG[unit] for v in vals] if unit in TO_KG else None
            bound = None
            if basis == "per_ha" and kg is not None:
                bound = {"nutrient": 500, "fertilizer": 1000, "organic_input": 25000}.get(kind)
                if kind == "ai":
                    pct = _formulation_pct(a.get("formulation"))
                    if pct is None:
                        skipped.append("%s: no formulation %% to compute a.i." % a["target_id"])
                        continue
                    ai = max(kg) * pct / 100
                    if ai > AI_MAX_KG_PER_HA:
                        problems.append("%s %s %s/ha = %.2f kg a.i./ha (> %g); %s"
                                        % (a["target_id"], a["formulation"], a["raw"], ai, AI_MAX_KG_PER_HA,
                                           "ml read as g" if unit in ("ml", "l") else "as printed"))
                    continue
            elif basis == "per_kg_seed" and unit in ("g", "ml"):
                bound, kg = 20, vals                                     # g or ml per kg of seed
            elif basis == "per_cent_nursery" and kg is not None:
                bound = 100 if kind == "organic_input" else 50
            if bound is None:
                skipped.append("%s: no bound for %s %s" % (a["target_id"], unit, basis))
                continue
            if max(kg) > bound:
                problems.append("%s %s (%g %s %s) above %g" % (a["target_id"], a["raw"], max(vals), unit, basis, bound))
    if problems:
        return result("fail", "; ".join(problems), skipped=skipped)
    return result("pass", skipped=skipped)


# --- 4 alternatives ------------------------------------------------------------------------

def check_alternatives(fact: dict, fertilizers: dict) -> dict:
    """fertilizers: approved Fertilizer concepts by id. Options are compared per nutrient."""
    groups = {}
    for s in fact["steps"]:
        if s["alt_group"] is not None:
            groups.setdefault((s["order"], s["alt_group"]), []).append(s)
    groups = {k: v for k, v in groups.items() if len(v) > 1 and all(
        a["target_id"].startswith("fertilizer:") for s in v for a in s["applies"]) and all(s["applies"] for s in v)}
    if not groups:
        return result("skip", "no alternatives made only of fertilizers", applies=False)
    out = []
    for key, steps in groups.items():
        missing = sorted({a["target_id"] for s in steps for a in s["applies"] if a["target_id"] not in fertilizers
                          or None in (fertilizers[a["target_id"]].n_pct, fertilizers[a["target_id"]].p2o5_pct,
                                      fertilizers[a["target_id"]].k2o_pct)})
        if missing:
            return result("skip", "no approved percentages for %s" % ", ".join(missing), applies=True)
        totals = []
        for s in steps:
            t = Counter()
            for a in s["applies"]:
                f, amount = fertilizers[a["target_id"]], max(_amounts(a))
                t["n"] += amount * f.n_pct / 100
                t["p2o5"] += amount * f.p2o5_pct / 100
                t["k2o"] += amount * f.k2o_pct / 100
            totals.append(t)
        for nut in ("n", "p2o5", "k2o"):
            vals = [t[nut] for t in totals]
            if max(vals) > 0 and (max(vals) - min(vals)) / max(vals) > 0.15:
                out.append("group %s: %s totals %s differ by more than 15%%" % (key, nut, [round(v, 2) for v in vals]))
    return result("fail", "; ".join(out), applies=True) if out else result("pass", applies=True)


# --- 5 ingredients (fail closed) ------------------------------------------------------------

def check_ingredients(fact: dict, ais: dict) -> dict:
    applied = sorted({a["target_id"] for s in fact["steps"] for a in s["applies"] if a["target_id"].startswith("ai:")})
    if not applied:
        return result("skip", "applies no active ingredient")
    bad = {i: (ais[i].reg_status.value if i in ais else "not seeded") for i in applied}
    bad = {i: st for i, st in bad.items() if st != "registered"}
    if bad:
        return result("fail", "not registered (fail closed): %s" % ", ".join("%s=%s" % kv for kv in sorted(bad.items())))
    return result("pass")


# --- 6 review kept ---------------------------------------------------------------------------

def check_review_kept(record: dict, raw_fact: dict) -> dict:
    fact = record["fact"]
    reasons = list(record["review_reasons"])
    if raw_fact["extraction_flags"]:
        reasons.append("flags %s" % raw_fact["extraction_flags"])
    for s in fact["steps"]:
        for a in s["applies"]:
            if a.get("basis_inferred") or a.get("inherited"):
                reasons.append("%s basis_inferred/inherited" % a["target_id"])
    if fact.get("excluded_regions"):
        reasons.append("exclusion")
    if reasons and fact["status"] != "needs_review":
        return result("fail", "status %s although: %s" % (fact["status"], "; ".join(reasons)))
    return result("pass", reasons=len(reasons))


# --- 7 range narrowed ------------------------------------------------------------------------

def _range_ends(text: str | None) -> set[float]:
    """Both ends of every range printed in the text ("12 - 13 %" -> {12, 13})."""
    return {float(x) for m in PRINTED_RANGE.finditer(normalise(text or "")) for x in m.groups()}


def check_range_narrowed(fact: dict) -> dict:
    """A value stored as one bound (or equal bounds) that is an end of a range printed in its raw text."""
    problems = []

    def single(lo, hi, text, what):
        if lo is None and hi is None:
            return
        if lo is not None and hi is not None and lo != hi:
            return                                                       # both bounds stored
        v = lo if lo is not None else hi
        if _same(v, _range_ends(text)):
            problems.append("%s %g from %r" % (what, v, text))

    for name, text in (fact.get("raw") or {}).items():
        if name.endswith("_min") or name.endswith("_max"):
            base = name[:-4]
            single(fact.get(base + "_min"), fact.get(base + "_max"), text, name)
        elif name.startswith("min_") or name.startswith("max_"):        # v1.3 StorageRule min_/max_moisture_pct
            base = name[4:]
            single(fact.get("min_" + base), fact.get("max_" + base), text, name)
        else:
            single(fact.get(name), None, text, name)
    for s in fact["steps"]:
        if not s.get("repeat_offsets"):              # with stated times, the offsets are the first time on purpose
            single(s.get("offset_min"), s.get("offset_max"), s.get("timing_raw"), "step %d offset" % s["order"])
        single(s.get("duration_min"), s.get("duration_max"), s.get("duration_raw"), "step %d duration" % s["order"])
        for a in s["applies"]:
            lo, hi = (a["value"], None) if a.get("value") is not None else (a.get("min"), a.get("max"))
            single(lo, hi, a.get("raw"), "%s amount" % a["target_id"])
        for c in s.get("conditions") or []:
            if isinstance(c.get("value"), (int, float)):
                single(c["value"], c.get("value_max"), c.get("raw"), c["variable"])
    for cl in fact.get("clauses") or []:
        single(cl["value"], None, cl.get("raw"), "clause %s" % cl["observation"])
        for c in cl.get("conditions") or []:
            if isinstance(c.get("value"), (int, float)):
                single(c["value"], c.get("value_max"), c.get("raw"), c["variable"])
    for c in fact.get("conditions") or []:
        if isinstance(c.get("value"), (int, float)):
            single(c["value"], c.get("value_max"), c.get("raw"), c["variable"])
    if problems:
        return result("fail", "%s: %s" % (NARROWED, "; ".join(problems)))
    return result("pass")


# --- 8 lost glyph ----------------------------------------------------------------------------

def _strings(obj, path=""):
    """(path, text) for every string in a nested fact, keys included."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            sub = "%s.%s" % (path, k) if path else k
            yield sub + " (key)", k
            yield from _strings(v, sub)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, "%s[%d]" % (path, i))


def check_lost_glyph(fact: dict, raw_fact: dict) -> dict:
    """A replacement character means a glyph was lost somewhere before it was stored."""
    bad = ["%s %s" % (where, p) for where, obj in (("fact", fact), ("step 9", raw_fact))
           for p, text in _strings(obj) if LOST_GLYPH in text]
    return result("fail", "U+FFFD in " + ", ".join(bad)) if bad else result("pass")


# --- 9 printed text --------------------------------------------------------------------------

def _printed_in(text: str, q: str) -> bool:
    """`text` occurs in `q` (both normalised), not inside a longer word or number: "g" is not in "kg"."""
    t = normalise(text)
    for m in re.finditer(re.escape(t), q):
        before = q[m.start() - 1] if m.start() else ""
        after = q[m.end()] if m.end() < len(q) else ""
        if not ((t[0].isalpha() and before.isalpha()) or (t[0].isdigit() and before.isdigit())
                or (t[-1].isalpha() and after.isalpha()) or (t[-1].isdigit() and after.isdigit())):
            return True
    return False


COPIED_LISTS = ("varieties", "seasons", "systems", "soils", "purposes", "stages", "regions", "recommends", "pests",
                "targets", "concerns", "about", "unmapped", "maturity_signs")
COPIED_FIELDS = ("structure", "storage_term_raw", "coefficients_raw", "target_nutrient", "soil_series", "valid_range",
                 "authority", "valid_for_season", "parameter", "method", "criterion",
                 "start_raw", "end_raw")                 # prompt v6: a window's calendar words, copied as printed
# prompt v3 asks for these only as "a short phrase" / "a few words from the text", not as printed
PHRASE_FIELDS = ("maturity_signs", "method", "criterion")
HEADING_FLAGS = ("scope_from_heading", "target_from_heading")


def copied_texts(raw_fact: dict) -> list[tuple[str, str, str]]:
    """(where, field, text) for every text the extraction copies from the book. A quantity's unit "count"
    (prompt v2's placeholder) and a basis given by a default-scope rule or inferred are not copied."""
    out = [("%s[%d]" % (k, i), k, t) for k in COPIED_LISTS for i, t in enumerate(raw_fact.get(k) or [])]
    out += [("excluded_regions[%d].name" % i, "excluded_regions", x["name"])
            for i, x in enumerate(raw_fact.get("excluded_regions") or [])]
    fields = COPIED_FIELDS
    if raw_fact.get("parameter_raw"):            # prompt v5: parameter is a list value, its printed name is here
        fields = tuple(k for k in COPIED_FIELDS if k != "parameter") + ("parameter_raw",)
        if raw_fact.get("unit"):
            fields += ("unit",)
    out += [(k, k, raw_fact[k]) for k in fields if isinstance(raw_fact.get(k), str) and raw_fact[k]]
    for s in raw_fact.get("steps") or []:
        step = "step %d" % s["order"]
        out += [("%s %s" % (step, k), k, s[k]) for k in ("stage", "method", "purpose_raw", "duration_raw") if s.get(k)]
        for a in s["applies"]:
            out.append(("%s target" % step, "target", a["target"]))
            if a.get("unit") and a["unit"] not in PLACEHOLDER_UNITS:
                out.append(("%s unit" % step, "unit", a["unit"]))
            for k in ("conc_unit", "formulation", "water_raw", "carrier_raw", "mix_conc_raw"):
                if a.get(k):
                    out.append(("%s %s" % (step, k), k, a[k]))
            if a.get("basis") and not (a.get("basis_rule") or a.get("basis_inferred")):
                out.append(("%s basis" % step, "basis", a["basis"]))
    for i, cl in enumerate(raw_fact.get("clauses") or []):
        out += [("clause %d %s" % (i + 1, k), k, cl[k]) for k in ("observation", "unit", "sampling_unit", "stage")
                if cl.get(k)]
    return out


def check_printed_text(raw_fact: dict, subheading: str | None = None, row: str | None = None) -> dict:
    """On the step 9 fact: every copied text (`copied_texts`) is printed in the quote, not inside a longer
    word. Also accepted: the fact's own table row (`row`; a table fact quotes a passage of one cell, its pest
    is the row's first cell) and, for a fact flagged scope_from_heading or target_from_heading, its
    sub-heading. A difference only in case ("Soak" / "soak") passes and is counted in `case_only`. A
    failure says when prompt v3 allowed a short phrase for that field."""
    q = normalise(raw_fact["quote"])
    if row:
        q += " " + normalise(row)
    if subheading and set(HEADING_FLAGS) & set(raw_fact.get("extraction_flags") or []):
        q += " " + normalise(subheading)
    problems, case_only = [], []
    for where, field, text in copied_texts(raw_fact):
        if _printed_in(text, q):
            continue
        if _printed_in(text.casefold(), q.casefold()):
            case_only.append(where)
            continue
        note = " (prompt v3 allows a short phrase here)" if field in PHRASE_FIELDS else ""
        problems.append("%s %r is not in the quote%s" % (where, text, note))
    if problems:
        return result("fail", " | ".join(problems), case_only=case_only)
    return result("pass", case_only=case_only)


# --- 10 scope in unmapped ----------------------------------------------------------------------

def scope_phrases(unmapped: list[str] | None) -> list[tuple[str, list[str]]]:
    """(phrase, kinds) for every unmapped phrase that looks like scope (kg.schema.vocab.SCOPE_IN_UNMAPPED)."""
    out = []
    for phrase in unmapped or []:
        if re.search(NOT_SCOPE, phrase, re.I):
            continue
        kinds = [k for k, patterns in SCOPE_IN_UNMAPPED.items() if any(re.search(p, phrase, re.I) for p in patterns)]
        if kinds:
            out.append((phrase, kinds))
    return out


def check_scope_in_unmapped(fact: dict) -> dict:
    """On the step 10 fact: an unmapped phrase that names a variety type, an area, a condition or a moisture
    means the fact as stored applies more widely than the book says."""
    found = scope_phrases(fact.get("unmapped"))
    if not found:
        return result("pass")
    return result("fail", "; ".join("%r (%s)" % (p, ", ".join(k)) for p, k in found),
                  phrases=[p for p, _ in found])


# --- 11 number in text ---------------------------------------------------------------------------

NUMBER_IN_TEXT = "number only in text"


def check_number_in_text(fact: dict) -> dict:
    """Schema v1.4: a number that survives only in text (an unmapped phrase or a step's purpose_raw, e.g.
    "hastened by 3-4 days") is no value the bot can use or check; it adds a review reason."""
    texts = [("unmapped", t) for t in fact.get("unmapped") or []]
    texts += [("step %d purpose_raw" % s["order"], s["purpose_raw"]) for s in fact["steps"] if s.get("purpose_raw")]
    found = ["%s %r" % (where, t) for where, t in texts if re.search(r"\d", t)]
    return result("fail", "; ".join(found)) if found else result("pass")


def table_rows(rendered: list[str], refs: list[str]) -> str:
    """The rendered text of the table rows a quote was found in ("[#/tables/57 row 3] Brown planthopper …"),
    and of their table's header line (schema v1.5: "Maximum Limit (%)" gives a limit's unit)."""
    out = []
    for ref in refs:
        if "#/tables/" in ref:
            marker = "[%s]" % ref
            out += [line[len(marker):].strip() for line in rendered if line.startswith(marker)]
            header = "[%s header]" % ref.split(" row ", 1)[0]
            out += [line[len(header):].strip() for line in rendered if line.startswith(header)]
    return " ".join(out)


# --- running ---------------------------------------------------------------------------------

def step9_runs(entry) -> dict:
    """Every step 9 run of the source by cache key (the latest of each version and the history)."""
    d = EXTRACTED_DIR / entry.id.split(":", 1)[1]
    out = {}
    for version_dir in d.iterdir():
        if version_dir.is_dir():
            for p in version_dir.glob("*.json"):
                if p.name != "report.json":
                    rec = json.loads(p.read_text(encoding="utf-8"))
                    out[rec["cache_key"]] = rec
    return out


def review_notes(entry, quote: str, pdf_pages: list[int]) -> list[int]:
    """Indexes of the approved registry notes whose printed text is in the fact's quote on one of
    its pages."""
    q = normalise(quote)
    return [i for i, n in enumerate(entry.review_note)
            if n.status == "approved" and n.pdf_page in pdf_pages and normalise(n.match) in q]


def run(entry) -> dict:
    path = NORMALIZED_DIR / entry.id.split(":", 1)[1] / "facts.jsonl"
    records = [json.loads(line) for line in open(path, encoding="utf-8")]
    runs = step9_runs(entry)
    tables, rendered = load_tables(entry), {}

    def row_of(unit_id: str, refs: list[str]) -> str:
        if not any("#/tables/" in r for r in refs):
            return ""
        if unit_id not in rendered:                  # the unit text exactly as step 9 rendered it
            rendered[unit_id] = render_unit(entry, get_unit(entry, unit_id), tables)[0].splitlines()
        return table_rows(rendered[unit_id], refs)

    nodes = read_seed().nodes
    fertilizers = {n.id: n for n in nodes if isinstance(n, Fertilizer) and n.review_status.value == "approved"}
    ais = {n.id: n for n in nodes if isinstance(n, ActiveIngredient)}
    out, note_hits = [], Counter()
    for rec in records:
        step9 = runs[rec["run"]["cache_key"]]["facts"][rec["raw_index"]]
        fact = rec["fact"]
        checks = {
            "quote_location": check_quote_location(fact, step9["quote_check"]),
            "raw_numbers": check_raw_numbers(step9["fact"]),
            "value_ranges": check_value_ranges(fact),
            "alternatives": check_alternatives(fact, fertilizers),
            "ingredients": check_ingredients(fact, ais),
            "review_kept": check_review_kept(rec, step9["fact"]),
            "range_narrowed": check_range_narrowed(fact),
            "lost_glyph": check_lost_glyph(fact, step9["fact"]),
            "printed_text": check_printed_text(step9["fact"], step9.get("subheading"),
                                               row_of(rec["unit_id"], step9["quote_check"]["refs"])),
            "scope_in_unmapped": check_scope_in_unmapped(fact),
            "number_in_text": check_number_in_text(fact),
        }
        reasons = [SCOPE_IN_UNMAPPED_REASON if k == "scope_in_unmapped" else
                   "%s: %s" % (NUMBER_IN_TEXT, c["reason"]) if k == "number_in_text" else "%s: %s" % (k, c["reason"])
                   for k, c in checks.items() if c["status"] == "fail"]
        scope = checks["scope_in_unmapped"].get("phrases", [])
        alt = checks["alternatives"]
        if alt["status"] == "skip" and alt.get("applies"):
            reasons.append("alternatives: %s" % alt["reason"])
        hits = review_notes(entry, fact["evidence"][0]["quote"], step9["quote_check"]["pdf_pages"])
        note_hits.update(hits)
        # a row merged across pages can match the same note on each page; its text is listed once
        notes = list(dict.fromkeys(entry.review_note[i].note for i in hits))
        reasons += ["review note: %s" % n for n in notes]
        status = "needs_review" if reasons or fact["status"] == "needs_review" else fact["status"]
        out.append({**{k: rec[k] for k in ("unit_id", "raw_index", "subtype", "run")}, "fact_id": fact["id"],
                    "status_before": fact["status"], "status": status, "checks": checks, "review_notes": notes,
                    "review_reasons": rec["review_reasons"] + reasons,
                    "fact": {**fact, "status": status, "review_notes": notes,            # notes on the fact (v1.3)
                             "scope_in_unmapped": scope}})
    stale = [{"pdf_page": n.pdf_page, "match": n.match} for i, n in enumerate(entry.review_note)
             if n.status == "approved" and not note_hits[i]]
    return {"facts": out, "stale_notes": stale}


def report(result_: dict) -> dict:
    per = {c: Counter(f["checks"][c]["status"] for f in result_["facts"]) for c in CHECKS}
    failures = {c: [{"fact": "%s#%d" % (f["unit_id"].rsplit(":", 1)[1], f["raw_index"]), "subtype": f["subtype"],
                     "reason": f["checks"][c]["reason"]}
                    for f in result_["facts"] if f["checks"][c]["status"] == "fail"] for c in CHECKS}
    skips = {c: Counter(f["checks"][c]["reason"] for f in result_["facts"] if f["checks"][c]["status"] == "skip")
             for c in CHECKS}
    return {"facts": len(result_["facts"]),
            "per_check": {c: dict(per[c]) for c in CHECKS},
            "failures": failures, "skips": {c: dict(v) for c, v in skips.items() if v},
            "review_notes": [{"fact": "%s#%d" % (f["unit_id"].rsplit(":", 1)[1], f["raw_index"]), "notes": f["review_notes"]}
                             for f in result_["facts"] if f["review_notes"]],
            "stale_notes": result_["stale_notes"],
            "status_before": dict(Counter(f["status_before"] for f in result_["facts"])),
            "status_after": dict(Counter(f["status"] for f in result_["facts"])),
            "approved": sum(f["status"] == "approved" for f in result_["facts"])}
