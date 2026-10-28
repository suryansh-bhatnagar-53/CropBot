"""Check each table part against its PDF page (docling-parse, the same text layer Docling read).

  rows     docling row count == bands between the horizontal ruling lines in the table box
  columns  per row: the page shows the full grid width or the merged cell count;
           a cell spanning several columns must not have a vertical ruling inside it
  text     each cell's text == the page words whose centres fall inside the cell box
A part without ruling lines is "not verifiable"; its cell text is still checked.
Mismatches go to review; nothing is corrected.
"""

import warnings

from .stitch import Part, ws

TOL = 3.0


def _merge(values: list[float]) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > TOL:
            out.append(v)
    return out


def _bottom_left(box: dict, height: float) -> tuple[float, float, float, float]:
    """(l, b, r, t) with y growing upwards."""
    if box["origin"] == "BOTTOMLEFT":
        return box["l"], box["b"], box["r"], box["t"]
    return box["l"], height - box["b"], box["r"], height - box["t"]


def rulings(part: Part, page: dict) -> tuple[list, list]:
    """The ruling segments in a part's table box: horizontal (y, x0, x1) and vertical (x, y0, y1)."""
    h = page["height"]
    l, b, r, t = _bottom_left(part.bbox, h)

    def inbox(x0, y0, x1, y1):
        return l - 4 <= min(x0, x1) and max(x0, x1) <= r + 4 and b - 4 <= min(y0, y1) and max(y0, y1) <= t + 4

    H = [(y0, min(x0, x1), max(x0, x1)) for (x0, y0), (x1, y1) in page["segments"]
         if abs(y0 - y1) < 1.5 and abs(x1 - x0) > 15 and inbox(x0, y0, x1, y1)]
    V = [(x0, min(y0, y1), max(y0, y1)) for (x0, y0), (x1, y1) in page["segments"]
         if abs(x0 - x1) < 1.5 and abs(y1 - y0) > 6 and inbox(x0, y0, x1, y1)]
    return H, V


class PageChecker:
    def __init__(self, pdf_path):
        from docling_parse.pdf_parser import DoclingPdfParser
        self.pdf = DoclingPdfParser(loglevel="fatal").load(path_or_stream=str(pdf_path))
        self._pages: dict[int, dict] = {}

    def page(self, n: int) -> dict:
        if n not in self._pages:
            from docling_core.types.doc.page import TextCellUnit
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                p = self.pdf.get_page(n)
            words = [((w.rect.r_x0 + w.rect.r_x2) / 2, (w.rect.r_y0 + w.rect.r_y2) / 2, w.text)
                     for w in p.iterate_cells(unit_type=TextCellUnit.WORD)]
            segs = []
            for s in p.shapes:
                pts = [(q.x, q.y) for q in s.points]
                segs += list(zip(pts, pts[1:]))
            self._pages[n] = {"height": p.dimension.height, "words": words, "segments": segs}
        return self._pages[n]

    def check(self, part: Part) -> tuple[dict, list[dict]]:
        """(summary, problems) for one part."""
        page = self.page(part.pdf_page)
        h = page["height"]
        l, b, r, t = _bottom_left(part.bbox, h)
        hs, vs = [], []
        for (x0, y0), (x1, y1) in page["segments"]:
            if not (l - 4 <= min(x0, x1) <= r + 4 and b - 4 <= min(y0, y1) <= t + 4):
                continue
            if abs(y0 - y1) < 1.5 and abs(x1 - x0) > 15:
                hs.append(y0)
            elif abs(x0 - x1) < 1.5 and abs(y1 - y0) > 6:
                vs.append((x0, min(y0, y1), max(y0, y1)))
        hlines = _merge(hs)
        problems = []
        summary = {"table_ref": part.ref, "pdf_page": part.pdf_page, "docling_rows": part.num_rows,
                   "docling_cols": part.num_cols, "ruled": len(hlines) >= 2 and len(vs) >= 2}

        def problem(check, detail, docling, page_value):
            problems.append({"table_ref": part.ref, "pdf_page": part.pdf_page, "check": check,
                             "detail": detail, "docling": docling, "page": page_value})

        if summary["ruled"]:
            page_rows = len(hlines) - 1
            summary["page_rows"] = page_rows
            if page_rows != part.num_rows:
                problem("rows", "row count differs from the ruled bands", part.num_rows, page_rows)
            for row in part.rows:
                boxes = [_bottom_left(c["bbox"], h) for c in row if c["bbox"]]
                if not boxes:
                    continue
                yc = sum((bb[1] + bb[3]) / 2 for bb in boxes) / len(boxes)
                xs = _merge([x for x, y_lo, y_hi in vs if y_lo - 1 <= yc <= y_hi + 1])
                for c in row:                      # a merged cell must not cross a ruling on the page
                    if c["col_span"] > 1 and c["bbox"]:
                        cl, _, cr, _ = _bottom_left(c["bbox"], h)
                        inner = [x for x in xs if cl + TOL < x < cr - TOL]
                        if inner:
                            problem("merged across a ruling", "row %d col %d spans %d columns"
                                    % (c["row"], c["col"], c["col_span"]), c["text"],
                                    "%d ruling(s) inside the cell" % len(inner))
                page_cols = max(len(xs) - 1, 0)
                # the page may show the full grid (spanned or empty cells drawn as separate
                # columns) or the merged view; anything else is a column problem
                if page_cols not in (part.num_cols, len(row)):
                    problem("columns", "row %d: cells vs vertical rulings (grid width %d)"
                            % (row[0]["row"], part.num_cols), len(row), page_cols)
        else:
            problem("not verifiable", "no ruling lines in the table box", part.num_rows, None)

        order_only = 0
        for c in part.cells:
            if not c["bbox"]:
                continue
            cl, cb, cr, ct = _bottom_left(c["bbox"], h)
            inside = [(x, y, w) for x, y, w in page["words"]
                      if cl - 1 <= x <= cr + 1 and cb - 1 <= y <= ct + 1]
            layer = ws(" ".join(w for _, _, w in sorted(inside, key=lambda v: (-round(v[1]), v[0]))))
            if layer == c["text"]:
                continue
            if sorted(layer.split()) == sorted(c["text"].split()):
                order_only += 1      # same words; superscripts or stacked lines read in another order
            else:
                problem("text", "row %d col %d" % (c["row"], c["col"]), c["text"], layer)
        summary["text_mismatches"] = sum(1 for p in problems if p["check"] == "text")
        summary["text_order_only"] = order_only
        return summary, problems
