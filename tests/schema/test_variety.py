"""Variety records: a reviewer may approve them; the pivot only ever produces needs_review."""

import pytest
from pydantic import ValidationError

from kg.schema.concepts import Variety

CO51 = {
    "id": "variety:co_51", "name": "CO 51", "name_en": "CO 51", "review_status": "needs_review",
    "release_year": 2013, "avg_yield_kg_ha": 6641,
    "raw": {"release_year": "2013", "avg_yield_kg_ha": "6641"},
    "evidence": [{"id": "span:tnau_co_51", "source_id": "source:tnau_agriculture_2020", "pdf_page": 17,
                  "printed_page": "5", "section_path": "RICE > II. PARTICULARS OF RICE VARIETIES",
                  "quote": "CO 51", "table_ref": "#/tables/9", "table_row": 0, "table_col": 1,
                  "extraction_method": "table_parse"}],
}


@pytest.mark.parametrize("status", ["needs_review", "approved"])
def test_variety_accepts_review_statuses(status):
    assert Variety.model_validate({**CO51, "review_status": status}).review_status == status


def test_unknown_review_status_is_rejected():
    with pytest.raises(ValidationError, match="review_status"):
        Variety.model_validate({**CO51, "review_status": "draft"})


def test_number_without_raw_is_still_rejected():
    with pytest.raises(ValidationError, match="raw source text"):
        Variety.model_validate({**CO51, "raw": {"release_year": "2013"}})


def test_pivot_produces_only_needs_review(monkeypatch):
    """The pivot sets needs_review itself, whatever the model allows."""
    from kg.tables import varieties
    seen = []
    original = Variety.model_validate

    def spy(data, *a, **k):
        seen.append(data["review_status"])
        return original(data, *a, **k)

    monkeypatch.setattr(varieties.Variety, "model_validate", spy)
    from kg.tables.stitch import Part, Table
    cells = [{"row": 0, "col": 0, "row_span": 1, "col_span": 1, "text": "PARTICULARS", "header": True, "bbox": None},
             {"row": 0, "col": 1, "row_span": 1, "col_span": 1, "text": "CO 51", "header": True, "bbox": None},
             {"row": 1, "col": 0, "row_span": 1, "col_span": 1, "text": "Grain type", "header": False, "bbox": None},
             {"row": 1, "col": 1, "row_span": 1, "col_span": 1, "text": "Medium Slender", "header": False, "bbox": None}]
    tag = {"part_ref": "#/tables/9", "pdf_page": 17, "part_cols": 2}
    part = Part("#/tables/9", 17, 2, 2, cells, [cells[:2], cells[2:]])
    table = Table("unit:x", "RICE > X", "RICE", [part], header=["PARTICULARS", "CO 51"],
                  header_cells=[{**c, **tag} for c in cells[:2]], rows=[[{**c, **tag} for c in cells[2:]]])

    class Entry:
        id = "source:tnau_agriculture_2020"

        @staticmethod
        def printed_page(p):
            return str(p - 12)

    class Chapter:
        status, crop_id = "approved", "crop:rice"

    records, _ = varieties.pivot(table, Entry, Chapter, "short")
    assert seen == ["needs_review"] and records[0].review_status == "needs_review"
    assert records[0].grain_type == "Medium Slender" and records[0].crop_id == "crop:rice"
