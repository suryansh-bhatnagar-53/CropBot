"""uv run python -m kg.review sheet source:<id> [--out <xlsx>] [--database <db>] [--precheck <notes.csv>]
uv run python -m kg.review import <xlsx> [--check] [--database <db>] [--decisions <csv>]"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from kg.load import facts as lf
from kg.load.db import get_driver
from kg.load.seed import read_seed
from kg.registry import ROOT, RegistryError, read_registry
from kg.review import importer, sheet
from kg.review.decisions import DECISIONS_CSV, read_decisions


def _entry(source_id):
    try:
        entries = read_registry()
    except RegistryError as e:
        raise SystemExit("registry is invalid:\n  " + "\n  ".join(e.problems))
    entry = next((e for e in entries if e.id == source_id), None)
    if entry is None:
        raise SystemExit("unknown source %s" % source_id)
    return entry


def _built(entry, decisions):
    seed = read_seed()
    try:
        return lf.build(entry, lf.read_inputs(entry, decisions), {n.id for n in seed.nodes}), seed
    except lf.LoadError as e:
        raise SystemExit("step 13 refuses the current facts:\n  " + "\n  ".join(e.problems))


def cmd_sheet(a) -> int:
    entry = _entry(a.source_id)
    built, seed = _built(entry, a.decisions)
    names = {n.id: n.name_en for n in seed.nodes if getattr(n, "name_en", None)}
    with get_driver() as driver:
        current = sheet.current_from_db(driver, a.database)
    try:
        rows = sheet.rows(entry, built, current, names)
        moved = sheet.add_precheck(rows, sheet.read_precheck(a.precheck)) if a.precheck else []
    except sheet.SheetError as e:
        raise SystemExit("no sheet written:\n  " + "\n  ".join(e.problems))
    out = Path(a.out) if a.out else ROOT / "data" / "review" / ("expert_review_%s.xlsx" % entry.id.split(":", 1)[1])
    sheet.write_workbook(out, entry, rows, a.database, names.get(entry.state_id))
    flagged = [r["fact_id"] for r in rows if r["scope_flag"]]
    print(json.dumps({"written": str(out), "rows": len(rows),
                      "by_subtype": {s: sum(r["subtype"] == s for r in rows) for s in sheet.ORDER},
                      "scope_in_unmapped_highlighted": flagged,
                      "ai_precheck": {**{k: sum(r.get("ai_precheck") == k for r in rows) for k in sheet.PRECHECK},
                                      "blank result, note only": sum("ai_note" in r and not r["ai_precheck"]
                                                                     for r in rows),
                                      "no note": sum("ai_note" not in r for r in rows)}
                      if a.precheck else None,
                      "review_no_differs_from_notes": moved}, indent=1))
    return 0


def cmd_import(a) -> int:
    path = Path(a.workbook)
    try:
        meta, rows = sheet.read_workbook(path)
    except sheet.SheetError as e:
        raise SystemExit("\n".join(e.problems))
    entry = _entry(meta.get("source_id"))
    built, _ = _built(entry, a.decisions)
    existing = {d["fact_id"]: d for d in read_decisions(a.decisions)}
    result = importer.check_rows(rows, importer.current_facts(built), existing, entry.id, dt.date.today())
    rep = importer.report(result)
    print(json.dumps({"workbook": str(path), "source_id": entry.id, "decisions_file": str(a.decisions), **rep},
                     indent=1, ensure_ascii=False))
    if a.check:
        print("check only: nothing written")
        return 1 if result["refused"] else 0
    accepted = importer.stamp(result["accepted"], path.read_bytes())
    with get_driver() as driver:
        try:
            importer.apply(driver, accepted, a.database)
        except ValueError as e:
            raise SystemExit(str(e))
    importer.append_decisions(accepted, Path(a.decisions))
    print("applied to %s and recorded in %s: %d decisions" % (a.database or "the home database", a.decisions,
                                                               len(accepted)))
    return 1 if result["refused"] else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kg.review", description="Step 16: expert review")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet", help="write the review workbook for a source")
    s.add_argument("source_id")
    s.add_argument("--out")
    s.add_argument("--database")
    s.add_argument("--decisions", default=str(DECISIONS_CSV))
    s.add_argument("--precheck", help="AI pre-check notes (review_no, fact_id, ai_precheck, ai_note), shown as a hint")
    i = sub.add_parser("import", help="check and import a filled review workbook")
    i.add_argument("workbook")
    i.add_argument("--check", action="store_true", help="check every row; write nothing")
    i.add_argument("--database")
    i.add_argument("--decisions", default=str(DECISIONS_CSV))
    a = ap.parse_args(argv)
    return cmd_sheet(a) if a.cmd == "sheet" else cmd_import(a)


if __name__ == "__main__":
    sys.exit(main())
