import argparse
import csv
import json
import sys

from kg.registry import read_registry

from . import DISAGREEMENTS_CSV, EVAL_DIR, UNMATCHED_CSV, disagreements, report, run, unmatched


def write_csv(path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def pct(r: dict) -> str:
    if r["rate"] is None:
        return "n/a (0)"
    lo, hi = r["wilson95"]
    return "%d/%d = %.0f%% [%.0f-%.0f]" % (r["k"], r["n"], 100 * r["rate"], 100 * lo, 100 * hi)


def print_report(rep: dict) -> None:
    g = rep["gold"]
    print("gold rows %d, scored %d; unscored: %s" % (g["rows"], g["scored"], g["unscored"]))
    if g["oddities"]:
        print("gold oddities (reported, not changed):", g["oddities"])
    print("atoms %d, in the precision scope %d; context steps not counted %d" % (
        rep["atoms"]["total"], rep["atoms"]["in_scope"], rep["atoms"]["context_steps_not_counted"]))
    for title, block in (("section", rep["metrics"]["sections"]), ("subtype", rep["metrics"]["subtypes"])):
        print("\nby %s:" % title)
        for k, m in block.items():
            print("  %-15s rows %3d found %3d (not-extracted %d, missed %d) | recall found %s, lenient %s, "
                  "pipeline %s | agree %s .. %s | precision found %s, agree %s .. %s" % (
                      k, m["gold_rows"], m["found"], m["not_extracted"], m["missed"] - m["not_extracted"],
                      pct(m["recall_found_strict"]), pct(m["recall_found_lenient"]), pct(m["recall_pipeline_strict"]),
                      pct(m["recall_agree"]["lower"]), pct(m["recall_agree"]["upper"]),
                      pct(m["precision_found"]), pct(m["precision_agree_lower"]), pct(m["precision_agree_upper"])))
    print("\nnot extracted (step 9 decision):", rep["not_extracted_rows"])
    print("missed scored rows:", rep["missed_rows"])
    d = rep["disagreements"]
    print("\ndisagreements: %d on %d gold rows, %d adjudicated; by field %s" % (
        d["count"], d["rows"], d["adjudicated"], d["by_field"]))
    for p in d["patterns"]:
        print("  x%-3d %-11s gold %r | extracted %r" % (p["rows"], p["field"], p["gold"][:60], p["extracted"][:60]))
    stale = rep["stale_adjudications"]
    print("\nstale adjudications (kept in the file, meeting nothing now): %d" % len(stale))
    for s in stale:
        print("  %-6s %-12s %-10s %s" % (s["gold_id"] or "-", s["field"], s["verdict"], s.get("name") or s["reason"]))
    c = rep["calibration"]
    for name, pop in c["populations"].items():
        print("\ncalibration %s (n=%d):" % (name, pop["n"]))
        for r in pop["cutoffs"]:
            print("  >= %.2f  n %3d  correct %3d open %3d wrong %2d  coverage %s  precision (open=wrong) %s  "
                  "(open=right) %s" % (r["cutoff"], r["n"], r["correct"], r["open"], r["wrong"], r["coverage"],
                                       pct(r["precision_lower"]), pct(r["precision_upper"])))
    print("\nproposal:", json.dumps(c["proposal"], indent=1))
    k = rep["controls"]
    print("\ncontrols: %d; by kind %s" % (k["n"], json.dumps(k["by_kind"])))
    print("gold-labelled claims P(yes):", json.dumps(k["gold_labelled_claims"]))
    for r in k["cutoffs"]:
        print("  >= %.2f  controls accepted %d/%d %s  by kind %s" % (r["cutoff"], r["accepted"], r["of"],
                                                                    pct(r["false_accept"]), r["by_kind"]))
    print("with none accepted, %d controls bound the false-accept rate below %.1f%% (exact 95%%); "
          "%d are needed for 5%%" % (k["n"], 100 * k["exact_95_upper_if_none_accepted"],
                                    k["controls_needed_for_5pct_upper_with_none_accepted"]))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m kg.eval", description="Step 15: evaluate against the gold set")
    p.add_argument("source_id")
    a = p.parse_args(argv)
    entry = next((e for e in read_registry() if e.id == a.source_id), None)
    if entry is None:
        raise SystemExit("unknown source %s" % a.source_id)
    res = run(entry)
    rep = report(res)
    out = EVAL_DIR / entry.id.split(":", 1)[1]
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    dis = disagreements(res)
    write_csv(DISAGREEMENTS_CSV, dis, ["gold_id", "section", "scored", "pdf_page", "field", "gold_value",
                                       "extracted_value", "rule", "atom", "fact_status", "gold_type",
                                       "extracted_subtype", "gold_input", "extracted_name", "gold_quote",
                                       "extracted_quote", "verdict", "note"])
    write_csv(UNMATCHED_CSV, unmatched(res), ["kind", "id", "section", "scored", "pdf_page", "type", "name", "value",
                                             "note", "quote"])
    print_report(rep)
    print("\nwritten: %s, %s, %s" % (out / "report.json", DISAGREEMENTS_CSV, UNMATCHED_CSV))
    return 0


if __name__ == "__main__":
    sys.exit(main())
