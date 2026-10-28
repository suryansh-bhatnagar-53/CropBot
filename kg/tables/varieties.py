"""Pivot variety tables (header "Particulars", one variety per column) into Variety records.

Every record is needs_review. Mapped rows fill typed fields (numbers keep their raw
text); known descriptive rows become traits "Label: value"; unknown or empty row
labels go to review. Names are never merged: possible duplicates are only reported.
"""

import re

from kg.schema.concepts import Variety
from kg.schema.core import SourceSpan

from .stitch import Table, ws

FIELDS = {"yearofrelease": "release_year", "parentage": "parentage", "durationdays": "duration",
          "averageyieldkgha": "avg_yield", "grainyieldkgha": "avg_yield", "graintype": "grain_type"}
TRAITS = {"yearofnotification", "habit", "leafsheath", "septum", "ligule", "auricle", "panicle",
          "huskcolour", "ricecolour", "graincolour", "abdominalwhite", "stem", "tillers", "heightcm",
          "daysto50flowering", "earsizeandshape", "1000grainwtg", "1000grainsweightg", "grainlbratio",
          "seedsource", "marketability", "specialfeatures"}
GRAIN_SIZE = {"length", "breadth", "thickness"}
DIVIDERS = {"morphologicalcharacters"}
EMPTY = {"", "-", "--", "---"}
GENERIC = {"tnau", "rice", "wheat", "samba", "hybrid", "variety", "paddy"}


def key(label: str) -> str:
    return re.sub(r"[^a-z0-9]", "", label.lower())


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def is_variety_table(t: Table) -> bool:
    return bool(t.header) and key(t.header[0]) == "particulars"


def _number(text: str) -> float | None:
    return float(text) if re.fullmatch(r"\d+(?:\.\d+)?", text) else None


def pivot(t: Table, entry, chapter, duration_group: str | None) -> tuple[list[Variety], list[dict]]:
    """Variety records from one stitched variety table, and review rows."""
    review, records = [], []
    first = t.parts[0]
    header_cells = t.header_cells[1:]                 # the first header cell is the label ("Particulars")
    names = [c["text"] for c in header_cells]
    crop_id = chapter.crop_id if chapter.status == "approved" else None
    builds, skip = [], set()
    for j, cell in enumerate(header_cells):
        name = cell["text"]
        if cell["col_span"] > 1:     # a name cell across several variety columns: names merged
            review.append({"check": "variety", "table_ref": cell["part_ref"], "pdf_page": cell["pdf_page"],
                           "detail": "variety name cell spans %d columns: %r" % (cell["col_span"], name),
                           "docling": name, "page": None})
            skip.add(j)
            continue
        span = SourceSpan(id="span:%s_%s_t%s" % (entry.id.split(":", 1)[1], slug(name),
                                                 cell["part_ref"].split("/")[-1]),
                          source_id=entry.id, pdf_page=cell["pdf_page"],
                          printed_page=entry.printed_page(cell["pdf_page"]), section_path=t.section_path,
                          quote=name, table_ref=cell["part_ref"], table_row=cell["row"],
                          table_col=cell["col"], extraction_method="table_parse")
        builds.append({"id": "variety:" + slug(name), "name_en": name, "name": name, "crop_id": crop_id,
                       "kind": "hybrid" if "hybrid" in name.lower() else None,
                       "duration_group": duration_group, "review_status": "needs_review",
                       "source": "%s %s" % (entry.id, first.ref), "traits": [], "raw": {}, "cells": {},
                       "evidence": [span], "_col": j})

    def flag(row_label, reason, cell=None):
        review.append({"check": "variety", "table_ref": cell["part_ref"] if cell else first.ref,
                       "pdf_page": cell["pdf_page"] if cell else first.pdf_page,
                       "detail": "%s: %r" % (reason, row_label), "docling": cell["text"] if cell else None,
                       "page": None})

    n = len(names)
    prefix = None
    for row in t.rows:
        # values sit in the last n columns of their part; label cells are to their left
        vstart = row[0]["part_cols"] - n
        if vstart < 1:
            flag(row[0]["text"], "row narrower than the %d variety columns" % n, row[0])
            continue
        label = ws(" ".join(c["text"] for c in row if c["col"] < vstart))
        k = key(label)
        spans_into_values = any(c["col"] < vstart < c["col"] + c["col_span"] for c in row)
        if k in DIVIDERS or k == "grainsizemm":                    # divider rows, spanned or not
            prefix = label if k == "grainsizemm" else None
            continue
        if spans_into_values:
            whole = len(row) == 1                                  # one cell across the row: a divider
            flag(label, "unmapped divider row" if whole else
                 "ambiguous columns: a cell straddles the label and value columns", row[0])
            prefix = None
            continue
        if k in GRAIN_SIZE and prefix:
            target = ("trait", "%s %s" % (prefix, label))
        elif k in FIELDS:
            target, prefix = ("field", FIELDS[k]), None
        elif k in TRAITS:
            target, prefix = ("trait", label), None
        else:
            flag(label, "empty row label" if not k else "unmapped row label", row[0])
            continue
        values = {}
        for c in row:
            if c["col"] < vstart:
                continue
            if c["col_span"] > 1:      # never copied to several varieties: it may be two values merged
                flag(label, "value cell spans %d variety columns" % c["col_span"], c)
                continue
            values[c["col"] - vstart] = c
        for b in builds:
            cell = values.get(b["_col"])
            if cell is None or cell["text"] in EMPTY:
                continue
            text, where = cell["text"], {"table_ref": cell["part_ref"], "row": cell["row"], "col": cell["col"],
                                         "pdf_page": cell["pdf_page"],
                                         "printed_page": entry.printed_page(cell["pdf_page"]), "text": cell["text"]}
            kind, name = target
            if kind == "trait":
                b["traits"].append("%s: %s" % (name, text))
                b["cells"][name] = where
                continue
            b["cells"][name] = where
            if name == "release_year":
                if re.fullmatch(r"\d{4}", text):
                    b["release_year"], b["raw"]["release_year"] = int(text), text
                else:
                    flag(label, "release year not a plain year for %s" % b["name"], cell)
            elif name == "duration":
                m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)", text) or \
                    re.fullmatch(r"(\d+(?:\.\d+)?)", text)
                if m:
                    lo, hi = float(m.group(1)), float(m.groups()[-1])
                    b.update(duration_days_min=lo, duration_days_max=hi)
                    b["raw"]["duration_days_min"] = b["raw"]["duration_days_max"] = text
                else:
                    flag(label, "duration not a number or range for %s" % b["name"], cell)
            elif name == "avg_yield":
                v = _number(text)
                if v is not None:
                    b["avg_yield_kg_ha"], b["raw"]["avg_yield_kg_ha"] = v, text
                else:
                    flag(label, "yield not a plain number for %s" % b["name"], cell)
            else:
                b[name] = text
    for b in builds:
        b.pop("_col")
        if not b["cells"]:
            flag(b["name"], "no values pivoted for this variety", None)
        records.append(Variety.model_validate(b))
    return records, review


def possible_duplicates(records: list[Variety], mentions: list[str]) -> list[dict]:
    """Pairs whose numbers match and whose code words are a subset of the other's."""
    def sig(name):
        toks = [t for t in re.findall(r"[a-z]+|\d+", name.lower()) if t not in GENERIC]
        return {t for t in toks if t.isdigit()}, {t for t in toks if not t.isdigit()}

    names = [(r.name, r.id) for r in records] + [(m, None) for m in mentions]
    out, seen = [], set()
    for i, (a, aid) in enumerate(names):
        for b, bid in names[i + 1:]:
            if aid is None and bid is None or slug(a) == slug(b):
                continue
            (na, wa), (nb, wb) = sig(a), sig(b)
            if na and na == nb and (wa <= wb or wb <= wa):
                pair = tuple(sorted((a, b)))
                if pair not in seen:
                    seen.add(pair)
                    out.append({"a": a, "a_id": aid, "b": b, "b_id": bid})
    return out


def duration_outliers(records: list[Variety], reference: dict[str, float]) -> list[dict]:
    """Varieties whose duration is nearer another group's reference than their own."""
    out = []
    for r in records:
        if not (r.duration_group and r.duration_days_min is not None and reference):
            continue
        mid = (r.duration_days_min + r.duration_days_max) / 2
        nearest = min(reference, key=lambda g: abs(reference[g] - mid))
        if nearest != r.duration_group.value:
            out.append({"variety": r.id, "group": r.duration_group.value, "duration_days": r.raw.get(
                "duration_days_min"), "nearer_to": nearest, "reference": reference})
    return out


def duration_reference(tables: list[Table]) -> tuple[dict[str, float], str | None]:
    """Reference durations from the book's own table, e.g. "Stages | Short (105) | Medium (135) | Long (150)"."""
    for t in tables:
        cells = (t.header or []) + [c["text"] for row in t.rows[:1] for c in row]
        found = {g.lower(): float(n) for g, n in
                 (re.match(r"(Short|Medium|Long)\s*\((\d+)\)", c).groups() for c in cells
                  if re.match(r"(Short|Medium|Long)\s*\((\d+)\)", c))}
        if len(found) == 3:
            return found, t.parts[0].ref
    return {}, None


def duration_group_of(section_path: str) -> str | None:
    m = re.search(r"\b(SHORT|MEDIUM|LONG) DURATION VARIETIES\b", section_path.upper())
    return m.group(1).lower() if m else None


def variety_mentions(units: list[dict], tables: list[Table]) -> list[str]:
    """Variety names mentioned outside variety tables: "Variety : A, B" lines and zone-table cells."""
    out = []
    for u in units:
        for i in u["items"]:
            m = re.match(r"^\s*Variet(?:y|ies)\s*:\s*(.+)$", i.get("text") or "")
            if m:
                out += [ws(x) for x in m.group(1).split(",") if ws(x)]
    for t in tables:
        if t.header and key(t.header[-1]) == "varieties":
            for row in t.rows:
                if len(row) == len(t.header):
                    out += [ws(x).rstrip("*") for x in row[-1]["text"].split(",") if ws(x)]
    return sorted(set(out))
