"""Extraction (step 9): one model call per unit, output in the raw model (kg.extract.model).

  uv run python -m kg.extract find    source:tnau_agriculture_2020 "Wet nursery"
  uv run python -m kg.extract prepare source:tnau_agriculture_2020 --unit <unit_id> --model <name> [--prompt v2]
  uv run python -m kg.extract ingest  source:tnau_agriculture_2020 --unit <unit_id> --model <name> --response <file>
  uv run python -m kg.extract report  source:tnau_agriculture_2020 [--prompt v2]
  uv run python -m kg.extract compare source:tnau_agriculture_2020 --unit <unit_id> --from v1 --to v2

No model is called from here: `prepare` writes the filled prompt, a runner (a person, Claude Code,
or later a Sarvam or API runner) answers it, and `ingest` checks and stores the answer.
Input: data/units/<id>/units.jsonl and data/tables/<id>/tables.jsonl (run kg.segment and kg.tables).
Output: data/extracted/<id>/<prompt version>/ (gitignored). Checks here: the answer parses into the
raw model under its prompt version, every quote is found in the unit text, and (v2) every text line
and table row is quoted by a fact or listed as not extracted. Failures are saved and reported,
never fixed.
"""

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from kg.registry import ROOT
from kg.schema.vocab import (CONDITION_VARIABLES, Anchor, CautionKind, CommodityForm, ConditionOp, ControlClass,
                             DoseBasis, DurationGroup, Grade, LimitType, OffsetUnit, OperationType,
                             QualityParameter, Subtype, WeatherAdvice, WindowFor)
from kg.segment import UNITS_DIR
from kg.tables import TABLES_DIR

from .model import FACT, NotExtracted
from .quotes import QuoteIndex, normalise
from .versions import LATEST, VERSIONS, version_problems

EXTRACTED_DIR = ROOT / "data" / "extracted"
PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = LATEST
SLOTS = ("{{subtypes}}", "{{vocabularies}}", "{{default_scope}}", "{{unit}}")
COVERED_KINDS = ("text", "row")          # segments that must be quoted or listed as not extracted


class ExtractError(Exception):
    pass


def slug(entry) -> str:
    return entry.id.split(":", 1)[1]


def file_stem(unit_id: str) -> str:
    """unit:<source slug>:<hash>[-n] -> <hash>[-n] (Windows file names cannot hold ':')."""
    return unit_id.split(":", 2)[2]


def load_units(entry) -> list[dict]:
    path = UNITS_DIR / slug(entry) / "units.jsonl"
    if not path.exists():
        raise ExtractError("%s not found: run kg.segment first" % path)
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def load_tables(entry) -> dict[str, dict]:
    """Stitched tables keyed by every part ref."""
    path = TABLES_DIR / slug(entry) / "tables.jsonl"
    out = {}
    if path.exists():
        for line in open(path, encoding="utf-8"):
            t = json.loads(line)
            for ref in t["table_refs"]:
                out[ref] = t
    return out


def get_unit(entry, unit_id: str) -> dict:
    hits = [u for u in load_units(entry) if u["id"] == unit_id]
    if len(hits) != 1:
        raise ExtractError("unit %s found %d times in units.jsonl" % (unit_id, len(hits)))
    return hits[0]


# --- rendering ---------------------------------------------------------------------------

def _pages(lo, hi) -> str:
    return str(lo) if lo == hi else "%s-%s" % (lo, hi)


def _row_ref(row: list[dict]) -> str:
    """A row's ref; a row merged across a page break names every piece (kg.tables.stitch)."""
    ref = "%s row %d" % (row[0]["part_ref"], row[0]["row"])
    pieces = {(c["part_ref"], c["row"]) for cell in row for c in cell.get("continued_from") or []}
    for part, r in sorted(pieces):
        ref += " + %s row %d" % (part, r)
    return ref


def render_unit(entry, unit: dict, tables: dict[str, dict]) -> tuple[str, list[dict]]:
    """The unit as the model sees it, and the text segments the quote check searches."""
    lines, segments, done = [], [], set()
    for it in unit["items"]:
        page = it.get("pdf_page")
        base = {"ref": it["ref"], "pdf_page": page, "printed_page": it.get("printed_page"),
                "subheading": it.get("subheading")}
        if it["kind"] == "subheading":
            lines.append("[p.%s] ## %s" % (page, it["text"]))
            segments.append({**base, "kind": "subheading", "text": it["text"]})
        elif it["kind"] == "text":
            lines.append("[p.%s] %s" % (page, it["text"]))
            segments.append({**base, "kind": "text", "text": it["text"]})
        elif it["kind"] == "table":
            if it["ref"] in done:
                continue
            t = tables.get(it["ref"])
            if t is None:
                raise ExtractError("table %s of unit %s is not in tables.jsonl: run kg.tables first"
                                   % (it["ref"], unit["id"]))
            done.update(t["table_refs"])
            page_of = dict(zip(t["table_refs"], t["pdf_pages"]))
            lines.append("[p.%s] TABLE %s" % (_pages(min(t["pdf_pages"]), max(t["pdf_pages"])),
                                               " + ".join(t["table_refs"])))
            header = " | ".join(t["header"] or [])
            lines.append("[%s header] %s" % (t["table_refs"][0], header))
            segments.append({**base, "kind": "header", "ref": t["table_refs"][0], "text": header})
            for row in t["rows"]:
                ref, part = _row_ref(row), row[0]["part_ref"]
                text = " | ".join(c["text"] or "" for c in row)
                lines.append("[%s] %s" % (ref, text))
                # a row merged across a page break lies on every page its pieces came from
                pieces = {part} | {c["part_ref"] for cell in row for c in cell.get("continued_from") or []}
                pages = sorted({page_of[p] for p in pieces})
                segments.append({**base, "kind": "row", "ref": ref, "pdf_page": page_of[part], "pdf_pages": pages,
                                 "printed_page": entry.printed_page(page_of[part]),
                                 "printed_pages": [entry.printed_page(p) for p in pages], "text": text})
    lo, hi = unit["pdf_pages"]
    printed = [p for p in (entry.printed_page(lo), entry.printed_page(hi)) if p]
    head = ["SECTION: %s" % unit["section_path"], "CHAPTER: %s" % unit["chapter"]["title"],
            "PAGES: PDF %s%s" % (_pages(lo, hi), " (printed %s)" % _pages(*printed) if len(printed) == 2 else ""),
            "", "TEXT:"]
    return "\n".join(head + lines), segments


def render_default_scope(entry, unit: dict) -> str:
    rules = {r.label(): r for r in entry.default_scope}
    out = []
    for label in unit["default_scope"]:
        r = rules[label]
        out.append('- RULE: %s\n  QUOTE (PDF p. %d): "%s"' % (label, r.pdf_page, r.quote))
    return "\n".join(out) or "none"


def render_vocabularies(version: str = PROMPT_VERSION) -> str:
    """The fixed lists the prompt shows. v5 adds the QualitySpec lists and v6 the SowingWindow one; earlier
    versions render exactly as they did, so their kept prompts stay byte-identical."""
    lists = [("operation", OperationType), ("anchor", Anchor), ("offset_unit", OffsetUnit),
             ("op", ConditionOp), ("duration_group", DurationGroup), ("dose_basis", DoseBasis),
             ("control_class", ControlClass), ("advice", WeatherAdvice), ("kind", CautionKind)]
    if int(version[1:]) >= 5:
        lists += [("commodity_form", CommodityForm), ("grade", Grade), ("limit_type", LimitType),
                  ("quality parameter", QualityParameter)]
    if int(version[1:]) >= 6:
        lists += [("window_for", WindowFor)]
    lines = ["- %s: %s" % (name, ", ".join(v.value for v in enum)) for name, enum in lists]
    lines.append("- condition variable (unit, value type):")
    for name, spec in CONDITION_VARIABLES.items():
        lines.append("  - %s (%s, %s)" % (name, spec.unit.value if spec.unit else "no unit",
                                         spec.value_type.value))
    return "\n".join(lines)


def prompt_template(version: str = PROMPT_VERSION) -> tuple[str, str]:
    if version not in VERSIONS:
        raise ExtractError("unknown prompt version %r" % version)
    raw = (PROMPTS_DIR / ("%s.md" % version)).read_bytes()
    return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()


def build(entry, unit: dict, model: str, tables: dict | None = None, version: str = PROMPT_VERSION) -> dict:
    """The filled prompt, the quote segments and the cache key for one unit."""
    template, prompt_sha = prompt_template(version)
    for slot in SLOTS:
        if template.count(slot) != 1:
            raise ExtractError("prompt %s must contain %s exactly once" % (version, slot))
    unit_text, segments = render_unit(entry, unit, load_tables(entry) if tables is None else tables)
    scope = render_default_scope(entry, unit)
    unit_sha = hashlib.sha256(("%s\n\n%s" % (scope, unit_text)).encode("utf-8")).hexdigest()
    key = hashlib.sha256(json.dumps([unit_sha, version, prompt_sha, model]).encode()).hexdigest()
    prompt = (template.replace("{{subtypes}}", ", ".join(s.value for s in Subtype))
              .replace("{{vocabularies}}", render_vocabularies(version))
              .replace("{{default_scope}}", scope).replace("{{unit}}", unit_text))
    return {"prompt": prompt, "segments": segments, "prompt_sha256": prompt_sha, "version": version,
            "unit_text_sha256": unit_sha, "cache_key": key}


def out_dir(entry, version: str = PROMPT_VERSION) -> Path:
    return EXTRACTED_DIR / slug(entry) / version


def out_path(entry, unit_id: str, version: str = PROMPT_VERSION) -> Path:
    return out_dir(entry, version) / ("%s.json" % file_stem(unit_id))


def cached(entry, unit: dict, built: dict) -> Path | None:
    path = out_path(entry, unit["id"], built["version"])
    if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("cache_key") == built["cache_key"]:
        return path
    return None


# --- checking an answer ---------------------------------------------------------------------

def _errors(e: ValidationError) -> list[str]:
    return ["%s: %s" % (".".join(map(str, x["loc"])) or "(fact)", x["msg"]) for x in e.errors()]


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", normalise(text)) if s]


def check_answer(text: str, segments: list[dict], version: str = PROMPT_VERSION) -> dict:
    """Parse into the raw model under the prompt version, find every quote and (v2) check that
    every text line and table row is quoted. Nothing is corrected."""
    v = VERSIONS[version]
    empty = {"facts": [], "not_extracted": [], "coverage": None}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return {**empty, "parse_error": "not JSON: %s" % e}
    if v.envelope == "list":
        if not isinstance(data, list):
            return {**empty, "parse_error": "the answer must be a JSON list of facts"}
        items, skipped = data, []
    else:
        if not isinstance(data, dict) or set(data) != {"facts", "not_extracted"} \
                or not isinstance(data["facts"], list) or not isinstance(data["not_extracted"], list):
            return {**empty, "parse_error": 'the answer must be {"facts": [...], "not_extracted": [...]}'}
        items, skipped = data["facts"], data["not_extracted"]
    index, facts, others = QuoteIndex(segments), [], []
    for i, item in enumerate(items):
        try:
            fact, errors = FACT.validate_python(item).model_dump(mode="json"), []
        except ValidationError as e:
            fact, errors = None, _errors(e)
        problems = version_problems(item, version)
        if problems:
            fact, errors = None, errors + problems
        quote = item.get("quote") if isinstance(item, dict) else None
        found = index.find(quote) if isinstance(quote, str) else {"ok": False, "occurrences": 0, "refs": []}
        subs = [s.get("subheading") for s in segments if s["ref"] in found["refs"]]
        facts.append({"index": i, "fact": fact, "answer": item, "parse_errors": errors,
                      "quote_check": found, "subheading": subs[0] if subs else None})
    for i, item in enumerate(skipped):
        try:
            entry, errors = NotExtracted.model_validate(item).model_dump(), []
        except ValidationError as e:
            entry, errors = None, _errors(e)
        quote = item.get("quote") if isinstance(item, dict) else None
        found = index.find(quote) if isinstance(quote, str) else {"ok": False, "occurrences": 0, "refs": []}
        others.append({"index": i, "entry": entry, "answer": item, "parse_errors": errors, "quote_check": found})
    coverage = None
    if v.coverage:
        touched = {r for x in facts + others for r in x["quote_check"]["refs"]}
        quotes = [normalise(x["answer"]["quote"]) for x in facts + others
                  if isinstance(x["answer"], dict) and isinstance(x["answer"].get("quote"), str)]
        coverage = {
            "uncovered": [{"ref": s["ref"], "pdf_page": s["pdf_page"], "text": s["text"]}
                          for s in segments if s["kind"] in COVERED_KINDS and s["ref"] not in touched],
            "sentences_outside_quotes": [{"ref": s["ref"], "sentence": t} for s in segments
                                         if s["kind"] == "text" and s["ref"] in touched
                                         for t in _sentences(s["text"]) if not any(t in q for q in quotes)],
        }
    return {"parse_error": None, "facts": facts, "not_extracted": others, "coverage": coverage}


def summarise(record: dict) -> dict:
    facts, others = record["facts"], record.get("not_extracted") or []
    ok = [f for f in facts if f["fact"]]
    steps = [(f["index"], s) for f in ok for s in f["fact"]["steps"]]
    qty = [(i, s, q) for i, s in steps for q in s["applies"]]
    cov = record.get("coverage") or {}

    def quote_of(x):
        return x["answer"].get("quote") if isinstance(x["answer"], dict) else None

    return {
        "facts": len(facts),
        "by_subtype": dict(Counter(f["fact"]["subtype"] for f in ok)),
        "by_subheading": dict(Counter(f["subheading"] or "(none)" for f in facts)),
        "parse_failures": [{"index": f["index"], "errors": f["parse_errors"]} for f in facts if not f["fact"]],
        "quote_failures": [{"index": f["index"], "quote": quote_of(f)} for f in facts if not f["quote_check"]["ok"]],
        "quotes_found_more_than_once": [f["index"] for f in facts if f["quote_check"]["occurrences"] > 1],
        "not_extracted": [{"index": x["index"], "quote": quote_of(x), "reason": (x["entry"] or {}).get("reason"),
                           "ok": x["quote_check"]["ok"] and not x["parse_errors"]} for x in others],
        "not_extracted_failures": [x["index"] for x in others if x["parse_errors"] or not x["quote_check"]["ok"]],
        "uncovered": cov.get("uncovered", []),
        "sentences_outside_quotes": cov.get("sentences_outside_quotes", []),
        "extraction_flags": [{"index": f["index"], "flags": f["fact"]["extraction_flags"]}
                             for f in ok if f["fact"]["extraction_flags"]],
        "unmapped": [{"index": f["index"], "phrase": p} for f in ok for p in f["fact"]["unmapped"]],
        "purposes": [{"index": f["index"], "purposes": f["fact"]["purposes"]} for f in ok if f["fact"]["purposes"]],
        "basis_inferred": [{"index": i, "target": q["target"], "basis": q["basis"], "raw": q["raw"]}
                           for i, _, q in qty if q["basis_inferred"]],
        "basis_missing": [{"index": i, "target": q["target"], "raw": q["raw"]}
                          for i, _, q in qty if q["raw"] and q["basis"] is None],
        "basis_from_rule": [{"index": i, "target": q["target"], "rule": q["basis_rule"]}
                            for i, _, q in qty if q["basis_rule"]],
        "quantity_ref": [{"index": i, "target": q["target"]} for i, _, q in qty if q["quantity_ref"]],
        "steps_without_operation": [{"index": i, "step": s["instruction_en"] or s.get("method") or s["order"]}
                                    for i, s in steps if s["operation"] is None],
    }


def ingest(entry, unit: dict, model: str, answer: str, force: bool = False,
           version: str = PROMPT_VERSION) -> tuple[Path, dict]:
    built = build(entry, unit, model, version=version)
    path = out_path(entry, unit["id"], version)
    if cached(entry, unit, built) and not force:
        raise ExtractError("%s already holds an answer with this cache key; use --force to replace it" % path)
    checked = check_answer(answer, built["segments"], version)
    record = {
        "unit_id": unit["id"], "source_id": entry.id, "section_path": unit["section_path"],
        "chapter": unit["chapter"], "pdf_pages": unit["pdf_pages"], "regions": unit["regions"],
        "purposes": unit.get("purposes", []), "default_scope": unit["default_scope"],
        "prompt_version": version, "prompt_sha256": built["prompt_sha256"],
        "extraction_model": model, "unit_text_sha256": built["unit_text_sha256"],
        "cache_key": built["cache_key"], "created_at": datetime.now(timezone.utc).isoformat(),
        "answer": answer, **checked,
    }
    record["summary"] = s = summarise(record)
    record["ok"] = not (record["parse_error"] or s["parse_failures"] or s["quote_failures"]
                        or s["not_extracted_failures"] or s["uncovered"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():                    # an earlier run is kept, never overwritten
        old = json.loads(path.read_text(encoding="utf-8"))
        kept = path.parent / "history" / history_name(path.stem, old)
        if kept.exists():                # a --force re-run has the same cache key; its time tells the runs apart
            raise ExtractError("%s already exists; refusing to overwrite an earlier run" % kept)
        kept.parent.mkdir(exist_ok=True)
        kept.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        record["previous_run"] = kept.relative_to(EXTRACTED_DIR).as_posix()
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path, record


def history_name(stem: str, run: dict) -> str:
    """history/<hash>.<cache key[:12]>.<run time, UTC>.json. The cache key alone repeats when the same
    unit, prompt and model are re-run with --force; before 2026-10-21 that overwrote a kept run."""
    when = datetime.fromisoformat(run["created_at"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return "%s.%s.%s.json" % (stem, run["cache_key"][:12], when)


def write_prompt(entry, unit: dict, built: dict) -> Path:
    """Write the filled prompt; an earlier prompt for the unit with a different cache key moves to
    history/<hash>.<key[:12]>.md first. The key sits beside the prompt in <hash>.key (the prompt
    text itself is only what the model reads)."""
    d = out_dir(entry, built["version"]) / "prompts"
    stem = file_stem(unit["id"])
    path, key_path = d / ("%s.md" % stem), d / ("%s.key" % stem)
    d.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old_key = key_path.read_text(encoding="utf-8").strip() if key_path.exists() else \
            "nokey-" + hashlib.sha256(path.read_bytes()).hexdigest()
        if old_key != built["cache_key"]:
            kept = out_dir(entry, built["version"]) / "history" / ("%s.%s.md" % (stem, old_key[:12]))
            if kept.exists() and kept.read_bytes() != path.read_bytes():   # the key covers the prompt text
                raise ExtractError("%s already exists with other text; refusing to overwrite it" % kept)
            kept.parent.mkdir(exist_ok=True)
            kept.write_bytes(path.read_bytes())
    path.write_text(built["prompt"], encoding="utf-8")
    key_path.write_text(built["cache_key"], encoding="utf-8")
    return path


def load_run(entry, unit_id: str, ref: str) -> dict:
    """A stored run: a prompt version ("v2", the latest run under it) or a file path."""
    path = Path(ref) if ref.endswith(".json") else out_path(entry, unit_id, ref)
    if not path.exists():
        raise ExtractError("no run %s for %s (%s)" % (ref, unit_id, path))
    return json.loads(path.read_text(encoding="utf-8"))


# --- comparing two runs of one unit -------------------------------------------------------------

IGNORED = {"instruction_en"}             # written by the model in v1, by code from v2


def _flatten(obj, prefix="") -> dict:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k not in IGNORED:
                out.update(_flatten(v, "%s.%s" % (prefix, k) if prefix else k))
        return out
    if isinstance(obj, list):
        if not any(isinstance(v, (dict, list)) for v in obj):
            return {prefix: obj}                     # names, flags, signs: compared whole
        out = {}
        for i, v in enumerate(obj):
            out.update(_flatten(v, "%s[%d]" % (prefix, i)))
        return out
    return {prefix: obj}


def compare(a: dict, b: dict) -> dict:
    """Facts matched by subtype and quote (then by one quote containing the other), with the fields
    that differ; facts only in one run; and b's not-extracted passages."""
    fa = [f for f in a["facts"] if f["fact"]]
    fb = [f for f in b["facts"] if f["fact"]]
    pairs, left, right = [], list(fa), list(fb)
    for loose in (False, True):
        for x in list(left):
            qx = normalise(x["fact"]["quote"])
            for y in right:
                qy = normalise(y["fact"]["quote"])
                same = qx == qy if not loose else (qx in qy or qy in qx)
                if y["fact"]["subtype"] == x["fact"]["subtype"] and same:
                    pairs.append((x, y))
                    left.remove(x)
                    right.remove(y)
                    break
    def current(fact):                               # both runs through today's model: same defaults
        return FACT.validate_python(fact).model_dump(mode="json")

    changed = []
    for x, y in pairs:
        dx, dy = _flatten(current(x["fact"])), _flatten(current(y["fact"]))
        diff = {k: [dx.get(k), dy.get(k)] for k in sorted(set(dx) | set(dy)) if dx.get(k) != dy.get(k)}
        if diff:
            changed.append({"from": x["index"], "to": y["index"], "subtype": x["fact"]["subtype"], "diff": diff})
    return {
        "from": "%s@%s" % (a["prompt_version"], a["cache_key"][:8]),
        "to": "%s@%s" % (b["prompt_version"], b["cache_key"][:8]),
        "facts": [len(a["facts"]), len(b["facts"])],
        "by_subtype": [a["summary"]["by_subtype"], b["summary"]["by_subtype"]],
        "matched": len(pairs), "unchanged": len(pairs) - len(changed), "changed": changed,
        "only_from": [{"index": x["index"], "subtype": x["fact"]["subtype"], "quote": x["fact"]["quote"]} for x in left],
        "only_to": [{"index": y["index"], "subtype": y["fact"]["subtype"], "quote": y["fact"]["quote"]} for y in right],
        "not_extracted_to": b["summary"].get("not_extracted", []),
    }
