"""Offline tests for approved fixes applied to the item stream (kg.segment.fixes)."""

from collections import defaultdict
from types import SimpleNamespace

import pytest

from kg.registry.model import HeadingFix, ReadingOrderFix
from kg.segment.fixes import FixError, apply_fixes


def item(text, kind="text", page=39, label="list_item"):
    return {"ref": "#/texts/%s" % text[:8], "label": label, "kind": kind, "text": text,
            "pdf_page": page, "chars": len(text)}


def entry(heading_fix=(), reading_order_fix=()):
    return SimpleNamespace(heading_fix=list(heading_fix), reading_order_fix=list(reading_order_fix))


def restore(match, heading, page=39, status="approved"):
    return HeadingFix(kind="restore", match=match, pdf_page=page, heading=heading, status=status)


def test_restore_turns_a_list_item_into_the_printed_heading():
    items = [item("Disease management: See Crop Protection Chapter"), item("Harvesting"),
             item("Dry the grains to 12% moisture level for storage.")]
    log = defaultdict(list)
    out = apply_fixes(items, entry([restore("Harvesting", "1.5. Harvesting")]), log)
    assert (out[1]["kind"], out[1]["text"], out[1]["restored_from"]) == ("heading", "1.5. Harvesting", "list_item")
    assert out[2]["kind"] == "text" and log["heading_fixes_applied"][0]["heading"] == "1.5. Harvesting"


def test_proposed_fixes_are_ignored():
    items = [item("Harvesting")]
    out = apply_fixes(items, entry([restore("Harvesting", "1.5. Harvesting", status="proposed")]),
                      defaultdict(list))
    assert out[0]["kind"] == "text"


@pytest.mark.parametrize("items, found", [
    ([item("Harvest")], 0),                                   # text not on the page
    ([item("Harvesting", page=40)], 0),                       # right text, wrong page
    ([item("Harvesting"), item("Harvesting")], 2),            # ambiguous
])
def test_restore_fails_loudly_unless_found_exactly_once(items, found):
    with pytest.raises(FixError, match="found %d times on PDF p. 39" % found):
        apply_fixes(items, entry([restore("Harvesting", "1.5. Harvesting")]), defaultdict(list))


def test_split_fix_is_checked_against_headings_only():
    fix = HeadingFix(match="A) Pest management Nursery", pdf_page=62, heading="A) Pest management",
                     subsection="Nursery", status="approved")
    with pytest.raises(FixError, match="found 0 times"):         # same text as body text does not count
        apply_fixes([item("A) Pest management Nursery", page=62)], entry([fix]), defaultdict(list))
    apply_fixes([item("A) Pest management Nursery", kind="heading", page=62)], entry([fix]),
                defaultdict(list))


WHEAT_P134 = [item(t, kind=k, page=134) for k, t in (
    ("heading", "Suitable Districts"), ("text", "Plains & adjoining areas"), ("text", "Variety : COW(W)1"),
    ("text", "3. SEED RATE: 100 kg/ha"), ("heading", "3. WHEAT (Triticum aestivum.)"),
    ("heading", "CROP IMPROVEMENT"), ("heading", "I. SEASON AND VARIETY"))]
MOVE = ReadingOrderFix(pdf_page=134, first="Suitable Districts", last="3. SEED RATE: 100 kg/ha",
                       after="I. SEASON AND VARIETY", status="approved")


def test_reading_order_fix_moves_the_block_after_its_anchor():
    log = defaultdict(list)
    out = apply_fixes(WHEAT_P134, entry(reading_order_fix=[MOVE]), log)
    assert [i["text"] for i in out] == [
        "3. WHEAT (Triticum aestivum.)", "CROP IMPROVEMENT", "I. SEASON AND VARIETY", "Suitable Districts",
        "Plains & adjoining areas", "Variety : COW(W)1", "3. SEED RATE: 100 kg/ha"]
    assert log["reading_order_fixes_applied"][0]["moved"] == 4


def test_reading_order_fix_fails_loudly_on_a_missing_anchor():
    bad = MOVE.model_copy(update={"after": "II. CROP MANAGEMENT"})
    with pytest.raises(FixError, match="after: 'II. CROP MANAGEMENT' found 0 times"):
        apply_fixes(WHEAT_P134, entry(reading_order_fix=[bad]), defaultdict(list))


def test_reading_order_fix_rejects_an_anchor_inside_its_block():
    bad = MOVE.model_copy(update={"after": "Variety : COW(W)1"})
    with pytest.raises(FixError, match="inside the block"):
        apply_fixes(WHEAT_P134, entry(reading_order_fix=[bad]), defaultdict(list))
