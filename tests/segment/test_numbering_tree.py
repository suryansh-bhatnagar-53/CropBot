"""Offline tests for heading numbers and the tree rules."""

from collections import defaultdict

import pytest

from kg.registry.model import HeadingFix
from kg.segment.numbering import is_caps, parse, promotable
from kg.segment.tree import Builder, Node


@pytest.mark.parametrize("text, scheme, parts, title", [
    ("1.8.3.1.Seed rate", "arabic", (1, 8, 3, 1), "Seed rate"),
    ("1.1 Nursery management", "arabic", (1, 1), "Nursery management"),
    ("1.1.1. Wet nursery Nursery area", "arabic", (1, 1, 1), "Wet nursery Nursery area"),
    ("10. HARVESTING", "arabic", (10,), "HARVESTING"),
    ("II.DESCRIPTION OF REDGRAM VARIETIES", "roman", (2,), "DESCRIPTION OF REDGRAM VARIETIES"),
    ("A) Pest management Nursery", "letter", (1,), "Pest management Nursery"),
    ("B. Disease Management", "letter", (2,), "Disease Management"),
    ("ii) Main field", "roman_lower", (2,), "Main field"),
    ("(iii) COWPEA ( Vigna unguiculata)", "roman_lower", (3,), "COWPEA ( Vigna unguiculata)"),
])
def test_parse_numbered(text, scheme, parts, title):
    number, rest = parse(text)
    assert (number.scheme, number.parts, rest) == (scheme, parts, title)


@pytest.mark.parametrize("text", ["12 Points for SRI", "Harvesting", "Nutrient management", "CROP PROTECTION"])
def test_parse_unnumbered(text):
    assert parse(text)[0] is None


def test_promotable_and_caps():
    assert promotable("4.11.Disease management: See Crop Protection Chapter")
    assert not promotable("2.5 m wide beds") and not promotable("30 kg for long duration")
    assert is_caps("RICE - VARIETAL SEED PRODUCTION") and not is_caps("Water Management")


def run(events, fixes=()):
    """events: ("h", text) for a heading, ("t", text) for body text. Returns (chapter, log)."""
    log = defaultdict(list)
    chapter = Node("chapter", "RICE", pdf_page=1)
    b = Builder(chapter, list(fixes), log)
    for i, (kind, text) in enumerate(events):
        if kind == "h":
            b.heading(text, "#/texts/%d" % i, 1)
        else:
            b.body({"ref": "#/texts/%d" % i, "label": "text", "kind": "text", "text": text,
                    "pdf_page": 1, "chars": len(text)})
    return chapter, log


def find(root, heading):
    return next(n for n in root.walk() if n.heading == heading)


def path(node):
    out = []
    while node.parent is not None:
        out.append(node.heading)
        node = node.parent
    return out[::-1]


def test_numbers_nest_by_number_not_order():
    root, _ = run([("h", "1. A"), ("h", "1.1 B"), ("h", "1.1.1. C"), ("h", "1.2. D"), ("t", "x")])
    assert path(find(root, "1.1.1. C")) == ["1. A", "1.1 B", "1.1.1. C"]
    assert path(find(root, "1.2. D")) == ["1. A", "1.2. D"]


def test_late_parent_fills_its_placeholder():
    root, log = run([("h", "3.1. Area"), ("t", "a"), ("h", "3.2. Season"), ("t", "b"),
                     ("h", "3. DRY SEEDED RAINFED RICE"), ("t", "c")])
    three = find(root, "3. DRY SEEDED RAINFED RICE")
    assert [c.heading for c in three.children] == ["3.1. Area", "3.2. Season"]
    assert log["placeholders"][0]["number"] == "3" and log["late_parents"][0]["number"] == "3"


def test_numbering_continues_across_a_caps_major_section():
    root, log = run([("h", "CROP MANAGEMENT SYSTEMS"), ("t", "intro"), ("h", "1. TRANSPLANTED"), ("t", "x"),
                     ("h", "2. WET SEEDED"), ("t", "y"), ("h", "RAINFED RICE"), ("t", "z"),
                     ("h", "3.1. Area"), ("t", "w")])
    cms = find(root, "CROP MANAGEMENT SYSTEMS")
    assert [c.number.label() for c in cms.children] == ["1", "2", "3"]
    assert find(root, "RAINFED RICE").children == []
    assert any(d["decision"] == "numbering continues across it" for d in log["caps_decisions"])


def test_caps_heading_right_after_a_heading_is_a_subtitle():
    root, log = run([("h", "1. TRANSPLANTED PUDDLED LOWLAND RICE"), ("h", "TRANSPLANTED RICE"), ("t", "x")])
    node = find(root, "1. TRANSPLANTED PUDDLED LOWLAND RICE")
    assert node.subtitles == ["TRANSPLANTED RICE"] and log["caps_decisions"][0]["decision"] == "subtitle"


def test_seed_production_is_not_inside_nematode_management():
    root, _ = run([("h", "CROP PROTECTION"), ("t", "x"), ("h", "A) Pest management"), ("t", "y"),
                   ("h", "C) Nematode management"), ("t", "z"),
                   ("h", "RICE - VARIETAL SEED PRODUCTION"), ("t", "s"), ("h", "Storage"), ("t", "bags")])
    seed = find(root, "RICE - VARIETAL SEED PRODUCTION")
    assert path(seed) == ["RICE - VARIETAL SEED PRODUCTION"]
    assert seed.items[-1]["subheading"] == "Storage"            # unnumbered: inline, not a section


def test_unnumbered_headings_are_inline():
    root, _ = run([("h", "1.1.1. Wet nursery"), ("t", "Select 20 cents"), ("h", "Nutrient management"),
                   ("t", "Apply 40 kg of DAP")])
    node = find(root, "1.1.1. Wet nursery")
    assert node.children == [] and [i["subheading"] for i in node.items] == [
        None, "Nutrient management", "Nutrient management"]


def test_promotion_needs_an_existing_parent():
    root, log = run([("h", "4. DRY SEEDED"), ("t", "x"), ("t", "4.11.Disease management: See Crop Protection")])
    assert find(root, "4.11.Disease management: See Crop Protection").parent.heading == "4. DRY SEEDED"
    root, log = run([("h", "4. DRY SEEDED"), ("t", "7.2.Something Else")])
    assert log["promotions"] == []


FIXES = [HeadingFix(match="1.1.1. Wet nursery Nursery area", pdf_page=1, heading="1.1.1. Wet nursery",
                    inline_subheading="Nursery area", status="approved"),
         HeadingFix(match="A) Pest management Nursery", pdf_page=1, heading="A) Pest management",
                    subsection="Nursery", status="approved")]


def test_split_fix_with_a_numbered_subsection():
    fix = HeadingFix(match="CROP IMPROVEMENT I. SEASON AND VARIETIES", pdf_page=1, heading="CROP IMPROVEMENT",
                     subsection="I. SEASON AND VARIETIES", status="approved")
    root, _ = run([("h", "CLIMATE REQUIREMENT"), ("t", "x"), ("h", "CROP IMPROVEMENT I. SEASON AND VARIETIES"),
                   ("t", "zone table")], [fix])
    season = find(root, "I. SEASON AND VARIETIES")
    assert path(season) == ["CROP IMPROVEMENT", "I. SEASON AND VARIETIES"]
    assert season.number.scheme == "roman" and season.items[0]["text"] == "zone table"


def test_approved_heading_fixes():
    root, log = run([("h", "1.1.1. Wet nursery Nursery area"), ("t", "Select 20 cents"),
                     ("h", "CROP PROTECTION"), ("t", "x"), ("h", "A) Pest management Nursery"), ("t", "seed"),
                     ("h", "ii) Main field"), ("t", "stubbles")], FIXES)
    wet = find(root, "1.1.1. Wet nursery")
    assert [(i["text"], i["subheading"]) for i in wet.items] == [
        ("Nursery area", "Nursery area"), ("Select 20 cents", "Nursery area")]
    a = find(root, "A) Pest management")
    assert [c.heading for c in a.children] == ["Nursery", "ii) Main field"]
    assert len(log["heading_fixes_applied"]) == 2
