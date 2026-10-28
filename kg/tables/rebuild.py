"""Rebuild a ruled table part's cell text from the PDF text layer (step 8, approved 2026-10-21). No LLM.

  uv run python -m kg.tables.rebuild source:tnau_agriculture_2020   # the before/after diff for rice and wheat

Docling sometimes puts a printed line in the cell next to it (p. 66: the BPH cell's last line, "Pymetrozine 50%
WG 300g", in the WBPH cell). Where a part has rulings, the rulings decide which cell a printed word belongs to;
Docling keeps the skeleton (rows, columns, spans) and its own text and word order wherever they agree.

  1. Ruled cells: a grid on every ruling position; neighbouring grid units join unless a ruling covers the whole
     edge between them, so an underline under a few words never separates.
  2. Each page word goes to the Docling cell whose row and column (placed by the median centre of their one-span
     cells) sit over its ruled cell. Inside one ruled cell holding several Docling lines (no ruling between them,
     p. 34), the smallest Docling box that holds the word decides. Where no Docling row or column sits over a
     ruled cell, Docling's box decides, and the part is flagged.
  3. Docling's tokens are aligned, in order, to the page words inside its box. A cell loses exactly the tokens
     whose words went to another cell (a block at its start or end only), and gains the words printed in its
     ruled cell outside its box, at the start (printed above) or end. Every removed token is received by one
     cell; words no Docling cell read are left out, as before.
  4. All or nothing per part: a part whose words would land in a ruled cell no Docling cell sits over, or whose
     moved words are not at a cell's start or end, keeps Docling's cells and is flagged. The characters of a part
     must be identical before and after (moved, never duplicated or dropped).
  5. A cell spanning more columns than the ruled cell it prints in is narrowed to it (equal grid sizes only), so
     the page-break merge continues the right column (p. 17).
Parts without rulings keep Docling's cells. Every change and flag goes to review; values are never typed in.
"""

import copy
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .check import TOL, _bottom_left, _merge, rulings
from .stitch import Part, ws

LINE_TOL = 4.5          # half a text line: descenders and superscripts stay on their line


@dataclass
class Rebuilt:
    part: Part                                     # the part to stitch (Docling's own when nothing changed)
    changes: dict = field(default_factory=dict)    # (row, col) -> (text, (col, col_span) or None)
    flags: list[str] = field(default_factory=list)
    ruled: bool = True


def _covers(segs, a, b) -> bool:
    """Do the 1-D intervals in segs cover [a, b] (within TOL)?"""
    pos = a
    for s0, s1 in sorted(segs):
        if s0 > pos + TOL:
            return False
        pos = max(pos, s1)
        if pos >= b - TOL:
            return True
    return pos >= b - TOL


def ruled_cells(part: Part, page: dict):
    """(units by ruled cell, ys top to bottom, xs left to right, find) or None without rulings."""
    H, V = rulings(part, page)
    ys = sorted(_merge([y for y, _, _ in H]), reverse=True)
    xs = _merge([x for x, _, _ in V])
    if len(ys) < 2 or len(xs) < 2:
        return None
    nr, nc = len(ys) - 1, len(xs) - 1
    parent = {(i, j): (i, j) for i in range(nr) for j in range(nc)}

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    for i in range(nr):
        for j in range(nc - 1):
            x = xs[j + 1]
            if not _covers([(y0, y1) for vx, y0, y1 in V if abs(vx - x) <= TOL], ys[i + 1], ys[i]):
                parent[find((i, j))] = find((i, j + 1))
    for j in range(nc):
        for i in range(nr - 1):
            y = ys[i + 1]
            if not _covers([(x0, x1) for hy, x0, x1 in H if abs(hy - y) <= TOL], xs[j], xs[j + 1]):
                parent[find((i, j))] = find((i + 1, j))
    units = defaultdict(list)
    for u in parent:
        units[find(u)].append(u)
    return units, ys, xs, find


def unit_of(x, y, ys, xs) -> tuple[int, int] | None:
    """The grid unit (row band, column band) holding the point."""
    i = next((k for k in range(len(ys) - 1) if ys[k] + 0.5 >= y >= ys[k + 1] - 0.5), None)
    j = next((k for k in range(len(xs) - 1) if xs[k] - 0.5 <= x <= xs[k + 1] + 0.5), None)
    return None if i is None or j is None else (i, j)


def reading_words(words):
    """Page words (x, y, text) in reading order: lines top to bottom, each left to right."""
    lines = []
    for v in sorted(words, key=lambda v: (-v[1], v[0])):
        if lines and abs(lines[-1][0] - v[1]) <= LINE_TOL:
            lines[-1][1].append(v)
        else:
            lines.append([v[1], [v]])
    return [v for _, line in lines for v in sorted(line)]


def reading(words) -> list[str]:
    return [w for _, _, w in reading_words(words)]


def align(tokens: list[str], words: list) -> dict:
    """Docling token index -> the page word it was read from, by order-preserving matching."""
    sm = SequenceMatcher(a=tokens, b=[w for _, _, w in words], autojunk=False)
    return {blk.a + k: words[blk.b + k] for blk in sm.get_matching_blocks() for k in range(blk.size)}


def chars(text: str) -> Counter:
    return Counter(c for c in text if not c.isspace())


def changes_for(part: Part, page: dict) -> tuple[dict | None, list[str]]:
    """{(row, col): (text, (col, col_span) or None)} for the cells that change, and the part's flags."""
    built = ruled_cells(part, page)
    if built is None:
        return None, ["no rulings: Docling's cells kept"]
    units, ys, xs, find = built
    h = page["height"]
    region_words = defaultdict(list)
    for x, y, w in page["words"]:
        u = unit_of(x, y, ys, xs)
        if u:
            region_words[find(u)].append((x, y, w))
    same_grid = part.num_rows == len(ys) - 1 and part.num_cols == len(xs) - 1
    cells = [c for c in part.cells if c["bbox"]]
    box = {id(c): _bottom_left(c["bbox"], h) for c in cells}

    def anchor(index, span, axis):
        """Docling row or column index -> the ruled band under the median centre of its one-span cells."""
        pos = defaultdict(list)
        for c in cells:
            if c[span] == 1:
                l_, b_, r_, t_ = box[id(c)]
                pos[c[index]].append((l_ + r_) / 2 if axis == "x" else (b_ + t_) / 2)
        out = {}
        for k, vals in pos.items():
            v = sorted(vals)[len(vals) // 2]
            out[k] = (next((j for j in range(len(xs) - 1) if xs[j] - 0.5 <= v <= xs[j + 1] + 0.5), None)
                      if axis == "x" else
                      next((i for i in range(len(ys) - 1) if ys[i] + 0.5 >= v >= ys[i + 1] - 0.5), None))
        return out

    col_unit, row_unit = anchor("col", "col_span", "x"), anchor("row", "row_span", "y")
    reach = {id(c): ({row_unit.get(r) for r in range(c["row"], c["row"] + c["row_span"])} - {None},
                     {col_unit.get(k) for k in range(c["col"], c["col"] + c["col_span"])} - {None})
             for c in cells}

    def holds(c, x, y):
        l_, b_, r_, t_ = box[id(c)]
        return l_ - 1 <= x <= r_ + 1 and b_ - 1 <= y <= t_ + 1

    def area(c):
        return (box[id(c)][2] - box[id(c)][0]) * (box[id(c)][3] - box[id(c)][1])

    def page_words_in(c):
        return [v for v in page["words"] if holds(c, v[0], v[1]) and unit_of(v[0], v[1], ys, xs)]

    assigned = defaultdict(list)              # id(cell) -> page words
    orphan_words, by_box = [], set()
    for root, words in region_words.items():
        us = units[root]
        cands = [c for c in cells if any(i in reach[id(c)][0] and j in reach[id(c)][1] for i, j in us)]
        for x, y, w in words:
            pool, fallback = cands, False
            if not pool:                                            # no Docling row or column sits here
                pool, fallback = [c for c in cells if holds(c, x, y)], True
            if not pool:
                orphan_words.append((x, y, w))
                continue
            owner = pool[0]
            if len(pool) > 1:                                       # lines Docling split inside a ruled cell
                holding = [c for c in pool if box[id(c)][1] - 1 <= y <= box[id(c)][3] + 1]
                if len(holding) > 1:
                    holding = [c for c in holding if box[id(c)][0] - 1 <= x <= box[id(c)][2] + 1] or holding
                owner = min(holding, key=area) if holding else min(
                    pool, key=lambda c: min(abs(y - box[id(c)][1]), abs(y - box[id(c)][3])))
            assigned[id(owner)].append((x, y, w))
            if fallback:
                by_box.add((owner["row"], owner["col"]))
    flags, changes = [], {}
    orphan_set = set(orphan_words)
    # Docling's tokens aligned to the page words inside its box; words assigned to a cell but printed outside
    # its box are candidates to move in
    info = {}
    for c in cells:
        old = c["text"].split()
        info[id(c)] = {"old": old, "aligned": align(old, reading_words(page_words_in(c))), "block_out": set(),
                       "cand_in": [v for v in reading_words(assigned.get(id(c), [])) if not holds(c, v[0], v[1])]}
    # tokens at a cell's start or end that align to nothing in its box but equal a run of words moving into
    # another cell were read by Docling from outside the box (p. 71): they move out of this cell
    read = {v for d in info.values() for v in d["aligned"].values()}
    for c in cells:
        d = info[id(c)]
        n = len(d["old"])
        first, last = min(d["aligned"], default=n), max(d["aligned"], default=-1)
        for block in (list(range(0, first)), list(range(last + 1, n))):
            toks = [d["old"][k] for k in block]
            if not toks:
                continue
            for o in cells:
                seq = [w for _, _, w in info[id(o)]["cand_in"]] if o is not c else []
                hit = next((s for s in range(len(seq) - len(toks) + 1) if seq[s:s + len(toks)] == toks), None)
                if hit is not None:
                    d["block_out"] |= set(block)
                    read |= set(info[id(o)]["cand_in"][hit:hit + len(toks)])
                    break
    # an unaligned token inside a moving block (a glyph read slightly off its line, the "❖" on p. 69) pairs
    # with an unread word of the same text moving into another cell
    for c in cells:
        d = info[id(c)]
        mine_c = set(assigned.get(id(c), []))
        outs = {k for k, v in d["aligned"].items() if v not in mine_c} | d["block_out"]
        n = len(d["old"])
        if not outs:
            continue
        block = range(0, max(outs) + 1) if min(outs) == 0 else range(min(outs), n) if max(outs) == n - 1 else ()
        for k in block:
            if k in outs or k in d["aligned"]:
                continue
            spare = next((v for o in cells if o is not c for v in info[id(o)]["cand_in"]
                          if v not in read and v[2] == d["old"][k]), None)
            if spare is not None:
                read.add(spare)
                d["block_out"].add(k)
    if by_box:
        flags.append("ruled cells with no Docling row or column; their words follow Docling's boxes into %s"
                     % sorted(by_box))
    if orphan_words:
        flags.append("words in ruled cells with no Docling cell (a row or column Docling lacks): %s"
                     % ws(" ".join(reading(orphan_words)))[:120])
    # per cell, the tokens to remove: their page words went to another cell, or the steps above matched them
    plan = {}
    for c in cells:
        words = assigned.get(id(c), [])
        new_col = None
        if same_grid and c["col_span"] > 1 and words:               # narrow a span to the ruled cell it prints in
            cols = sorted({j for x, y, _ in words for _, j in units[find(unit_of(x, y, ys, xs))]})
            if len(cols) < c["col_span"] and cols == list(range(cols[0], cols[-1] + 1)):
                new_col = (cols[0], len(cols))
        d = info[id(c)]
        if chars(c["text"]) == chars(ws(" ".join(reading(words)))):
            if new_col:
                changes[(c["row"], c["col"])] = (c["text"], new_col)
            continue
        mine = set(words)
        out = sorted({k for k, v in d["aligned"].items() if v not in mine} | d["block_out"])
        if any(k in d["aligned"] and d["aligned"][k] in orphan_set for k in out):
            flags.append("r%d c%d kept: %s would go to a row or column Docling lacks"
                         % (c["row"], c["col"], " ".join(d["old"][k] for k in out)))
            continue
        n, m = len(d["old"]), len(out)
        if out and out != list(range(m)) and out != list(range(n - m, n)):   # a block at the start or end only
            flags.append("r%d c%d kept: the words to remove are not at its start or end: %s"
                         % (c["row"], c["col"], " ".join(d["old"][k] for k in out)))
            continue
        plan[id(c)] = (c, out, new_col)
    # moves balance: every removed token is received by one cell, from the words printed in that cell's ruled
    # cell outside its box, first those some Docling cell read, then unread ones of the same text
    removed = Counter(info[id(c)]["old"][k] for c, out, _ in plan.values() for k in out)
    receive = defaultdict(list)
    for stage in (True, False):
        for c, _, _ in plan.values():
            for v in info[id(c)]["cand_in"]:
                if (v in read) == stage and removed[v[2]] > 0 and v not in receive[id(c)]:
                    receive[id(c)].append(v)
                    removed[v[2]] -= 1
    received = {v for vs in receive.values() for v in vs}
    unread = sorted({v for d in info.values() for v in d["cand_in"]} - read - received, key=lambda v: (-v[1], v[0]))
    if unread:
        flags.append("words the text layer has but no Docling cell read (left out, as before): %s"
                     % " ".join(w for _, _, w in unread)[:120])
    for c, out, new_col in plan.values():
        d = info[id(c)]
        kept_idx = [k for k in range(len(d["old"])) if k not in set(out)]
        kept = [d["old"][k] for k in kept_idx]
        in_words = receive[id(c)]
        if in_words:
            kept_ys = [d["aligned"][k][1] for k in kept_idx if k in d["aligned"]]
            top = max(kept_ys) if kept_ys else None
            above = [v for v in in_words if top is not None and v[1] > top + LINE_TOL]
            below = [v for v in in_words if v not in above]
            kept = reading(above) + kept + reading(below)
        text = ws(" ".join(kept))
        if text != c["text"] or new_col:
            changes[(c["row"], c["col"])] = (text, new_col)
    if changes and any(" kept: " in f for f in flags):               # all or nothing per part
        flags.append("part kept as Docling read it: %d proposed change(s) withdrawn because a cell was kept"
                     % len(changes))
        return {}, flags
    before = sum((chars(c["text"]) for c in cells), Counter())
    after = sum((chars(changes[(c["row"], c["col"])][0]) if (c["row"], c["col"]) in changes else chars(c["text"])
                 for c in cells), Counter())
    if before != after:                                              # moved, never duplicated or dropped
        flags.append("part kept as Docling read it: the changes would not conserve its text (added %r, lost %r)"
                     % ("".join(sorted((after - before).elements()))[:60],
                        "".join(sorted((before - after).elements()))[:60]))
        return {}, flags
    return changes, flags


def rebuild(part: Part, page: dict) -> Rebuilt:
    """The part with its changes applied (Docling's cells kept in `docling_cells`; a changed cell keeps its
    Docling text in `docling_text`), or Docling's own part when nothing changes."""
    changes, flags = changes_for(part, page)
    if changes is None:
        return Rebuilt(part, {}, flags, ruled=False)
    if not changes:
        return Rebuilt(part, {}, flags)
    cells = copy.deepcopy(part.cells)
    for c in cells:
        key = (c["row"], c["col"])
        if key in changes:
            text, new_col = changes[key]
            if text != c["text"]:
                c["docling_text"] = c["text"]
                c["text"] = text
            if new_col:
                c["docling_col"] = (c["col"], c["col_span"])
                c["col"], c["col_span"] = new_col
    rows: dict[int, list[dict]] = {}
    for c in sorted(cells, key=lambda c: (c["row"], c["col"])):
        rows.setdefault(c["row"], []).append(c)
    new = Part(part.ref, part.pdf_page, part.num_rows, part.num_cols, cells, [rows[r] for r in sorted(rows)],
               part.bbox, docling_cells=part.cells)
    return Rebuilt(new, changes, flags)


CROSSES_ROW = "crosses a row ruling"
CROSSES_COLUMN = "crosses a column ruling"
SPAN_WIDER = "span wider than its ruled cell"


def crossings(part: Part, page: dict) -> list[dict]:
    """Step 8 checks on Docling's own cells (review only):
      - a one-row cell whose box contains one ruling segment across its whole width, with printed words on
        both sides;
      - a one-column cell whose box contains one ruling segment across its whole height, with words on both
        sides;
      - a cell spanning more columns than the ruled cell its words print in (equal grid sizes only)."""
    built = ruled_cells(part, page)
    if built is None:
        return []
    units, ys, xs, find = built
    H, V = rulings(part, page)
    h = page["height"]
    same_grid = part.num_rows == len(ys) - 1 and part.num_cols == len(xs) - 1
    out = []

    def problem(check, c, detail, page_value):
        out.append({"table_ref": part.ref, "pdf_page": part.pdf_page, "check": check,
                    "detail": "row %d col %d: %s" % (c["row"], c["col"], detail), "docling": c["text"],
                    "page": page_value, "row": c["row"], "col": c["col"]})

    for c in part.cells:
        if not c["bbox"] or not c["text"]:
            continue
        cl, cb, cr, ct = _bottom_left(c["bbox"], h)
        words = [(x, y, w) for x, y, w in page["words"] if cl - 1 <= x <= cr + 1 and cb - 1 <= y <= ct + 1]
        # one ruling segment across the whole cell: pieces that only join up across it (p. 72, invisible paths
        # at y 500.9, one reaching into the next column) are not a printed ruling
        if c["row_span"] == 1:
            for y in _merge([hy for hy, _, _ in H if cb + TOL < hy < ct - TOL]):
                if any(abs(hy - y) <= TOL and x0 <= cl + TOL and x1 >= cr - TOL for hy, x0, x1 in H):
                    above = ws(" ".join(reading([v for v in words if v[1] > y])))
                    below = ws(" ".join(reading([v for v in words if v[1] < y])))
                    if above and below:
                        problem(CROSSES_ROW, c, "ruling at y %.1f" % y, "above: %s | below: %s" % (above, below))
        if c["col_span"] == 1:
            for x in _merge([vx for vx, _, _ in V if cl + TOL < vx < cr - TOL]):
                if any(abs(vx - x) <= TOL and y0 <= cb + TOL and y1 >= ct - TOL for vx, y0, y1 in V):
                    left = ws(" ".join(reading([v for v in words if v[0] < x])))
                    right = ws(" ".join(reading([v for v in words if v[0] > x])))
                    if left and right:
                        problem(CROSSES_COLUMN, c, "ruling at x %.1f" % x, "left: %s | right: %s" % (left, right))
        if same_grid and c["col_span"] > 1 and words:
            us = {unit_of(x, y, ys, xs) for x, y, _ in words} - {None}
            cols = sorted({j for u in us for _, j in units[find(u)]})
            if cols and len(cols) < c["col_span"]:
                problem(SPAN_WIDER, c, "spans %d columns, prints in ruled columns %s" % (c["col_span"], cols),
                        ws(" ".join(reading(words))))
    return out


def diff_lines(parts: list[Part], checker) -> list[str]:
    """The before/after diff of every part, as data/review/table_rebuild_diff.txt was written on 2026-10-21."""
    out, total = [], 0
    for part in parts:
        res = rebuild(part, checker.page(part.pdf_page))
        before = {(c["row"], c["col"]): c for c in part.cells}
        for (r, c), (text, new_col) in sorted(res.changes.items()):
            total += 1
            out.append("")
            out.append("%s p.%d r%d c%d%s" % (part.ref, part.pdf_page, r, c,
                                              "  -> col %d span %d" % new_col if new_col else ""))
            out.append("  before: %s" % before[(r, c)]["text"].encode("ascii", "backslashreplace").decode())
            out.append("  after : %s" % text.encode("ascii", "backslashreplace").decode())
        for f in res.flags:
            if not f.startswith("no rulings"):
                out.append("FLAG %s p.%d: %s" % (part.ref, part.pdf_page, f.encode("ascii", "backslashreplace").decode()))
    out += ["", "parts %d; changed cells %d" % (len(parts), total)]
    return out


def main(argv=None) -> int:
    import argparse
    import json

    from docling_core.types.doc import DoclingDocument

    from kg.registry import ROOT, read_registry

    from . import TABLES_DIR
    from .check import PageChecker
    from .stitch import part_from
    p = argparse.ArgumentParser(prog="python -m kg.tables.rebuild", description="Before/after diff of the rebuild")
    p.add_argument("source_id")
    a = p.parse_args(argv)
    entry = next(e for e in read_registry() if e.id == a.source_id)
    sid = entry.id.split(":", 1)[1]
    doc = DoclingDocument.load_from_json(ROOT / "data" / "docling" / sid / "document.json")
    items = {t.self_ref: t for t in doc.tables}
    tables = [json.loads(line) for line in open(TABLES_DIR / sid / "tables.jsonl", encoding="utf-8")]
    refs = list(dict.fromkeys(ref for t in tables for ref in t["table_refs"]))
    print("\n".join(diff_lines([part_from(items[r]) for r in refs], PageChecker(ROOT / entry.file))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
