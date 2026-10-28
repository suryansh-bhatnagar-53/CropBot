"""The expert decisions file (step 16): data/review/expert_decisions.csv, committed.

One row per decided fact. A row is written only by kg.review.importer from a filled review workbook, and is
never changed by code afterwards: a re-review is a deliberate edit of this file. The loader (kg.load.facts)
re-applies every row whose fact is in the load and whose row_hash still matches, so decisions survive
reloads and a rebuilt database; any other row is reported as stale and not applied.
"""

import csv
from pathlib import Path

from kg.registry import ROOT

DECISIONS_CSV = ROOT / "data" / "review" / "expert_decisions.csv"
FIELDS = ("fact_id", "row_hash", "decision", "note", "applies_uttarakhand", "reviewed_by", "reviewed_at",
          "imported_at", "workbook_sha256", "source_id", "subtype", "quote")
DECISIONS = ("approve", "reject", "needs change")
UTTARAKHAND = ("yes", "no", "not sure")
STATUS_OF = {"approve": "approved", "reject": "rejected", "needs change": "needs_review"}
EXPERT_PREFIX = "expert: "                  # a "needs change" note, as it appears in review_reasons


def read_decisions(path: Path = DECISIONS_CSV, source_id: str | None = None) -> list[dict]:
    """Every decision row (of one source, if given). A missing file means no decisions."""
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    bad = [r.get("fact_id") for r in rows if r.get("decision") not in DECISIONS]
    if bad:
        raise ValueError("%s: unknown decision for %s" % (path, bad))
    return [r for r in rows if source_id is None or r["source_id"] == source_id]


def append_decisions(rows: list[dict], path: Path = DECISIONS_CSV) -> None:
    """Append rows; the header is written when the file is new."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows({k: r.get(k) for k in FIELDS} for r in rows)


def apply_row(d: dict) -> dict:
    """What a decision sets on its Recommendation node."""
    note = d.get("note") or None
    return {"fact_id": d["fact_id"], "status": STATUS_OF[d["decision"]], "decision": d["decision"], "note": note,
            "reason_text": EXPERT_PREFIX + note if d["decision"] == "needs change" and note else None,
            "applies_uttarakhand": d.get("applies_uttarakhand") or None, "reviewed_by": d["reviewed_by"],
            "reviewed_at": d["reviewed_at"]}
