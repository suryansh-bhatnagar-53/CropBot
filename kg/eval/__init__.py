"""Evaluate (step 15): the latest step 9 run of each unit against the frozen gold set. No model.

  uv run python -m kg.eval.gold                                # the gold workbook -> data/gold/*.jsonl
  uv run python -m kg.eval source:tnau_agriculture_2020        # this evaluation

One gold row is one value (one product, amount or reading). Each step 9 fact (held ones included) is split
into atoms of the same size: one per applied quantity, field value (moisture, depth, spacing), threshold
clause, Caution concern, step without a quantity, or, when none of these, the fact itself.

Matching: an atom is a candidate for a gold row when one normalised quote contains the other, or 80 % of the
shorter one's words are shared, on the gold row's PDF page (any page only for a containing quote, listed
as a page disagreement). Score = quote overlap + 2 x number agreement + name similarity; pairs are taken
greedily, best first, one to one, ties in gold-row then atom order. Numbers only choose between candidates.

Nothing is decided in code. Each matched pair's differences (value, unit, basis, condition, alternative
structure, purpose, subtype, timing, page, granularity) are listed in data/review/gold_disagreements.csv
for adjudication against the PDF. Verdicts are read back from data/gold/adjudications.csv, which only a
person decides (columns gold_id, field, verdict, note, atom, name, quote; verdict extraction | gold | both |
unclear). A disagreement is keyed by gold_id + field. An extracted atom with no gold row is a row with field
"extra", no gold_id, and its name and quote; judged extraction or both, it counts as correct (the gold set
lacks it).
Equality uses step 10's unit and basis tables (kg.normalize.units) and exact normalised text only.

Scoring (approved 2026-10-21):
  - sections: A all rows; B only rows whose pest marker (condition before ";") is BPH; C all rows;
  - gold "Other" rows, B's non-BPH rows, and rows matching a step 9 not-extracted entry are scored apart;
  - precision counts only atoms inside the annotated scope (PRECISION_SCOPE); atoms matched to unscored
    gold rows are left out of it, and so is a step without a value in a fact the gold set annotated
    (its context: "soak the seeds in water" beside the dose) unless a gold row names it;
  - a candidate must share a number or a name word with the gold row; B's BPH rows never match an atom
    that names another pest and not BPH;
  - every rate carries a Wilson 95 % interval; "agree" is a range until every disagreement is adjudicated.
Calibration: facts matched to gold rows, by verifier_score cut-off, for (a) all with a score, (b) only
`extracted` facts (what auto_verified would cover) and (c) their claims (each with its fact's label). The
proposed threshold is the lowest cut-off whose Wilson lower bound on (b)'s precision, open disagreements
counted wrong, is >= 0.90. It is never written to config/verify.toml.
"""

import csv
import json
import math
import re
from collections import Counter, defaultdict

from kg.eval.gold import FACT_SHEETS, GOLD_DIR, out_name
from kg.extract import EXTRACTED_DIR
from kg.extract.numbers import printed_numbers
from kg.extract.quotes import normalise
from kg.extract.versions import source_version
from kg.normalize import NORMALIZED_DIR
from kg.normalize.units import canon_basis, canon_unit
from kg.registry import ROOT
from kg.verify import VERIFIED_DIR, pest_terms

EVAL_DIR = ROOT / "data" / "eval"
DISAGREEMENTS_CSV = ROOT / "data" / "review" / "gold_disagreements.csv"
UNMATCHED_CSV = ROOT / "data" / "review" / "gold_unmatched.csv"
ADJUDICATIONS = GOLD_DIR / "adjudications.csv"
VERDICTS = ("extraction", "gold", "both", "unclear")

SECTION_UNITS = {"A": ("b879265e483b",), "B": ("e63c6fbba0e4",), "C": ("8e1d1b38b483", "f5b06c9fd3f8")}
C_SUBHEADINGS = ("Harvesting", "Threshing", "Drying", "Pre-storage seed treatment", "Storage")
PRECISION_SCOPE = {
    "A": "every atom of unit b879 (wet nursery)",
    "B": "atoms of unit e63c whose printed pest, target or ABOUT is BPH (name, label or scientific name), "
         "plus Cautions on PDF p. 63 whose quote names BPH",
    "C": "every atom of unit 8e1d (harvesting, p. 39); atoms of unit f5b0 under the sub-headings "
         + ", ".join(C_SUBHEADINGS),
}
ALT_LABELS = ("option", "preferred", "fallback")
QUOTE_MIN = 0.8
CUTOFFS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.97, 0.99)
TARGET_LB = 0.90
Z = 1.96


# --- small helpers ---------------------------------------------------------------------------------

def norm(text) -> str:
    return normalise(str(text)).casefold() if text not in (None, "") else ""


def words(text) -> set[str]:
    return set(re.findall(r"[\w.%]+", norm(text)))


def overlap(a, b) -> float:
    """1.0 when one normalised text contains the other, else the share of the shorter one's words."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    wa, wb = words(a), words(b)
    return len(wa & wb) / min(len(wa), len(wb)) if wa and wb else 0.0


def singular(text) -> str:
    t = norm(text)
    return t[:-1] if t.endswith("s") and len(t) > 3 else t


def wilson(k: int, n: int) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = k / n
    d = 1 + Z * Z / n
    c = p + Z * Z / (2 * n)
    m = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    return round(max(0.0, (c - m) / d), 4), round(min(1.0, (c + m) / d), 4)    # clamp float noise at 0 and 1


def rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "wilson95": [lo, hi]}


def needed_n(p: float, target: float = TARGET_LB) -> int | None:
    """The smallest n whose Wilson lower bound reaches `target` if precision p holds; None if p <= target."""
    if p <= target:
        return None
    for n in range(1, 100_000):
        if wilson(math.floor(p * n + 1e-9), n)[0] >= target:
            return n
    return None


# --- gold rows ----------------------------------------------------------------------------------------

def read_gold() -> list[dict]:
    rows = []
    for sheet in FACT_SHEETS:
        for line in open(GOLD_DIR / out_name(sheet), encoding="utf-8"):
            rows.append(json.loads(line))
    return rows


def pest_marker(row: dict) -> str | None:
    c = row.get("condition") or ""
    return c.split(";", 1)[0].strip() if ";" in c else None


def gold_condition(row: dict) -> str:
    """where + condition, without the B sheets' leading pest marker ("BPH; ...")."""
    c = row.get("condition") or ""
    if ";" in c:
        c = c.split(";", 1)[1]
    return " ".join(x.strip() for x in (row.get("where") or "", c) if x and x.strip())


def scored(row: dict) -> str | None:
    """Why a gold row is not scored, or None when it is."""
    if row["fact_type"] == "Other":
        return "gold type Other"
    if row["_sheet"] == "B" and pest_marker(row) != "BPH":
        return "section B scores BPH rows only (marker %r)" % pest_marker(row)
    return None


def gold_value(row: dict) -> dict | None:
    """The amount as numbers: {lo, hi, hi_incl, lo_incl, pct}. "<8%" is an exclusive upper bound."""
    s = row.get("amount")
    if s in (None, ""):
        return None
    s = str(s).strip()
    nums = printed_numbers(s)
    if not nums:
        return {"lo": None, "hi": None, "lo_incl": True, "hi_incl": True, "pct": "%" in s, "text": s}
    lo, hi = min(nums), max(nums)
    v = {"lo": lo, "hi": hi, "lo_incl": True, "hi_incl": True, "pct": "%" in s, "text": s}
    if s.startswith("<"):
        v.update(lo=None, hi_incl=False)
    elif s.startswith(">"):
        v.update(hi=None, lo_incl=False)
    return v


# --- atoms ------------------------------------------------------------------------------------------

def latest_runs(source_id: str) -> dict:
    from kg.registry import read_entry
    d = EXTRACTED_DIR / source_id.split(":", 1)[1] / source_version(read_entry(source_id))
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json")) if p.stem != "report"}


def _bounds(raw: dict, base: str, prefix: bool = False):
    lo_k, hi_k = ("min_" + base, "max_" + base) if prefix else (base + "_min", base + "_max")
    return raw.get(lo_k), raw.get(hi_k), raw.get(lo_k + "_inclusive", True), raw.get(hi_k + "_inclusive", True)


FIELD_ATOMS = {   # subtype -> (field base, printed unit, min_/max_ prefix naming)
    "HarvestRule": (("harvest_moisture_pct", "%", False), ("threshing_moisture_pct", "%", False)),
    "DryingSpec": (("target_moisture_pct", "%", False),),
    "StorageRule": (("moisture_pct", "%", True),),
    "IrrigationRule": (("depth_cm", "cm", None),),
    "Spacing": (("seedlings_per_hill", None, False), ("row_cm", "cm", None), ("plant_cm", "cm", None),
                ("hills_per_m2", None, None)),
}


def atoms_of(stem: str, idx: int, rec: dict, run: dict) -> list[dict]:
    """A step 9 fact as single values, each with what the comparison needs, all as printed."""
    raw = rec["fact"]
    unit4 = stem[:4]
    purposes = {singular(p) for p in raw.get("purposes") or []} | {
        singular(p["id"].split(":", 1)[1]) for p in run.get("purposes") or []}
    fact_conds = [c["raw"] for c in raw.get("conditions") or []]
    applic = [x for k in ("varieties", "seasons", "systems", "soils", "stages", "regions") for x in raw.get(k) or []]
    if raw.get("duration_group"):
        applic.append("%s duration" % raw["duration_group"])
    window = [raw.get("storage_term_raw")] + [(raw.get("raw") or {}).get(k) for k in ("storage_months_min",
                                                                                      "storage_months_max")]
    base = {"unit": stem, "raw_index": idx, "fact": "%s#%d" % (unit4, idx), "subtype": raw["subtype"],
            "quote": raw["quote"], "pages": rec["quote_check"]["pdf_pages"], "subheading": rec.get("subheading"),
            "purposes": sorted(purposes), "printed_pests": [x for k in ("pests", "targets", "about")
                                                             for x in raw.get(k) or []]}
    out = []

    def add(kind, key, **kw):
        conds = [c for c in fact_conds + applic + [w for w in window if w] + kw.pop("more_conds", []) if c]
        out.append({**base, "atom": "%s#%d/%s%s" % (unit4, idx, kind, key), "kind": kind, "conditions": conds,
                    "order": None, "alt_group": None, "alt_option": None, "alt_priority": None, "timing": None,
                    "method": None,
                    "unit_printed": None, "per": None, "basis_inferred": False, "lo": None, "hi": None,
                    "lo_incl": True, "hi_incl": True, "detail": "", **kw})

    for si, s in enumerate(raw.get("steps") or []):           # ids use the step's position: options share an order
        step = {"order": s["order"], "alt_group": s.get("alt_group"), "alt_option": s.get("alt_option"),
                "alt_priority": s.get("alt_priority"), "timing": s.get("timing_raw"), "method": s.get("method")}
        more = [s.get("condition_raw")] + [c["raw"] for c in s.get("conditions") or []]
        for ai, a in enumerate(s.get("applies") or []):
            lo, hi = (a["value"], a["value"]) if a.get("value") is not None else (a.get("min"), a.get("max"))
            strength = a.get("conc_raw") or ""
            add("q", "%d.%d" % (si + 1, ai + 1), name=a["target"], lo=lo, hi=hi,
                lo_incl=a.get("min_inclusive", True), hi_incl=a.get("max_inclusive", True),
                unit_printed=a.get("unit"), per=a.get("basis"),
                basis_inferred=bool(a.get("basis_inferred") or a.get("basis_rule")),
                detail=" ".join(x for x in (a.get("formulation"), strength, a.get("raw")) if x),
                more_conds=more, **step)
        if not s.get("applies"):
            add("s", str(si + 1), name=s.get("method") or s.get("operation") or "", more_conds=more, **step)
    for mi, sign in enumerate(raw.get("maturity_signs") or []):
        # a printed sign ("90 % of the panicle are in golden yellow colour"): its number as printed, if any
        nums = printed_numbers(sign)
        pct = bool(nums) and re.search(r"\d\s*%", sign) is not None
        add("m", str(mi + 1), name=sign, lo=nums[0] if nums else None, hi=nums[0] if nums else None,
            unit_printed="%" if pct else None)
    for base_name, unit, prefix in FIELD_ATOMS.get(raw["subtype"], ()):
        if prefix is None:
            lo = hi = raw.get(base_name)
            lo_i = hi_i = True
        else:
            lo, hi, lo_i, hi_i = _bounds(raw, base_name, prefix)
        if lo is None and hi is None:
            continue
        add("v", base_name, name=base_name, lo=lo, hi=hi, lo_incl=lo_i, hi_incl=hi_i, unit_printed=unit)
    for ci, c in enumerate(raw.get("clauses") or []):
        add("c", str(ci + 1), name=c["observation"], lo=c["value"], hi=c["value"], unit_printed=c.get("unit"),
            per=c.get("sampling_unit"), more_conds=[c.get("raw")] + [x["raw"] for x in c.get("conditions") or []])
    for ki, name in enumerate(raw.get("concerns") or []):
        add("k", str(ki + 1), name=name)
    if not out:
        add("f", "", name=raw.get("text_en") or raw.get("summary_en") or "")
    return out


def names_pest(text: str, terms: list[str]) -> bool:
    """A pest term as a whole word or phrase: "BPH" is not inside "WBPH"."""
    t = norm(text)
    return any(re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(term), t) for term in terms)


def in_scope(atom: dict, section: str, bph: list[str]) -> bool:
    if section == "A":
        return True
    if section == "B":
        if names_pest(" | ".join(atom["printed_pests"]), bph):
            return True
        return atom["subtype"] == "Caution" and 63 in atom["pages"] and names_pest(atom["quote"], bph)
    if atom["unit"].startswith("8e1d"):
        return True
    return atom["subheading"] in C_SUBHEADINGS


def section_of(stem: str) -> str | None:
    return next((s for s, units in SECTION_UNITS.items() if any(stem.startswith(u) for u in units)), None)


# --- matching -----------------------------------------------------------------------------------------

def _nums(atom: dict) -> set[float]:
    return {round(v, 6) for v in (atom["lo"], atom["hi"]) if v is not None}


def score(row: dict, atom: dict) -> tuple[float, bool] | None:
    """(score, same page) or None when the atom is not a candidate."""
    q = overlap(row["quote"], atom["quote"])
    same_page = row["pdf_page"] in atom["pages"]
    if q < QUOTE_MIN or (not same_page and q < 1.0):
        return None
    g = gold_value(row)
    gn = {round(v, 6) for v in (g["lo"], g["hi"]) if v is not None} if g else set()
    an = _nums(atom)
    num = 1.0 if gn and gn == an else 0.5 if (gn & an) or (not gn and not an) else 0.0
    gw = words(" ".join(str(row.get(k) or "") for k in ("input", "action")))
    name = len(gw & words(" ".join((atom["name"] or "", atom["detail"])))) / len(gw) if gw else 0.0
    if num == 0 and name == 0:
        return None                                  # the quote alone does not say which value this is
    on = {round(v, 6) for v in printed_numbers(str(row.get("other_values") or ""))}
    other = 0.5 if on and on <= an else 0.0          # "moisture: 20%" beside the row's main amount
    cw = words(gold_condition(row))                  # tells apart the same value for different conditions
    cond = 0.5 * len(cw & words(" ".join(atom["conditions"]))) / len(cw) if cw else 0.0
    return q + 2 * num + name + other + cond + (0.5 if same_page else 0.0), same_page


def match(rows: list[dict], atoms: list[dict]) -> list[tuple[int, int, bool]]:
    """Greedy one-to-one pairs (gold index, atom index, same page), best score first."""
    cands = []
    for gi, row in enumerate(rows):
        section = row["_sheet"]
        bph_row = section == "B" and scored(row) is None
        for ai, atom in enumerate(atoms):
            if section_of(atom["unit"]) != section or (bph_row and atom["other_pest"]):
                continue
            s = score(row, atom)
            if s:
                cands.append((-s[0], gi, ai, s[1]))
    cands.sort()
    used_g, used_a, pairs = set(), set(), []
    for _, gi, ai, same_page in cands:
        if gi not in used_g and ai not in used_a:
            used_g.add(gi)
            used_a.add(ai)
            pairs.append((gi, ai, same_page))
    return sorted(pairs)


# --- comparison -------------------------------------------------------------------------------------

def _show(v) -> str:
    return "" if v is None else ("%g" % v if isinstance(v, float) else str(v))


def _atom_value(a: dict) -> str:
    if a["lo"] is None and a["hi"] is None:
        return ""
    lo, hi = _show(a["lo"]), _show(a["hi"])
    text = lo if lo == hi else "%s-%s" % (lo, hi) if lo and hi else ("<" if not a["hi_incl"] else "<=") + hi if hi \
        else (">" if not a["lo_incl"] else ">=") + lo
    return text


def same_unit(g: str | None, a: str | None) -> bool:
    if not g and not a:
        return True
    if not g or not a:
        return False
    cg, ca = canon_unit(g), canon_unit(a)
    if cg and ca:
        return (cg.unit, cg.factor) == (ca.unit, ca.factor)
    return singular(g) == singular(a)


def same_basis(g: str | None, atom: dict) -> bool:
    a = atom["per"]
    if g in (None, ""):
        return a in (None, "")
    if norm(g) == "not stated":
        return a in (None, "") or atom["basis_inferred"]
    nursery = atom["unit"].startswith("b879")
    seed = atom["subtype"] in ("SeedTreatment",)
    # the gold `per` column names the basis without "per" ("hectare", "kg seed", "20 cents nursery")
    cg = canon_basis(g, nursery, seed) or canon_basis("per " + g, nursery, seed)
    ca = canon_basis(a, nursery, seed) if a else None
    if cg and ca:
        return (cg.basis, cg.area_cents) == (ca.basis, ca.area_cents)
    return bool(a) and norm(g) == norm(a)


def alt_label(atom: dict) -> str | None:
    if atom["alt_priority"] == 1:
        return "preferred"
    if atom["alt_priority"] == 2:
        return "fallback"
    return "option" if atom["alt_group"] is not None else None


def compare(row: dict, atom: dict, same_page: bool) -> list[dict]:
    """Every field on which the gold row and the atom differ, both sides as printed. Nothing is judged."""
    out = []

    def diff(field, gold, extracted, rule):
        out.append({"field": field, "gold": gold, "extracted": extracted, "rule": rule})

    g = gold_value(row)
    a_val = _atom_value(atom)
    if g is None:
        if a_val:
            diff("value", "", a_val, "gold row gives no amount")
    else:
        same = (g["lo"] == atom["lo"] or (g["lo"] is None and atom["lo"] is None)) and \
               (g["hi"] == atom["hi"] or (g["hi"] is None and atom["hi"] is None)) and \
               g["hi_incl"] == atom["hi_incl"] and g["lo_incl"] == atom["lo_incl"]
        if g["lo"] is not None and g["lo"] == g["hi"] and atom["lo"] == atom["hi"] == g["lo"]:
            same = True
        if not same:
            diff("value", g["text"], a_val, "numbers and bounds compared as printed")
    g_unit = "%" if g and g["pct"] else row.get("unit")
    a_unit_ok = same_unit(g_unit, atom["unit_printed"]) or (
        atom["kind"] == "c" and same_unit(g_unit, atom["name"]))     # a clause counts its observation ("hoppers")
    if not a_unit_ok:
        diff("unit", g_unit or "", atom["unit_printed"] or "", "step 10 unit table, else the same word")
    if g and g["pct"] and row.get("unit") and singular(row["unit"]) not in norm(atom["name"]).replace("_", " "):
        diff("unit", "measure: %s" % row["unit"], atom["name"], "gold names what the % measures")
    if not same_basis(row.get("per"), atom):
        diff("basis", row.get("per") or "", (atom["per"] or "") + (" (inferred)" if atom["basis_inferred"] else ""),
             "step 10 basis table (gold `per` read with 'per' in front), 'not stated' = no printed basis")
    gc, ac = norm(gold_condition(row)), norm(" | ".join(atom["conditions"]))
    if (gc or ac) and not (gc and gc in ac):
        diff("condition", gold_condition(row), " | ".join(atom["conditions"]), "gold text must appear in ours")
    gl = row.get("alternative") if row.get("alternative") in ALT_LABELS else None
    if gl != alt_label(atom):
        diff("alternative", row.get("alternative") or "", alt_label(atom) or "",
             "option / preferred / fallback against alt_group and alt_priority")
    gp = singular(row.get("purpose")) if row.get("purpose") else None
    if (gp and gp not in atom["purposes"]) or (not gp and atom["purposes"]):
        diff("purpose", row.get("purpose") or "", ", ".join(atom["purposes"]), "text and section purposes")
    if row["fact_type"] != atom["subtype"]:
        diff("subtype", row["fact_type"], atom["subtype"], "")
    gt, at = norm(row.get("timing")), norm(atom["timing"])
    if (gt or at) and gt != at:
        diff("timing", row.get("timing") or "", atom["timing"] or "", "exact normalised text")
    if not same_page:
        diff("page", str(row["pdf_page"]), ", ".join(map(str, atom["pages"])), "the quote is on another page")
    return out


def granularity(rows, atoms, pairs) -> tuple[list[dict], set[int], set[int]]:
    """Where the gold set and the extraction cut the same text into a different number of values. The
    unmatched partner is listed as a granularity disagreement on the gold row and kept out of misses and
    extras:
      - one gold row names two values the extraction split ("FYM or compost": FYM, compost);
      - one gold row covers the same value in several extracted facts ("short and medium duration");
      - one gold row carries a second value in `other_values` ("moisture: 20%") that is an atom of its own;
      - a gold row's quote holds a value-less atom of the matched fact (a maturity sign);
      - one extracted atom holds several gold rows;
      - a gold row is the method every step of a fact shares ("Direct spray towards the base ...")."""
    by_g = {gi: ai for gi, ai, _ in pairs}
    by_a = {ai: gi for gi, ai, _ in pairs}
    found, covered_atoms, covered_rows = [], set(), set()

    def note(gi, ai, gold, extracted, rule):
        found.append({"gi": gi, "ai": ai, "field": "granularity", "gold": gold, "extracted": extracted, "rule": rule})

    for ai, atom in enumerate(atoms):
        if ai in by_a or not atom["name"]:
            continue
        for gi, aj in by_g.items():
            other, row = atoms[aj], rows[gi]
            if other["fact"] == atom["fact"] and norm(atom["name"]) in norm(row.get("input")) \
                    and norm(atom["name"]) != norm(other["name"]):
                note(gi, ai, row.get("input") or "", "separate atoms: %s; %s" % (other["name"], atom["name"]),
                     "one gold row names several values")
            elif other["fact"] != atom["fact"] and norm(other["quote"]) == norm(atom["quote"]) \
                    and norm(other["name"]) == norm(atom["name"]) and (other["lo"], other["hi"]) == (atom["lo"], atom["hi"]):
                note(gi, ai, row.get("input") or "", "the same value in facts %s and %s" % (other["fact"], atom["fact"]),
                     "one gold row covers several extracted facts")
            elif norm(other["quote"]) == norm(atom["quote"]) and other["subtype"] == atom["subtype"] and _nums(atom) \
                    and _nums(atom) <= {round(v, 6) for v in printed_numbers(str(row.get("other_values") or ""))}:
                note(gi, ai, row.get("other_values"), "%s %s is an atom of its own" % (atom["name"], _atom_value(atom)),
                     "one gold row carries a second value in other_values")
            elif other["fact"] == atom["fact"] and not _nums(atom) and atom["kind"] in ("m", "f") \
                    and norm(atom["name"]) in norm(row["quote"]):           # steps: the context rule in run()
                note(gi, ai, row.get("input") or "", "%s is an atom of its own" % atom["name"],
                     "the gold row's quote holds a value-less atom of the same fact")
            else:
                continue
            covered_atoms.add(ai)
            break
    for gi, row in enumerate(rows):
        if gi in by_g:
            continue
        for gj, aj in by_g.items():
            atom = atoms[aj]
            if row.get("input") and rows[gj]["quote"] == row["quote"] and norm(row["input"]) in norm(atom["name"]) \
                    and norm(row["input"]) != norm(atom["name"]):
                note(gi, aj, row["input"], "one atom: %s" % atom["name"], "one atom holds several gold rows")
                covered_rows.add(gi)
                break
        else:
            q = norm(row["quote"]).rstrip(".")
            sharing = [ai for ai, a in enumerate(atoms) if a["method"] and section_of(a["unit"]) == row["_sheet"]
                       and q and q == norm(a["method"]).rstrip(".") and row["pdf_page"] in a["pages"]]
            if sharing:
                facts = sorted({atoms[ai]["fact"] for ai in sharing})
                note(gi, sharing[0], row.get("input") or row["quote"],
                     "the method of %d extracted steps (%s)" % (len(sharing), ", ".join(facts)),
                     "a gold row is the method every step shares")
                covered_rows.add(gi)
    return found, covered_atoms, covered_rows


def group_structure(rows, atoms, pairs) -> list[dict]:
    """Gold rows sharing a quote and step as one group of alternatives must sit in one extracted group."""
    groups = defaultdict(list)
    for gi, ai, _ in pairs:
        r = rows[gi]
        if r.get("alternative") in ALT_LABELS:
            groups[(r["_sheet"], r["quote"], r.get("step"))].append((gi, ai))
    out = []
    for members in groups.values():
        keys = {(atoms[ai]["fact"], atoms[ai]["order"], atoms[ai]["alt_group"]) for _, ai in members}
        if len(members) > 1 and len(keys) > 1:
            for gi, ai in members:
                out.append({"gi": gi, "ai": ai, "field": "alternative",
                            "gold": "one group: %s" % ", ".join(rows[g]["fact_id"] for g, _ in members),
                            "extracted": "groups: %s" % "; ".join(sorted("%s step %s alt %s" % k for k in keys)),
                            "rule": "gold rows sharing quote and step form one group"})
    return out


# --- adjudication ---------------------------------------------------------------------------------

def read_adjudications() -> tuple[dict, list[dict]]:
    """(verdicts on disagreements keyed by gold_id + field, verdicts on extras). An extra (field "extra",
    no gold_id) is an extracted atom with no gold row, named by `name` and `quote` rather than its atom id,
    which shifts when a unit is re-extracted; `atom` is kept for reading only."""
    if not ADJUDICATIONS.exists():
        return {}, []
    pairs, extras = {}, []
    with open(ADJUDICATIONS, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["verdict"] not in VERDICTS:
                raise ValueError("%s: verdict %r for %s %s is not one of %s"
                                 % (ADJUDICATIONS.name, row["verdict"], row["gold_id"], row["field"], VERDICTS))
            if row["field"] == "extra":
                if row["gold_id"] or not row.get("name") or not row.get("quote"):
                    raise ValueError("%s: an extra needs name and quote and no gold_id: %s" % (ADJUDICATIONS.name, row))
                extras.append(row)
            else:
                pairs[(row["gold_id"], row["field"])] = row
    return pairs, extras


def judged_extras(atoms: list[dict], used: set[int], extras: list[dict]) -> dict[int, dict]:
    """Unmatched in-scope atoms a person judged, by name and quote: atom index -> adjudication row."""
    out = {}
    for i, a in enumerate(atoms):
        if i in used or not a["in_scope"]:
            continue
        for e in extras:
            if norm(e["name"]) == norm(a["name"]) and norm(e["quote"]) == norm(a["quote"]):
                out[i] = e
    return out


def pair_status(diffs: list[dict], adjudications: dict, gold_id: str) -> str:
    """agree, wrong or open: a disagreement counts only once a person has adjudicated it."""
    if not diffs:
        return "agree"
    verdicts = [adjudications.get((gold_id, d["field"]), {}).get("verdict") for d in diffs]
    if "gold" in verdicts:
        return "wrong"
    if all(v in ("extraction", "both") for v in verdicts):
        return "agree"
    return "open"


# --- the run ----------------------------------------------------------------------------------------

def run(entry) -> dict:
    sid = entry.id.split(":", 1)[1]
    runs = latest_runs(entry.id)
    validated = {(r["unit_id"][-12:], r["raw_index"]) for r in map(json.loads, open(
        NORMALIZED_DIR / sid / "facts.jsonl", encoding="utf-8"))}
    verified = {(r["unit_id"][-12:], r["raw_index"]): r for r in map(json.loads, open(
        VERIFIED_DIR / sid / "facts.jsonl", encoding="utf-8"))}
    terms = pest_terms()
    bph = sorted({norm(t) for t in terms.get("pest:brown_planthopper", ())} | {"bph"})
    other_pests = [sorted({norm(t) for t in ts}) for pid, ts in sorted(terms.items()) if pid != "pest:brown_planthopper"]
    rows = read_gold()
    atoms, skipped = [], []
    for stem, r in runs.items():
        if section_of(stem) is None:
            continue
        for i, rec in enumerate(r["facts"]):
            if rec.get("fact"):
                for a in atoms_of(stem, i, rec, r):
                    a["validated"] = (stem, i) in validated
                    a["section"] = section_of(stem)
                    a["in_scope"] = in_scope(a, a["section"], bph)
                    # names a specific seeded pest and not BPH: a BPH gold row never matches it (the WBPH
                    # row's products); a generic "Pest" names no pest
                    printed = " | ".join(a["printed_pests"])
                    a["other_pest"] = not names_pest(printed, bph) and any(
                        names_pest(printed, others) for others in other_pests)
                    atoms.append(a)
        for x in r.get("not_extracted") or []:
            if x.get("entry"):
                skipped.append({"unit": stem, "quote": x["entry"]["quote"], "reason": x["entry"].get("reason"),
                                "section": section_of(stem)})
    pairs = match(rows, atoms)
    adjud, extra_verdicts = read_adjudications()
    gran, covered_atoms, covered_rows = granularity(rows, atoms, pairs)
    structure = group_structure(rows, atoms, pairs)
    extra = defaultdict(list)
    for d in gran + structure:
        extra[d["gi"]].append({k: d[k] for k in ("field", "gold", "extracted", "rule")})
    matched = {}
    for gi, ai, same_page in pairs:
        diffs = compare(rows[gi], atoms[ai], same_page) + extra.pop(gi, [])
        matched[gi] = {"ai": ai, "diffs": diffs, "status": pair_status(diffs, adjud, rows[gi]["fact_id"])}
    for gi, diffs in extra.items():                          # granularity rows matched through a partner
        ai = next(d["ai"] for d in gran if d["gi"] == gi)
        matched[gi] = {"ai": ai, "diffs": diffs, "status": pair_status(diffs, adjud, rows[gi]["fact_id"]),
                       "granularity": True}
    outcome = []
    for gi, row in enumerate(rows):
        why = scored(row)
        m = matched.get(gi)
        skip = None
        if not m:
            skip = max(((overlap(row["quote"], s["quote"]), s) for s in skipped if s["section"] == row["_sheet"]),
                       key=lambda x: x[0], default=(0, None))
            skip = skip[1] if skip[0] >= QUOTE_MIN else None
        outcome.append({"gi": gi, "row": row, "scored": why is None, "unscored_reason": why, "match": m,
                        "not_extracted": skip})
    unscored_atoms = {m["ai"] for o in outcome if not o["scored"] and (m := o["match"])}
    # a step without a value, in a fact the gold set annotated, is that fact's context unless a gold row
    # names it ("soak the seeds in water" beside the Carbendazim dose): listed, not counted as an extra
    used = {o["match"]["ai"] for o in outcome if o["match"]} | covered_atoms
    annotated = {atoms[i]["fact"] for i in used}
    context = {i for i, a in enumerate(atoms) if a["kind"] == "s" and i not in used and a["fact"] in annotated}
    judged = judged_extras(atoms, used | context, extra_verdicts)
    covered_by = {}                     # a granularity-covered atom -> the gold row it is covered by (the first)
    for d in gran:
        if d["ai"] in covered_atoms:
            covered_by.setdefault(d["ai"], d["gi"])
    return {"rows": rows, "atoms": atoms, "outcome": outcome, "verified": verified, "adjudications": adjud,
            "covered_atoms": covered_atoms, "covered_by": covered_by, "unscored_atoms": unscored_atoms | context,
            "context_atoms": context, "judged_extras": judged, "extra_verdicts": extra_verdicts}


def _counts(outcome, atoms, covered_by, unscored_atoms, judged, key_row, key_atom) -> dict:
    """Recall and precision for the rows and atoms selected by key_row / key_atom. An extra judged
    "extraction" or "both" by a person counts as correct (the gold set lacks it). A granularity-covered
    atom takes the status of the gold row it is covered by. Agreeing precision is a range like recall:
    the lower bound counts "unclear" (open) as not agreeing, the upper bound as agreeing."""
    rows = [o for o in outcome if o["scored"] and key_row(o["row"])]
    ne = [o for o in rows if not o["match"] and o["not_extracted"]]
    found = [o for o in rows if o["match"]]
    agree_lb = sum(o["match"]["status"] == "agree" for o in found)
    agree_ub = sum(o["match"]["status"] in ("agree", "open") for o in found)
    pipeline = sum(atoms[o["match"]["ai"]]["validated"] for o in found)
    matched_atoms = {o["match"]["ai"] for o in found}
    scope = [i for i, a in enumerate(atoms) if a["in_scope"] and key_atom(a) and i not in unscored_atoms]
    confirmed = {i for i, e in judged.items() if e["verdict"] in ("extraction", "both")}
    hit = [i for i in scope if i in matched_atoms or i in covered_by or i in confirmed]
    by_atom = {o["match"]["ai"]: o["match"]["status"] for o in found}
    by_row = {o["gi"]: o["match"]["status"] for o in outcome if o["match"]}

    def status(i):
        if i in by_atom:
            return by_atom[i]
        if i in covered_by:
            return by_row.get(covered_by[i])
        return "agree" if i in confirmed else None

    hit_agree = [i for i in scope if status(i) == "agree"]
    hit_open = [i for i in scope if status(i) == "open"]
    n_strict, n_lenient = len(rows), len(rows) - len(ne)
    return {
        "gold_rows": len(rows), "found": len(found), "not_extracted": len(ne), "missed": len(rows) - len(found),
        "recall_found_strict": rate(len(found), n_strict),
        "recall_found_lenient": rate(len(found), n_lenient),
        "recall_pipeline_strict": rate(pipeline, n_strict),
        "recall_agree": {"lower": rate(agree_lb, n_strict), "upper": rate(agree_ub, n_strict)},
        "atoms_in_scope": len(scope), "atoms_matched": len(hit),
        "extras_confirmed": len([i for i in scope if i in confirmed]),
        "precision_found": rate(len(hit), len(scope)),
        "precision_agree_lower": rate(len(hit_agree), len(scope)),
        "precision_agree_upper": rate(len(hit_agree) + len(hit_open), len(scope)),
    }


def metrics(res: dict) -> dict:
    out, atoms = res["outcome"], res["atoms"]
    args = (out, atoms, res["covered_by"], res["unscored_atoms"], res["judged_extras"])
    by_section = {s: _counts(*args, lambda r, s=s: r["_sheet"] == s, lambda a, s=s: a["section"] == s)
                  for s in SECTION_UNITS}
    by_section["all"] = _counts(*args, lambda r: True, lambda a: True)
    types = sorted({o["row"]["fact_type"] for o in out if o["scored"]} | {a["subtype"] for a in atoms if a["in_scope"]})
    by_subtype = {t: _counts(*args, lambda r, t=t: r["fact_type"] == t, lambda a, t=t: a["subtype"] == t)
                  for t in types}
    return {"sections": by_section, "subtypes": by_subtype}


def fact_labels(res: dict) -> dict:
    """(unit stem, raw_index) -> correct | wrong | open, from the fact's matched scored gold rows."""
    by_fact = defaultdict(list)
    for o in res["outcome"]:
        if o["scored"] and o["match"]:
            a = res["atoms"][o["match"]["ai"]]
            by_fact[(a["unit"], a["raw_index"])].append(o["match"]["status"])
    return {k: "wrong" if "wrong" in v else "open" if "open" in v else "correct" for k, v in by_fact.items()}


def calibration(res: dict) -> dict:
    labels = fact_labels(res)
    facts = []
    for key, label in labels.items():
        v = res["verified"].get(key)
        if v and v["verifier_score"] is not None:
            facts.append({"fact": "%s#%d" % (key[0][:4], key[1]), "label": label, "score": v["verifier_score"],
                          "status": v["status"],
                          "claims": [c["p_yes"] for c in v["claims"] if not c["control"] and c["p_yes"] is not None]})
    pops = {"a_all_matched": [(f["score"], f["label"]) for f in facts],
            "b_extracted_only": [(f["score"], f["label"]) for f in facts if f["status"] == "extracted"],
            "c_claims": [(p, f["label"]) for f in facts for p in f["claims"]]}
    table = {}
    for name, items in pops.items():
        rows = []
        for t in CUTOFFS:
            above = [lab for s, lab in items if s >= t]
            n, k, op = len(above), above.count("correct"), above.count("open")
            rows.append({"cutoff": t, "n": n, "correct": k, "open": op, "wrong": above.count("wrong"),
                         "coverage": round(n / len(items), 4) if items else None,
                         "precision_lower": rate(k, n), "precision_upper": rate(k + op, n)})
        table[name] = {"n": len(items), "cutoffs": rows}
    b = table["b_extracted_only"]["cutoffs"]
    ok = [r for r in b if r["n"] and r["precision_lower"]["wilson95"][0] >= TARGET_LB]
    proposal = {"rule": "lowest cut-off whose Wilson 95 %% lower bound on population (b)'s precision, open "
                        "disagreements counted wrong, is >= %.2f" % TARGET_LB,
                "threshold": ok[0]["cutoff"] if ok else None,
                "message": ("propose auto_verified_threshold = %g (not written to config/verify.toml)" % ok[0]["cutoff"])
                if ok else "no threshold yet"}
    if not ok:
        proposal.update(rows_needed(res, facts, table))
    return {"facts": facts, "populations": table, "proposal": proposal}


def rows_needed(res: dict, facts: list[dict], table: dict) -> dict:
    """How many gold rows a threshold needs, if the precision observed so far holds."""
    b = [f for f in facts if f["status"] == "extracted"]
    scored_found = sum(1 for o in res["outcome"] if o["scored"] and o["match"])
    rows_per_fact = scored_found / max(1, len(fact_labels(res)))
    share_extracted = len(b) / max(1, len(facts))
    out = {"rows_per_matched_fact": round(rows_per_fact, 2), "share_of_matched_facts_extracted": round(share_extracted, 3)}
    plans = []
    for r in table["b_extracted_only"]["cutoffs"]:
        if not r["n"]:
            continue
        for label, k in (("open counted wrong", r["correct"]), ("open counted right", r["correct"] + r["open"])):
            p = k / r["n"]
            n = needed_n(p)
            facts_needed = None if n is None else math.ceil(n / max(r["coverage"], 1e-9))
            plans.append({"cutoff": r["cutoff"], "assuming": label, "observed_precision": round(p, 4),
                          "facts_above_cutoff_needed": n,
                          "gold_rows_needed": None if n is None else
                          math.ceil(facts_needed / max(share_extracted, 1e-9) * rows_per_fact)})
    out["plans"] = plans
    best = [p for p in plans if p["gold_rows_needed"]]
    out["fewest_gold_rows"] = min(best, key=lambda p: p["gold_rows_needed"]) if best else None
    return out


def controls(res: dict, calib: dict) -> dict:
    ctl = [(c["p_yes"], c.get("control_kind", "number")) for v in res["verified"].values() for c in v["claims"]
           if c["control"] and c["p_yes"] is not None]
    rows = []
    for t in CUTOFFS:
        acc = [k for p, k in ctl if p >= t]
        rows.append({"cutoff": t, "accepted": len(acc), "of": len(ctl), "false_accept": rate(len(acc), len(ctl)),
                     "by_kind": dict(Counter(acc))})
    by_kind = defaultdict(list)
    for p, k in ctl:
        by_kind[k].append(p)
    claims = calib["populations"]["c_claims"]
    labelled = defaultdict(list)
    for f in calib["facts"]:
        for p in f["claims"]:
            labelled[f["label"]].append(p)

    def summary(ps):
        ps = sorted(ps)
        return {"n": len(ps), "min": ps[0], "median": ps[len(ps) // 2], "max": ps[-1]} if ps else {"n": 0}
    zero_ok = 1 - 0.05 ** (1 / len(ctl)) if ctl else None
    return {"n": len(ctl), "by_kind": {k: summary(v) for k, v in sorted(by_kind.items())},
            "gold_labelled_claims": {k: summary(v) for k, v in sorted(labelled.items())},
            "cutoffs": rows, "claims_population": claims["n"],
            "exact_95_upper_if_none_accepted": round(zero_ok, 4) if zero_ok else None,
            "controls_needed_for_5pct_upper_with_none_accepted": math.ceil(math.log(0.05) / math.log(0.95))}


def disagreements(res: dict) -> list[dict]:
    out = []
    for o in res["outcome"]:
        m = o["match"]
        if not m:
            continue
        a, row = res["atoms"][m["ai"]], o["row"]
        for d in m["diffs"]:
            adj = res["adjudications"].get((row["fact_id"], d["field"]), {})
            out.append({"gold_id": row["fact_id"], "section": row["_sheet"], "scored": "yes" if o["scored"] else "no",
                        "pdf_page": row["pdf_page"], "field": d["field"], "gold_value": d["gold"],
                        "extracted_value": d["extracted"], "rule": d["rule"], "atom": a["atom"],
                        "fact_status": "validated" if a["validated"] else "held",
                        "gold_type": row["fact_type"], "extracted_subtype": a["subtype"],
                        "gold_input": row.get("input") or "", "extracted_name": a["name"],
                        "gold_quote": row["quote"], "extracted_quote": a["quote"],
                        "verdict": adj.get("verdict", ""), "note": adj.get("note", "")})
    return out


def unmatched(res: dict) -> list[dict]:
    out = []
    for o in res["outcome"]:
        if not o["match"]:
            row = o["row"]
            ne = o["not_extracted"]
            out.append({"kind": "gold row not found", "id": row["fact_id"], "section": row["_sheet"],
                        "scored": "yes" if o["scored"] else "no (%s)" % o["unscored_reason"],
                        "pdf_page": row["pdf_page"], "type": row["fact_type"], "name": row.get("input") or "",
                        "value": row.get("amount") or "",
                        "note": "step 9 not-extracted: %s" % ne["reason"] if ne else "",
                        "quote": row["quote"]})
    matched = {o["match"]["ai"] for o in res["outcome"] if o["match"]}
    for i, a in enumerate(res["atoms"]):
        if a["in_scope"] and i not in matched and i not in res["covered_atoms"]:
            context = i in res["context_atoms"]
            judged = res["judged_extras"].get(i)
            kind = "context step (not counted)" if context else "extracted atom with no gold row"
            if judged:
                kind = "extracted atom with no gold row, adjudicated %s" % judged["verdict"]
            out.append({"kind": kind, "id": a["atom"], "section": a["section"], "scored": "no" if context else "yes",
                        "pdf_page": ", ".join(map(str, a["pages"])), "type": a["subtype"],
                        "name": a["name"], "value": _atom_value(a),
                        "note": ("validated" if a["validated"] else "held") + ("; %s" % judged["note"] if judged else ""),
                        "quote": a["quote"]})
    return out


def stale_adjudications(res: dict, dis: list[dict]) -> list[dict]:
    """Recorded verdicts that no longer meet anything (re-extraction changed or cleared the disagreement, or the
    extra atom is gone). They are kept in the file and listed here; nothing is deleted or re-applied."""
    current = {(d["gold_id"], d["field"]) for d in dis}
    out = [{"gold_id": g, "field": f, "verdict": row["verdict"], "note": row.get("note", ""),
            "reason": "no current disagreement for this gold row and field"}
           for (g, f), row in sorted(res["adjudications"].items()) if (g, f) not in current]
    met = {(norm(e["name"]), norm(e["quote"])) for e in res["judged_extras"].values()}
    out += [{"gold_id": "", "field": "extra", "verdict": e["verdict"], "note": e.get("note", ""), "name": e["name"],
             "reason": "no extracted atom with this name and quote"}
            for e in res.get("extra_verdicts") or [] if (norm(e["name"]), norm(e["quote"])) not in met]
    return out


def report(res: dict) -> dict:
    calib = calibration(res)
    dis = disagreements(res)
    rows = res["rows"]
    odd = [{"gold_id": r["fact_id"], "alternative": r["alternative"]} for r in rows
           if r.get("alternative") not in (None, "note", *ALT_LABELS)]
    return {
        "gold": {"rows": len(rows), "scored": sum(o["scored"] for o in res["outcome"]),
                 "unscored": dict(Counter(o["unscored_reason"] for o in res["outcome"] if not o["scored"])),
                 "oddities": odd},
        "atoms": {"total": len(res["atoms"]), "in_scope": sum(a["in_scope"] for a in res["atoms"]),
                  "context_steps_not_counted": len(res["context_atoms"])},
        "precision_scope": PRECISION_SCOPE,
        "metrics": metrics(res),
        "not_extracted_rows": [{"gold_id": o["row"]["fact_id"], "scored": o["scored"], "reason": o["not_extracted"]["reason"]}
                               for o in res["outcome"] if not o["match"] and o["not_extracted"]],
        "missed_rows": [o["row"]["fact_id"] for o in res["outcome"] if o["scored"] and not o["match"]
                        and not o["not_extracted"]],
        "disagreements": {"count": len(dis), "rows": len({d["gold_id"] for d in dis}),
                          "by_field": dict(Counter(d["field"] for d in dis)),
                          "adjudicated": sum(bool(d["verdict"]) for d in dis),
                          "patterns": [{"field": f, "gold": g, "extracted": e, "rows": n} for (f, g, e), n in
                                       Counter((d["field"], d["gold_value"], d["extracted_value"]) for d in dis).most_common(15)]},
        "stale_adjudications": stale_adjudications(res, dis),
        "calibration": calib,
        "controls": controls(res, calib),
    }
