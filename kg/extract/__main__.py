import argparse
import json
import sys
from pathlib import Path

from kg.registry import read_registry

from . import (ExtractError, build, cached, compare, get_unit, ingest, load_run, load_units, out_dir,
               write_prompt)
from .versions import LATEST, VERSIONS, source_version

KEYS = ("parse_failures", "quote_failures", "quotes_found_more_than_once", "not_extracted",
        "not_extracted_failures", "uncovered", "sentences_outside_quotes", "extraction_flags", "unmapped",
        "purposes", "basis_inferred", "basis_missing", "basis_from_rule", "quantity_ref",
        "steps_without_operation")


def _entry(source_id):
    hits = [e for e in read_registry() if e.id == source_id]
    if not hits:
        raise SystemExit("unknown source %s" % source_id)
    return hits[0]


def print_summary(record: dict) -> None:
    s = record["summary"]
    print("=== %s  [%s]" % (record["section_path"], record["unit_id"]))
    print("  model %s, prompt %s, %s" % (record["extraction_model"], record["prompt_version"],
                                         "OK" if record["ok"] else "FAILED CHECKS"))
    if record["parse_error"]:
        print("  answer did not parse:", record["parse_error"])
    print("  facts: %d  by subtype: %s" % (s["facts"], s["by_subtype"]))
    print("  by sub-heading: %s" % s["by_subheading"])
    for key in KEYS:
        if key in s:
            print("  %s: %d" % (key, len(s[key])))
            for x in s[key]:
                print("    ", x)


def print_compare(c: dict) -> None:
    print("=== compare %s -> %s: facts %s, matched %d (unchanged %d, changed %d), only in %s: %d, only in %s: %d"
          % (c["from"], c["to"], c["facts"], c["matched"], c["unchanged"], len(c["changed"]), c["from"],
             len(c["only_from"]), c["to"], len(c["only_to"])))
    print("  by subtype: %s -> %s" % tuple(c["by_subtype"]))
    for ch in c["changed"]:
        print("  changed %s #%d -> #%d:" % (ch["subtype"], ch["from"], ch["to"]))
        for k, (x, y) in ch["diff"].items():
            print("      %s: %r -> %r" % (k, x, y))
    for key, run in (("only_from", c["from"]), ("only_to", c["to"])):
        for x in c[key]:
            print("  only in %s: #%d %s %r" % (run, x["index"], x["subtype"], x["quote"][:110]))
    for x in c["not_extracted_to"]:
        print("  not extracted in %s: %r -- %s" % (c["to"], (x["quote"] or "")[:90], x["reason"]))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m kg.extract", description="Step 9: extraction (no API calls)")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find", help="list units whose section path contains TEXT")
    f.add_argument("source_id")
    f.add_argument("text")
    for name in ("prepare", "ingest"):
        q = sub.add_parser(name)
        q.add_argument("source_id")
        q.add_argument("--unit", required=True)
        q.add_argument("--model", required=True, help="the model that answers, recorded as extraction_model")
        q.add_argument("--prompt", choices=sorted(VERSIONS), help="default: the source's pinned version, else %s"
                       % LATEST)
        if name == "ingest":
            q.add_argument("--response", required=True, type=Path, help="file holding the model's answer")
            q.add_argument("--force", action="store_true", help="replace an answer with the same cache key")
    r = sub.add_parser("report", help="summaries of every stored answer for one prompt version")
    r.add_argument("source_id")
    r.add_argument("--prompt", choices=sorted(VERSIONS), help="default: the source's pinned version, else %s"
                   % LATEST)
    c = sub.add_parser("compare", help="two runs of one unit")
    c.add_argument("source_id")
    c.add_argument("--unit", required=True)
    c.add_argument("--from", dest="a", required=True, help="a prompt version (its latest run) or a run file")
    c.add_argument("--to", dest="b", required=True, help="a prompt version (its latest run) or a run file")
    a = p.parse_args(argv)
    entry = _entry(a.source_id)
    if getattr(a, "prompt", "x") is None:
        a.prompt = source_version(entry)
    try:
        if a.cmd == "find":
            for u in load_units(entry):
                if a.text.lower() in u["section_path"].lower():
                    print("%s  PDF %s  ~%d tokens  %s" % (u["id"], u["pdf_pages"], u["approx_tokens"],
                                                          u["section_path"]))
            return 0
        if a.cmd == "report":
            d = out_dir(entry, a.prompt)
            records = [json.loads(x.read_text(encoding="utf-8")) for x in sorted(d.glob("*.json"))
                       if x.name != "report.json"]
            for rec in records:
                print_summary(rec)
            (d / "report.json").write_text(json.dumps(
                [{k: rec[k] for k in ("unit_id", "section_path", "extraction_model", "prompt_version",
                                      "ok", "summary")} for rec in records], indent=2, ensure_ascii=False),
                encoding="utf-8")
            return 0 if all(rec["ok"] for rec in records) else 1
        if a.cmd == "compare":
            print_compare(compare(load_run(entry, a.unit, a.a), load_run(entry, a.unit, a.b)))
            return 0
        unit = get_unit(entry, a.unit)
        if a.cmd == "prepare":
            built = build(entry, unit, a.model, version=a.prompt)
            hit = cached(entry, unit, built)
            if hit:
                print("cached: %s (same unit text, prompt and model)" % hit)
                return 0
            path = write_prompt(entry, unit, built)
            print("prompt written: %s (%d chars, %d quote segments)" % (path, len(built["prompt"]),
                                                                        len(built["segments"])))
            return 0
        path, record = ingest(entry, unit, a.model, a.response.read_text(encoding="utf-8"), a.force, a.prompt)
        print_summary(record)
        print("written:", path)
        return 0 if record["ok"] else 1
    except ExtractError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    sys.exit(main())
