"""Offline tests for rows split across a page break (kg.tables.stitch)."""

from kg.tables.stitch import Part, stitch_unit


def cell(row, col, text, header=False):
    return {"row": row, "col": col, "row_span": 1, "col_span": 1, "text": text, "header": header, "bbox": None}


def part(ref, page, rows):
    cells = [c for r in rows for c in r]
    return Part(ref, page, len(rows), 2, cells, rows)


def run(monkeypatch, parts):
    """stitch_unit on ready-made parts (part_from is patched to pass them through)."""
    import kg.tables.stitch as st
    by_ref = {p.ref: p for p in parts}
    monkeypatch.setattr(st, "part_from", lambda item: item)
    unit = {"id": "unit:x:1", "section_path": "RICE > CROP PROTECTION", "chapter": {"title": "RICE"},
            "items": [{"ref": p.ref, "kind": "table"} for p in parts]}
    return stitch_unit(unit, by_ref)


A = part("#/tables/56", 66, [[cell(0, 0, "Pests", True), cell(0, 1, "Management strategies", True)],
                              [cell(1, 0, "Hispa"), cell(1, 1, "Spray Malathion 5% DP 25 kg")]])


def test_piece_without_a_first_column_cell_is_merged_and_logged(monkeypatch):
    b = part("#/tables/57", 67, [[cell(0, 1, "Malathion 50%EC 1150 ml")], [cell(1, 0, "Grasshopper"), cell(1, 1, "Dust")]])
    [t] = run(monkeypatch, [A, b])
    hispa = t.rows[0]
    assert hispa[1]["text"] == "Spray Malathion 5% DP 25 kg Malathion 50%EC 1150 ml"
    assert hispa[1]["continued_from"] == [{"part_ref": "#/tables/57", "row": 0, "col": 1,
                                           "text": "Malathion 50%EC 1150 ml"}]
    assert [r[0]["text"] for r in t.rows] == ["Hispa", "Grasshopper"]
    assert t.merged_rows == [{"into": "#/tables/56 row 1", "part_ref": "#/tables/57", "row": 0, "pdf_page": 67,
                              "text": "Malathion 50%EC 1150 ml"}]
    assert any("merged into #/tables/56 row 1" in line for line in t.stitch_log)
    assert b.cells[0]["text"] == "Malathion 50%EC 1150 ml"          # the part's own cells are untouched


def test_empty_first_cell_counts_as_missing(monkeypatch):
    b = part("#/tables/57", 67, [[cell(0, 0, ""), cell(0, 1, "drooping")]])
    [t] = run(monkeypatch, [A, b])
    assert t.rows[0][1]["text"].endswith("25 kg drooping") and len(t.rows) == 1


def test_a_row_with_its_first_cell_is_never_merged(monkeypatch):
    b = part("#/tables/57", 67, [[cell(0, 0, "Grasshopper"), cell(0, 1, "Dust")]])
    [t] = run(monkeypatch, [A, b])
    assert len(t.rows) == 2 and t.merged_rows == []
