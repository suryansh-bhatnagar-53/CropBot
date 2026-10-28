"""Step 8 rebuild of ruled table parts from the text layer (kg.tables.rebuild), approved 2026-10-21.

Synthetic tests run offline; the TNAU tests need the full conversion and the PDF and are skipped without them."""

import json
from collections import Counter
from pathlib import Path

import pytest

from kg.registry import ROOT, read_entry
from kg.tables.rebuild import CROSSES_ROW, SPAN_WIDER, chars, crossings, diff_lines, rebuild
from kg.tables.stitch import Part

FIXTURE = Path(__file__).parent / "fixtures" / "table_rebuild_diff.txt"


# --- synthetic parts (bottom-left coordinates) ------------------------------------------------------------

def seg(x0, y0, x1, y1):
    return ((x0, y0), (x1, y1))


def grid_page(words, xs=(0, 100), ys=(40, 20, 0)):
    """A ruled table: full-width rulings at ys, full-height rulings at xs."""
    segments = [seg(xs[0], y, xs[-1], y) for y in ys] + [seg(x, ys[-1], x, ys[0]) for x in xs]
    return {"height": 100, "words": words, "segments": segments}


def cell(row, col, text, l, b, r, t, row_span=1, col_span=1):
    return {"row": row, "col": col, "row_span": row_span, "col_span": col_span, "text": text, "header": False,
            "bbox": {"l": l, "t": t, "r": r, "b": b, "origin": "BOTTOMLEFT"}}


def part(cells, num_rows=2, num_cols=1, box=(0, 0, 100, 40)):
    rows = {}
    for c in sorted(cells, key=lambda c: (c["row"], c["col"])):
        rows.setdefault(c["row"], []).append(c)
    l, b, r, t = box
    return Part("#/tables/x", 1, num_rows, num_cols, cells, [rows[k] for k in sorted(rows)],
                {"l": l, "t": t, "r": r, "b": b, "origin": "BOTTOMLEFT"})


def test_a_line_docling_put_across_a_ruling_moves_back():
    """Row 0's box reaches below the ruling at y 20 and takes row 1's first line (the p. 66 pattern)."""
    words = [(20, 30, "A1"), (50, 30, "A2"), (20, 14, "B1"), (20, 6, "B2")]
    p = part([cell(0, 0, "A1 A2 B1", 5, 12, 95, 38), cell(1, 0, "B2", 5, 2, 95, 9)])
    page = grid_page(words)
    res = rebuild(p, page)
    assert res.changes == {(0, 0): ("A1 A2", None), (1, 0): ("B1 B2", None)}
    assert [c["text"] for c in res.part.cells] == ["A1 A2", "B1 B2"]
    assert res.part.cells[0]["docling_text"] == "A1 A2 B1" and res.part.docling_cells == p.cells
    assert [x["check"] for x in crossings(p, page)] == [CROSSES_ROW]           # the check sees Docling's box
    assert crossings(p, page)[0]["page"] == "above: A1 A2 | below: B1"


def test_a_move_not_at_a_cells_start_or_end_withdraws_the_whole_part():
    words = [(20, 30, "A1"), (20, 24, "A2"), (20, 14, "B1"), (20, 6, "B2")]
    p = part([cell(0, 0, "A1 B1 A2", 5, 12, 95, 38), cell(1, 0, "B2", 5, 2, 95, 9)])
    res = rebuild(p, grid_page(words))
    assert res.changes == {} and res.part is p                                  # Docling's cells kept
    assert res.flags == ["r0 c0 kept: the words to remove are not at its start or end: B1"]
    # with a valid move elsewhere in the same part, that move is withdrawn too
    words += [(150, 30, "C1"), (150, 14, "D1")]
    p2 = part([cell(0, 0, "A1 B1 A2", 5, 12, 95, 38), cell(1, 0, "B2", 5, 2, 95, 9),
               cell(0, 1, "C1 D1", 105, 12, 195, 38), cell(1, 1, "", 105, 2, 195, 9)],
              num_cols=2, box=(0, 0, 200, 40))
    res = rebuild(p2, grid_page(words, xs=(0, 100, 200)))
    assert res.changes == {} and res.part is p2
    assert res.flags[-1] == "part kept as Docling read it: 2 proposed change(s) withdrawn because a cell was kept"


def test_a_span_wider_than_its_ruled_cell_is_narrowed():
    """p. 17: a cell indexed at col 1 spanning 2 columns prints only in the ruled column 2."""
    words = [(30, 30, "Kar"), (150, 30, "TPS"), (30, 10, "Semi"), (80, 10, "(Jul)"), (150, 10, "Anna")]
    cells = [cell(0, 0, "Kar", 5, 22, 45, 38), cell(0, 1, "TPS", 105, 22, 195, 38, col_span=2),
             cell(1, 0, "Semi", 5, 2, 45, 18), cell(1, 1, "(Jul)", 55, 2, 95, 18), cell(1, 2, "Anna", 105, 2, 195, 18)]
    p = part(cells, num_cols=3, box=(0, 0, 200, 40))
    page = grid_page(words, xs=(0, 50, 100, 200))
    res = rebuild(p, page)
    assert res.changes == {(0, 1): ("TPS", (2, 1))}
    moved = next(c for c in res.part.cells if c["text"] == "TPS")
    assert (moved["col"], moved["col_span"], moved["docling_col"]) == (2, 1, (1, 2))
    assert [x["check"] for x in crossings(p, page)] == [SPAN_WIDER]


def test_a_part_without_rulings_keeps_doclings_cells():
    p = part([cell(0, 0, "A1", 5, 22, 95, 38), cell(1, 0, "B1", 5, 2, 95, 18)])
    res = rebuild(p, {"height": 100, "words": [(20, 30, "A1"), (20, 10, "B1")], "segments": []})
    assert (res.ruled, res.changes, res.part is p) == (False, {}, True)


# --- the TNAU conversion ------------------------------------------------------------------------------------

DOCLING = ROOT / "data" / "docling" / "tnau_agriculture_2020" / "document.json"
TABLES = ROOT / "data" / "tables" / "tnau_agriculture_2020" / "tables.jsonl"
needs_data = pytest.mark.skipif(not DOCLING.exists() or not TABLES.exists(), reason="needs the TNAU conversion")


@pytest.fixture(scope="module")
def tnau():
    from docling_core.types.doc import DoclingDocument

    from kg.tables.check import PageChecker
    from kg.tables.stitch import part_from
    entry = read_entry("source:tnau_agriculture_2020")
    doc = DoclingDocument.load_from_json(DOCLING)
    items = {t.self_ref: t for t in doc.tables}
    refs = list(dict.fromkeys(r for line in open(TABLES, encoding="utf-8") for r in json.loads(line)["table_refs"]))
    checker = PageChecker(ROOT / entry.file)
    parts = {r: part_from(items[r]) for r in refs}
    return parts, checker


def changed(tnau, ref):
    parts, checker = tnau
    p = parts[ref]
    res = rebuild(p, checker.page(p.pdf_page))
    before = {(c["row"], c["col"]): c["text"] for c in p.cells}
    return before, res


@needs_data
def test_p66_pymetrozine_returns_to_the_bph_cell(tnau):
    before, res = changed(tnau, "#/tables/57")
    assert set(res.changes) == {(3, 1), (4, 1)}
    assert res.changes[(3, 1)][0] == before[(3, 1)] + " Pymetrozine 50% WG 300g"
    assert before[(3, 1)].endswith("Imidacloprid 17.8 SL 100-125 ml")
    assert before[(4, 1)].startswith("Pymetrozine 50% WG 300g • Spray any one")
    assert res.changes[(4, 1)][0] == before[(4, 1)].removeprefix("Pymetrozine 50% WG 300g ")


@needs_data
def test_p17_the_continuation_line_is_whole_and_in_its_column(tnau):
    before, res = changed(tnau, "#/tables/8")
    assert before[(0, 1)] == "Ponni, ADT (R) 46, TRY 1, TNAU Rice"
    assert before[(1, 2)] == "Hybrid CO 4 Anna (R) 4, PMK (R) 3"
    assert res.changes == {(0, 1): ("Ponni, ADT (R) 46, TRY 1, TNAU Rice Hybrid CO 4", (2, 1)),
                           (1, 2): ("Anna (R) 4, PMK (R) 3", None)}


@needs_data
def test_p34_the_location_names_are_whole_again(tnau):
    before, res = changed(tnau, "#/tables/32")
    assert {k: before[k] for k in res.changes} == {
        (3, 1): "(i) Old", (3, 2): "delta 35", (4, 1): "(ii)", (4, 2): "New delta 35",
        (6, 1): "(i)", (6, 2): "General 30", (7, 1): "(ii)", (7, 2): "Annamalai block 30"}
    assert {k: t for k, (t, _) in res.changes.items()} == {
        (3, 1): "(i) Old delta", (3, 2): "35", (4, 1): "(ii) New delta", (4, 2): "35",
        (6, 1): "(i) General", (6, 2): "30", (7, 1): "(ii) Annamalai block", (7, 2): "30"}


@needs_data
def test_p69_the_third_note_returns_to_the_notes_row(tnau):
    before, res = changed(tnau, "#/tables/60")
    note = "\x99 Fungicides and biocontrol agents are incompatible"
    assert before[(2, 0)] == "Seedling dip with Pseudomonas fluorescens \x99 Fungicides and"
    assert before[(2, 1)].endswith("and then transplanted biocontrol agents are incompatible")
    assert {k: t for k, (t, _) in res.changes.items()} == {
        (2, 0): "Seedling dip with Pseudomonas fluorescens",
        (2, 1): before[(2, 1)].removesuffix(" biocontrol agents are incompatible"),
        (3, 0): before[(3, 0)] + " " + note}


@needs_data
@pytest.mark.parametrize("ref,line", [
    ("#/tables/61", "• Foliar spray with P. fluorescens TNAU liquid formulation @ 5 ml/l"),      # p. 70
    ("#/tables/62", "• Foliar spray with P. fluorescens TNAU liquid formulation @ 5ml/l")])      # p. 71
def test_p70_p71_the_blast_rows_last_bullet_returns(tnau, ref, line):
    before, res = changed(tnau, ref)
    assert before[(2, 1)].startswith(line + " ")
    assert {k: t for k, (t, _) in res.changes.items()} == {
        (1, 1): before[(1, 1)] + " " + line, (2, 1): before[(2, 1)].removeprefix(line + " ")}


@needs_data
def test_p16_a_row_docling_lacks_keeps_doclings_cells_and_is_flagged(tnau):
    before, res = changed(tnau, "#/tables/7")
    assert res.changes == {} and before[(1, 0)] == "a. The Nilgiris Samba"
    assert res.flags == ["ruled cells with no Docling row or column; their words follow Docling's boxes into [(1, 0)]"]


@needs_data
def test_every_rebuilt_part_conserves_its_characters_exactly(tnau):
    parts, checker = tnau
    for p in parts.values():
        res = rebuild(p, checker.page(p.pdf_page))
        assert sum((chars(c["text"]) for c in res.part.cells), Counter()) == \
            sum((chars(c["text"]) for c in p.cells), Counter()), p.ref


@needs_data
def test_the_rice_and_wheat_diff_is_the_approved_one(tnau):
    parts, checker = tnau
    assert diff_lines(list(parts.values()), checker) == FIXTURE.read_text(encoding="utf-8").splitlines()


@needs_data
def test_the_crossing_checks_on_doclings_cells(tnau):
    parts, checker = tnau
    found = Counter()
    for p in parts.values():
        for x in crossings(p, checker.page(p.pdf_page)):
            found[(x["check"], p.ref, x["row"], x["col"])] += 1
    rows = sorted((ref, r, c) for (check, ref, r, c) in found if check == CROSSES_ROW)
    assert rows == [("#/tables/57", 4, 1), ("#/tables/60", 2, 0), ("#/tables/60", 2, 1), ("#/tables/61", 2, 1),
                    ("#/tables/7", 1, 0), ("#/tables/8", 1, 2)]
    columns = sorted((ref, r, c) for (check, ref, r, c) in found if check == "crosses a column ruling")
    assert columns == [("#/tables/32", 3, 2), ("#/tables/32", 4, 2), ("#/tables/32", 6, 2), ("#/tables/32", 7, 2)]
    assert [(ref, r, c) for (check, ref, r, c) in found if check == SPAN_WIDER] == [("#/tables/8", 0, 1)]
