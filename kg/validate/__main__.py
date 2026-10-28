import argparse
import csv
import json
import sys

from kg.registry import read_registry, review_csv

from . import CHECKS, REVIEW_CSV, VALIDATED_DIR, report, run


def write(entry, res, rep) -> None:
    out = VALIDATED_DIR / entry.id.split(":", 1)[1]
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "facts.jsonl", "w", encoding="utf-8") as f:
        for row in res["facts"]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    path = review_csv(REVIEW_CSV, entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["unit_id", "raw_index", "fact_id", "subtype", "check", "status", "reason"])
        for row in res["facts"]:
            for c in CHECKS:
                r = row["checks"][c]
                if r["status"] == "fail" or (c == "alternatives" and r["status"] == "skip" and r.get("applies")):
                    w.writerow([row["unit_id"], row["raw_index"], row["fact_id"], row["subtype"], c, r["status"],
                                r["reason"]])


def print_report(rep: dict) -> None:
    print("facts: %d  status before %s -> after %s  (approved: %d)" % (
        rep["facts"], rep["status_before"], rep["status_after"], rep["approved"]))
    print("review notes attached:", rep["review_notes"] or "none", " stale approved notes:", rep["stale_notes"] or "none")
    for c in CHECKS:
        print("%-15s %s" % (c, rep["per_check"][c]))
        for x in rep["failures"][c]:
            print("    FAIL %-18s %-15s %s" % (x["fact"], x["subtype"], x["reason"][:200]))
        for reason, n in rep["skips"].get(c, {}).items():
            print("    skip x%d  %s" % (n, reason))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m kg.validate", description="Step 11: validate (no model)")
    p.add_argument("source_id")
    a = p.parse_args(argv)
    entry = next((e for e in read_registry() if e.id == a.source_id), None)
    if entry is None:
        raise SystemExit("unknown source %s" % a.source_id)
    res = run(entry)
    rep = report(res)
    write(entry, res, rep)
    print_report(rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
