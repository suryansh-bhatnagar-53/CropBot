"""Conversion report: OCR pages, every table with its table_ref, and checks against converted/.

The checks compare two sections against the committed MVP conversion
(converted/<id>.index.json, docling 2.140.0, run on the GX10): the rice wet
nursery section and the BPH row of the ETL table.
"""

import json
import re

from kg.registry import ROOT

COMMITTED = {"source:tnau_agriculture_2020": ROOT / "converted" / "tnau_agriculture.index.json"}
BPH_QUOTE = ("1 hopper/ tiller in the absence of predatory spider and 2 hoppers / tiller "
             "when spider is present at 1/hill.")


def ws(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def build_report(out, entry, meta) -> dict:
    from docling_core.types.doc import DoclingDocument
    doc = DoclingDocument.load_from_json(out / "document.json")
    tables = []
    for t in doc.tables:
        page = t.prov[0].page_no if t.prov else None
        grid = t.data.grid
        tables.append({
            "table_ref": t.self_ref, "pdf_page": page,
            "printed_page": entry.printed_page(page) if page else None,
            "rows": t.data.num_rows, "cols": t.data.num_cols,
            "header": [ws(c.text)[:28] for c in grid[0]] if grid else [],
        })
    report = {
        "source_id": entry.id, "pages": meta["pages"], "device": meta["device"],
        "versions": meta["versions"], "settings": meta["settings"],
        "seconds_model_load": meta["seconds_model_load"], "seconds_convert": meta["seconds_convert"],
        "seconds_per_page": round(meta["seconds_convert"] / max(meta["pages"], 1), 2),
        "ocr": meta["ocr"], "tables": tables,
    }
    committed = COMMITTED.get(entry.id)
    if committed and committed.exists():
        items = json.loads(committed.read_text(encoding="utf-8"))["items"]
        report["wet_nursery"] = compare_wet_nursery(doc, items)
        report["bph_etl"] = compare_bph(doc, items)
    return report


def _page_texts(doc, page: int) -> list[str]:
    out = []
    for item, _ in doc.iterate_items():
        prov = getattr(item, "prov", None) or []
        if prov and prov[0].page_no == page and getattr(item, "text", None):
            out.append(ws(item.text))
    return out


def compare_wet_nursery(doc, items) -> dict:
    """Every committed item of "1.1.1. Wet nursery" (up to "1.1.2. Dry nursery") vs the new text."""
    start = next(i for i, it in enumerate(items) if it["k"] == "h" and "Wet nursery" in (it["t"] or ""))
    end = next(i for i, it in enumerate(items) if i > start and it["k"] == "h"
               and "Dry nursery" in (it["t"] or ""))
    pages = sorted({it["pg"] for it in items[start:end]})
    new = {p: _page_texts(doc, p) for p in pages}
    same, joined, changed = 0, 0, []
    for it in items[start:end]:
        text = ws(it.get("t") or it.get("md"))
        if it["k"] in ("tbl", "img") or not text:
            continue
        if text in new[it["pg"]]:
            same += 1
        elif text in " ".join(new[it["pg"]]):
            joined += 1          # same words, split or merged into different items
        else:
            changed.append({"pdf_page": it["pg"], "kind": it["k"], "committed": text[:160]})
    return {"pdf_pages": pages, "committed_items": same + joined + len(changed),
            "identical": same, "same_text_split_differently": joined, "missing_or_changed": changed}


def compare_bph(doc, items) -> dict:
    """The BPH ETL row on p. 64: is the committed cell text in a new table, unchanged?"""
    # the committed ETL table: the tables after the "Economic threshold level" heading,
    # up to the "Pests | Management strategies" table that follows it
    start = next(i for i, it in enumerate(items)
                 if it["k"] == "h" and "Economic threshold level" in (it["t"] or ""))
    committed_rows = set()
    for it in items[start + 1:]:
        rows = [[ws(c) for c in line.strip("|").split("|")] for line in (it.get("md") or "").splitlines()]
        if it["k"] != "tbl" or (rows and rows[0][0] == "Pests"):
            break
        committed_rows |= {r[0] for r in rows if r and r[0] and not set(r[0]) <= set("-: ")}
    found, new_rows, etl_refs = None, set(), []
    for t in doc.tables:
        page = t.prov[0].page_no if t.prov else None
        grid = t.data.grid
        if page not in (63, 64) or not grid or ws(grid[0][0].text) in ("Pests", ""):
            continue                     # not part of the ETL table
        etl_refs.append(t.self_ref)
        for r, row in enumerate(grid):
            texts = [ws(c.text) for c in row]
            if texts and texts[0]:
                new_rows.add(texts[0])
            for c, text in enumerate(texts):
                if "1 hopper/" in text or "1 hopper /" in text:
                    found = {"table_ref": t.self_ref, "pdf_page": page, "row": r, "col": c,
                             "row_label": texts[0], "text": text,
                             "identical_to_committed": text == BPH_QUOTE}
    pest_rows = {r for r in committed_rows if r not in ("Pest", "Pests")}
    return {"bph_cell": found, "etl_table_refs": etl_refs,
            "committed_first_column": sorted(pest_rows),
            "missing_from_new_tables": sorted(pest_rows - new_rows)}


def print_report(r: dict) -> None:
    print("\n=== %s: %d pages on %s ===" % (r["source_id"], r["pages"], r["device"]))
    print("docling %s, docling-core %s, easyocr %s"
          % (r["versions"]["docling"], r["versions"]["docling-core"], r["versions"]["easyocr"]))
    print("model load %.0f s, convert %.0f s = %.2f s/page"
          % (r["seconds_model_load"], r["seconds_convert"], r["seconds_per_page"]))
    print("pages with OCR text:", r["ocr"]["pages_with_ocr_text"] or "none")
    print("pages without a text layer:", r["ocr"]["pages_without_text_layer"] or "none")
    print("pages without any text:", r["ocr"]["pages_without_any_text"] or "none")
    print("tables: %d" % len(r["tables"]))
    for t in r["tables"]:
        print("  %-12s PDF p.%-3s printed p.%-4s %3dx%-2d %s" % (
            t["table_ref"], t["pdf_page"], t["printed_page"], t["rows"], t["cols"],
            " | ".join(t["header"])[:70]))
    if "wet_nursery" in r:
        w = r["wet_nursery"]
        print("wet nursery (PDF pp. %s): %d committed items: %d identical, %d same text split "
              "differently, %d missing or changed" % (
                  w["pdf_pages"], w["committed_items"], w["identical"],
                  w["same_text_split_differently"], len(w["missing_or_changed"])))
        for c in w["missing_or_changed"]:
            print("   p.%s %s: %s" % (c["pdf_page"], c["kind"], c["committed"]))
        b = r["bph_etl"]
        print("BPH ETL cell:", json.dumps(b["bph_cell"], ensure_ascii=False))
        print("ETL table parts: %s; %d committed rows, missing from the new tables: %s" % (
            ", ".join(b["etl_table_refs"]), len(b["committed_first_column"]),
            b["missing_from_new_tables"] or "none"))
