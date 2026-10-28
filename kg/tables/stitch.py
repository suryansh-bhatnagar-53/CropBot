"""Collapse merged cells and stitch tables split across pages. No LLM.

Merged cells: rows are built from Docling's unique table_cells, so a cell that
spans columns appears once with its col_span (the grid repeats it). The
original cells are kept on every part for traceability.

Stitching, within one unit and in reading order: table B continues table A when
B is on the next page, only tables lie between them, and the widths match (equal
grid widths, or equal merged widths when a label column is split in one part).
  B's first cell is "Particulars"         -> always a new (variety) table
  B's first row == A's header             -> repeated header, dropped
  B's first cell == A's first header cell -> a new table
  otherwise                               -> B's first row is data, even if Docling flagged it a header
A row split by the page break leaves B's first row with no first-column cell (or an empty one).
That piece is merged into A's last row, cell by cell in the same column; each merged cell keeps
the piece in `continued_from`, and the merge is logged and sent to review (never silent).
"""

import re
from dataclasses import dataclass, field


def ws(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


@dataclass
class Part:
    ref: str
    pdf_page: int
    num_rows: int
    num_cols: int
    cells: list[dict]                  # unique cells: row, col, row_span, col_span, text, header, bbox
    rows: list[list[dict]]             # cells grouped by start row, ordered by column
    bbox: dict | None = None           # table box on the page
    docling_cells: list[dict] | None = None   # Docling's own cells, when kg.tables.rebuild changed any


@dataclass
class Table:
    unit_id: str
    section_path: str
    chapter: str
    parts: list[Part] = field(default_factory=list)
    header: list[str] | None = None    # first row of the first part, when Docling flagged it a header
    header_cells: list[dict] = field(default_factory=list)  # the header row's cells (tagged)
    rows: list[list[dict]] = field(default_factory=list)   # data rows; each cell keeps its part ref
    stitch_log: list[str] = field(default_factory=list)
    merged_rows: list[dict] = field(default_factory=list)  # rows continued across a page break

    @property
    def refs(self) -> list[str]:
        return [p.ref for p in self.parts]

    @property
    def num_cols(self) -> int:
        return self.parts[0].num_cols


def part_from(item) -> Part:
    prov = item.prov[0]
    cells = []
    for c in item.data.table_cells:
        cells.append({"row": c.start_row_offset_idx, "col": c.start_col_offset_idx,
                      "row_span": c.row_span, "col_span": c.col_span, "text": ws(c.text),
                      "header": bool(c.column_header), "bbox": _box(c.bbox)})
    rows: dict[int, list[dict]] = {}
    for c in sorted(cells, key=lambda c: (c["row"], c["col"])):
        rows.setdefault(c["row"], []).append(c)
    return Part(item.self_ref, prov.page_no, item.data.num_rows, item.data.num_cols, cells,
                [rows[r] for r in sorted(rows)], _box(prov.bbox))


def _box(b) -> dict | None:
    if b is None:
        return None
    return {"l": b.l, "t": b.t, "r": b.r, "b": b.b, "origin": b.coord_origin.value}


def _texts(row: list[dict]) -> list[str]:
    return [c["text"] for c in row]


def _tag(row: list[dict], part: Part) -> list[dict]:
    return [{**c, "part_ref": part.ref, "pdf_page": part.pdf_page, "part_cols": part.num_cols} for c in row]


def _same_width(prev: "Table", part: Part) -> bool:
    """Equal grid widths, or equal merged widths (a split label column changes the grid only)."""
    if part.num_cols == prev.num_cols:
        return True
    last = prev.header if prev.header else [c["text"] for c in prev.rows[-1]] if prev.rows else []
    return bool(part.rows) and len(last) == len(part.rows[0])


def _start(unit: dict, part: Part) -> Table:
    t = Table(unit["id"], unit["section_path"], unit["chapter"]["title"], [part])
    first = part.rows[0] if part.rows else []
    if first and all(c["header"] for c in first):
        t.header, t.header_cells = _texts(first), _tag(first, part)
        t.rows = [_tag(r, part) for r in part.rows[1:]]
    else:
        t.rows = [_tag(r, part) for r in part.rows]
    return t


def stitch_unit(unit: dict, items_by_ref: dict, prepare=None) -> list[Table]:
    """Tables of one unit, with continuations stitched on. `prepare` (kg.tables.rebuild) may replace each
    part before stitching, so a page-break merge continues the corrected cells."""
    order = [i for i in unit["items"]]
    tables: list[Table] = []
    last_index = None
    for idx, item in enumerate(order):
        if item["kind"] != "table":
            continue
        found = items_by_ref[item["ref"]]
        part = found if isinstance(found, Part) else part_from(found)       # a transcription gives a Part
        if prepare is not None:
            part = prepare(part)
        prev = tables[-1] if tables else None
        between_only_tables = last_index is not None and all(
            order[k]["kind"] == "table" for k in range(last_index + 1, idx))
        last_index = idx
        first = _texts(part.rows[0]) if part.rows else []
        starts_new = bool(first) and re.sub(r"[^a-z]", "", first[0].lower()) == "particulars"
        if (prev is None or not between_only_tables or part.pdf_page != prev.parts[-1].pdf_page + 1
                or starts_new or not _same_width(prev, part)):
            tables.append(_start(unit, part))
            continue
        if prev.header and first == prev.header:
            prev.parts.append(part)
            prev.rows += [_tag(r, part) for r in part.rows[1:]]
            prev.stitch_log.append("%s: repeated header dropped" % part.ref)
        elif prev.header and first and first[0] == prev.header[0]:
            tables.append(_start(unit, part))          # same kind of table, new header
        else:
            prev.parts.append(part)
            rows = [_tag(r, part) for r in part.rows]
            if rows and _merge_split_row(prev, rows[0], part):
                rows = rows[1:]
            prev.rows += rows
            note = "first row was flagged a header, kept as data" if all(
                c["header"] for c in part.rows[0]) else "continues"
            prev.stitch_log.append("%s: %s" % (part.ref, note))
    return [piece for t in tables for piece in _split_at_inner_headers(t)]


def _merge_split_row(prev: Table, row: list[dict], part: Part) -> bool:
    """Merge a page-split row piece (no first-column cell, or an empty one) into prev's last row.
    Only when every cell of the piece has a cell in the same column to continue."""
    if not prev.rows:
        return False
    first = next((c for c in row if c["col"] == 0), None)
    if first is not None and first["text"]:
        return False
    target = {c["col"]: c for c in prev.rows[-1]}
    piece = [c for c in row if c["text"]]
    if not piece or any(c["col"] not in target for c in piece):
        return False
    for c in piece:
        t = target[c["col"]]
        t["continued_from"] = t.get("continued_from", []) + [
            {"part_ref": part.ref, "row": c["row"], "col": c["col"], "text": c["text"]}]
        t["text"] = ("%s %s" % (t["text"], c["text"])).strip()
    head = prev.rows[-1][0]
    prev.merged_rows.append({"into": "%s row %d" % (head["part_ref"], head["row"]), "part_ref": part.ref,
                             "row": row[0]["row"], "pdf_page": part.pdf_page,
                             "text": " | ".join(c["text"] for c in piece)})
    prev.stitch_log.append("%s row %d: row continued across the page break, merged into %s row %d" % (
        part.ref, row[0]["row"], head["part_ref"], head["row"]))
    return True


def _is_particulars(text: str) -> bool:
    return re.sub(r"[^a-z]", "", text.lower()) == "particulars"


def _split_at_inner_headers(t: Table) -> list[Table]:
    """Docling sometimes puts the end of one variety table and the start of the next in one
    table: a "Particulars" row in the middle starts a new table."""
    pieces, current = [], t
    rows, current.rows = current.rows, []
    for row in rows:
        if row and _is_particulars(row[0]["text"]) and current.rows:
            ref = row[0]["part_ref"]
            part = next(p for p in t.parts if p.ref == ref)
            pieces.append(current)
            current = Table(t.unit_id, t.section_path, t.chapter, [part], header=_texts(row),
                            header_cells=row,
                            stitch_log=["split from inside %s at a 'Particulars' row" % ref])
            continue
        current.rows.append(row)
    pieces.append(current)
    return pieces
