import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict

from kg.registry import read_registry, review_csv

from . import NORMALIZED_DIR, PROPOSED_CSV, run


def reason_group(reason: str) -> str:
    """'unlinked target 'Pest' (generic target, no concept)' -> 'unlinked target (generic target, no concept)'."""
    g = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "…", reason)
    g = re.sub(r"\b\d+\b", "N", g)
    g = re.sub(r"\[[^\]]*\]", "[…]", g)
    return re.sub(r"\s+", " ", g).strip()


def report(result) -> dict:
    links = [lk for x in result["facts"] + result["held"] for lk in x["links"]]
    by_type = defaultdict(Counter)
    for lk in links:
        by_type[lk["name_type"]]["total"] += 1
        by_type[lk["name_type"]][lk["method"] if lk["id"] else "unlinked"] += 1
    rates = {t: {"total": c["total"], "linked": c["total"] - c["unlinked"],
                 "rate": round((c["total"] - c["unlinked"]) / c["total"], 3),
                 "by_method": {k: v for k, v in c.items() if k not in ("total",)}} for t, c in sorted(by_type.items())}
    unlinked = Counter((lk["name_type"], lk["name"], lk["reason"]) for lk in links if not lk["id"])
    held_reasons = Counter(reason_group(r) for h in result["held"] for r in h["reasons"])
    held_facts_by_reason = defaultdict(list)
    for h in result["held"]:
        for g in {reason_group(r) for r in h["reasons"]}:
            held_facts_by_reason[g].append("%s#%d" % (h["unit_id"].rsplit(":", 1)[1], h["raw_index"]))
    return {
        "facts_in": len(result["facts"]) + len(result["held"]),
        "validated": len(result["facts"]), "held": len(result["held"]),
        "validated_by_status": dict(Counter(x["status"] for x in result["facts"])),
        "validated_by_subtype": dict(Counter(x["subtype"] for x in result["facts"])),
        "held_by_reason": dict(held_reasons.most_common()),
        "held_facts_by_reason": dict(held_facts_by_reason),
        "link_rates": rates,
        "unlinked": [{"name_type": t, "name": n, "reason": r, "count": c} for (t, n, r), c in unlinked.most_common()],
        "conversions": [c for x in result["facts"] + result["held"] for c in x["conversions"]],
        "review_reasons": dict(Counter(reason_group(r) for x in result["facts"] for r in x["review_reasons"])),
    }


def write(entry, result, rep) -> None:
    out = NORMALIZED_DIR / entry.id.split(":", 1)[1]
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("facts.jsonl", result["facts"]), ("held.jsonl", result["held"])):
        with open(out / name, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    seen = {}
    for x in result["facts"] + result["held"]:
        for lk in x["links"]:
            if lk["id"]:
                continue
            key = (lk["name"], lk["name_type"])
            row = seen.setdefault(key, {"name": lk["name"], "name_type": lk["name_type"], "reason": lk["reason"],
                                        "count": 0, "facts": []})
            row["count"] += 1
            row["facts"].append("%s#%d" % (x["unit_id"].rsplit(":", 1)[1], x["raw_index"]))
    path = review_csv(PROPOSED_CSV, entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=("name", "name_type", "reason", "count", "facts"))
        w.writeheader()
        for row in sorted(seen.values(), key=lambda r: (r["name_type"], r["name"].lower())):
            w.writerow({**row, "facts": " ".join(row["facts"])})


def print_report(r: dict) -> None:
    print("facts in: %d  validated: %d %s  held: %d" % (r["facts_in"], r["validated"], r["validated_by_status"], r["held"]))
    print("validated by subtype:", r["validated_by_subtype"])
    print("link rates:")
    for t, x in r["link_rates"].items():
        print("  %-18s %3d/%-3d %5.1f%%  %s" % (t, x["linked"], x["total"], 100 * x["rate"], x["by_method"]))
    print("held, by reason (a fact can have several):")
    for g, n in r["held_by_reason"].items():
        print("  %4d  %s" % (n, g))
    print("review reasons of validated facts:", r["review_reasons"])
    print("unlinked names: %d distinct" % len(r["unlinked"]))
    print("conversions: %d" % len(r["conversions"]))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m kg.normalize", description="Step 10: normalise and link (no model)")
    p.add_argument("source_id")
    a = p.parse_args(argv)
    entry = next((e for e in read_registry() if e.id == a.source_id), None)
    if entry is None:
        raise SystemExit("unknown source %s" % a.source_id)
    result = run(entry)
    rep = report(result)
    write(entry, result, rep)
    print_report(rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
