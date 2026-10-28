"""Import a filled review workbook (step 16).

Each row with a decision is checked against the facts step 13 would load now. A row is refused, with its
reason, when its fact is not current, its row_hash no longer matches (the quote, values or scope changed
since the sheet was made), the decision or the Uttarakhand answer is not one of the allowed values, a reject
or needs change has no reason, the reviewer name or date is missing or invalid, or the fact already has a
different decision. A row identical to a recorded decision is "already imported" (a re-run is a no-op).
Rows without a decision are "not reviewed".

Accepted rows are applied to the database in one transaction (kg.load.facts.APPLY_DECISIONS) and then
appended to the decisions file. A correction is stored as text and never changes a value.
"""

import datetime as dt
import hashlib
from collections import Counter

from kg.load.facts import apply_decisions, row_hash
from kg.review.decisions import DECISIONS, UTTARAKHAND, append_decisions, apply_row

SAME = ("row_hash", "decision", "note", "applies_uttarakhand", "reviewed_by", "reviewed_at")


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _date(v) -> str | None:
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    try:
        return dt.date.fromisoformat(_text(v)).isoformat()
    except ValueError:
        return None


def check_rows(sheet_rows: list[dict], current: dict, existing: dict, source_id: str, today: dt.date) -> dict:
    """`current`: fact id -> (row_hash, subtype, quote) of the facts the loader would write now;
    `existing`: fact id -> its recorded decision row. Returns accepted, already, refused and not_reviewed."""
    out = {"accepted": [], "already": [], "refused": [], "not_reviewed": []}
    seen = set()
    for r in sheet_rows:
        fid, decision = _text(r.get("fact_id")), _text(r.get("decision")).lower()
        where = "row %s (%s)" % (r.get("_row"), fid)
        if not decision:
            out["not_reviewed"].append(fid)
            continue
        note, utk, who = _text(r.get("note")), _text(r.get("uttarakhand")).lower(), _text(r.get("reviewer"))
        when = _date(r.get("date"))
        problems = []
        if fid in seen:
            problems.append("the fact appears twice in the sheet")
        seen.add(fid)
        if fid not in current:
            problems.append("not a current fact (re-extracted, held or missing since the sheet was made)")
        elif _text(r.get("row_hash")) != current[fid][0]:
            problems.append("the fact's quote, values or scope changed since the sheet was made")
        if decision not in DECISIONS:
            problems.append("decision %r is not one of %s" % (decision, ", ".join(DECISIONS)))
        if decision in ("reject", "needs change") and not note:
            problems.append("a %s needs a reason or correction" % decision)
        if utk not in UTTARAKHAND:
            problems.append("Uttarakhand answer %r is not one of %s" % (utk, ", ".join(UTTARAKHAND)))
        if not who:
            problems.append("no reviewer name")
        if when is None:
            problems.append("date %r is not a date (yyyy-mm-dd)" % r.get("date"))
        elif when > today.isoformat():
            problems.append("date %s is in the future" % when)
        if problems:
            out["refused"].append({"row": r.get("_row"), "fact_id": fid, "reasons": problems})
            continue
        h, subtype, quote = current[fid]
        d = {"fact_id": fid, "row_hash": h, "decision": decision, "note": note, "applies_uttarakhand": utk,
             "reviewed_by": who, "reviewed_at": when, "source_id": source_id, "subtype": subtype, "quote": quote}
        old = existing.get(fid)
        if old is None:
            out["accepted"].append(d)
        elif all(_text(old.get(k)) == _text(d.get(k)) for k in SAME):
            out["already"].append(fid)
        else:
            out["refused"].append({"row": r.get("_row"), "fact_id": fid, "reasons": [
                "already decided (%s by %s on %s); a re-review is a deliberate edit of the decisions file"
                % (old["decision"], old["reviewed_by"], old["reviewed_at"])]})
    return out


def current_facts(built: dict) -> dict:
    return {r["id"]: (row_hash(r["fact"]), r["subtype"], "\n".join(e["quote"] for e in r["fact"]["evidence"]))
            for r in built["recs"]}


def report(result: dict) -> dict:
    acc = result["accepted"]
    return {"accepted": len(acc), "already_imported": len(result["already"]),
            "not_reviewed": len(result["not_reviewed"]), "refused": len(result["refused"]),
            "by_decision": dict(Counter(d["decision"] for d in acc)),
            "by_subtype": {s: dict(Counter(d["decision"] for d in acc if d["subtype"] == s))
                           for s in sorted({d["subtype"] for d in acc})},
            "refused_rows": result["refused"]}


def apply(driver, accepted: list[dict], database=None) -> None:
    """One transaction; refused as a whole if any decided fact is not in the graph or is flagged missing."""
    if not accepted:
        return
    ids = [d["fact_id"] for d in accepted]
    found, _, _ = driver.execute_query("MATCH (r:Recommendation) WHERE r.id IN $ids "
                                       "AND NOT coalesce(r.missing_in_latest_run, false) RETURN r.id AS id",
                                       ids=ids, database_=database)
    absent = sorted(set(ids) - {r["id"] for r in found})
    if absent:
        raise ValueError("not in the database (load it first), nothing applied: %s" % absent)
    with driver.session(database=database) as session:
        session.execute_write(lambda tx: apply_decisions(tx, Counter(), [apply_row(d) for d in accepted]))


def stamp(accepted: list[dict], workbook: bytes) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    sha = hashlib.sha256(workbook).hexdigest()
    return [{**d, "imported_at": now, "workbook_sha256": sha} for d in accepted]


__all__ = ["append_decisions", "apply", "check_rows", "current_facts", "report", "stamp"]
