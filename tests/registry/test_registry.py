"""Registry validation runs offline: it needs the committed PDF and concepts/, not Neo4j."""

import json
import re
import shutil
from pathlib import Path

import pytest

from kg.registry import REGISTRY_DIR, RegistryError, heading_matches, read_entry, read_registry

ROOT = Path(__file__).resolve().parents[2]
TNAU = "tnau_agriculture_2020.toml"
TNAU_ID = "source:tnau_agriculture_2020"
INDEX = ROOT / "converted" / "tnau_agriculture.index.json"


@pytest.fixture
def reg(tmp_path):
    """A copy of registry/ that a test can break."""
    shutil.copytree(REGISTRY_DIR, tmp_path / "registry")
    return tmp_path / "registry"


def edit(directory, old, new, name=TNAU):
    path = directory / name
    text = path.read_text(encoding="utf-8")
    assert re.search(old, text, re.M), old
    path.write_text(re.sub(old, new, text, count=1, flags=re.M), encoding="utf-8")


def problems(directory):
    with pytest.raises(RegistryError) as e:
        read_registry(directory)
    return "\n".join(e.value.problems)


def test_committed_registry_validates():
    assert sorted(e.id for e in read_registry()) == ["source:dfpd_uniform_spec_kms_2026_27",
                                                     "source:gbpuat_kharif_advisory_2020", TNAU_ID]
    entry = read_entry(TNAU_ID)
    assert (entry.state_id, entry.region_scope, entry.authority_tier) == ("state:33", ["state:33"], 1)
    assert (entry.edition_year, entry.edition_label) == (2020, "2020")


DFPD = "dfpd_uniform_spec_kms_2026_27.toml"
DFPD_ID = "source:dfpd_uniform_spec_kms_2026_27"


def test_the_dfpd_specification_is_national_and_its_schedules_print_no_page_numbers():
    entry = read_entry(DFPD_ID)
    assert (entry.state_id, entry.region_scope, entry.authority_tier) == (None, ["country:in"], 0)   # regulatory
    assert (entry.edition_year, entry.edition_label, entry.extraction.ocr) == (2026, "2026-27", "force")
    assert (entry.season_label, entry.marketing_season) == ("KHARIF MARKETING SEASON 2026-2027", "KMS")
    assert any("No. 14453 dated 21/08/2026" in n and "17.08.2026" in n for n in entry.notes)   # a state forward
    paddy = next(c for c in entry.chapters if c.number == "1")
    assert (paddy.pdf_page, paddy.printed_page, paddy.status, paddy.crop_id) == (6, None, "approved", "crop:rice")
    assert all(c.status == "proposed" for c in entry.chapters if c.number != "1")
    assert entry.printed_page(5) == "2" and entry.printed_page(6) is None
    [scope] = entry.section_scope
    assert (scope.heading, scope.pdf_pages, scope.grades, scope.regions, scope.purposes, scope.status) == (
        "UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY", (6, 6), ["grade_a", "common"], [], [], "approved")


def test_a_season_label_must_name_the_edition_year(reg):
    edit(reg, r'^season_label = "KHARIF MARKETING SEASON 2026-2027"', 'season_label = "KHARIF MARKETING SEASON 2027-2028"',
         name=DFPD)
    assert "does not name edition_year 2026" in problems(reg)


def test_a_printed_page_on_an_unnumbered_page_fails(reg):
    edit(reg, r'pdf_page = 6, status', 'printed_page = 3, pdf_page = 6, status', name=DFPD)
    assert "PDF p. 6 is printed p. None, not 3" in problems(reg)


def test_sha256_mismatch_fails(reg):
    edit(reg, r'^sha256 = "a', 'sha256 = "b')
    assert "sha256 mismatch for data/raw/AGRICULTURE.pdf" in problems(reg)


def test_missing_file_fails(reg):
    edit(reg, r'^file = ".*"', 'file = "data/raw/not_there.pdf"')
    assert "file data/raw/not_there.pdf is missing; download it from https://" in problems(reg)


def test_missing_required_field_fails(reg):
    edit(reg, r"^authority_tier = 1\n", "")
    assert "authority_tier: Field required" in problems(reg)


def test_unknown_region_fails(reg):
    edit(reg, r'regions = \["zone:tn_western"\]', 'regions = ["zone:tn_nowhere"]')
    assert "zone:tn_nowhere is not a loaded region" in problems(reg)


def test_region_outside_the_state_fails(reg):
    edit(reg, r'^region_scope = \["state:33"\]', 'region_scope = ["state:33", "country:in"]')
    assert "country:in is outside the book's state state:33" in problems(reg)


def test_malformed_region_id_fails(reg):
    edit(reg, r'^region_scope = \["state:33"\]', 'region_scope = ["state:tn"]')
    assert "is not a region id" in problems(reg)


def test_unregistered_supersedes_fails(reg):
    edit(reg, r"^doc_type = ", 'supersedes = "source:tnau_agriculture_2016"\ndoc_type = ')
    assert "supersedes source:tnau_agriculture_2016, which is not registered" in problems(reg)


def test_file_name_must_match_id(reg):
    (reg / TNAU).rename(reg / "tnau.toml")
    assert "file name must match the id (tnau_agriculture_2020.toml)" in problems(reg)


def test_edition_year_must_match_label(reg):
    edit(reg, r'^edition_label = "2020"', 'edition_label = "2021-22"')
    assert "start year" in problems(reg)


def test_page_range_must_be_ordered(reg):
    edit(reg, r"pdf_pages = \[63, 69\]", "pdf_pages = [69, 63]")
    assert "is after end" in problems(reg)


def test_only_approved_default_scope_rules_reach_the_source(reg):
    edit(reg, r'^status = "approved"\nsection = \{ heading = "Nursery"',
         'status = "proposed"\nsection = { heading = "Nursery"')
    entry = read_entry(TNAU_ID, reg)
    assert entry.to_source().default_scope == [
        "dose basis = per_ha unless stated [ii) Main field, PDF pp. 63-69]"]


def test_section_scopes_and_their_review_status():
    entry = read_entry(TNAU_ID)
    [seed] = entry.approved_section_scopes()
    assert len(entry.section_scope) == 12 and all(s.status == "proposed" for s in entry.section_scope if s is not seed)
    assert (seed.heading, seed.pdf_pages, seed.purposes, seed.regions) == (
        "RICE - VARIETAL SEED PRODUCTION", (73, 75), ["purpose:seed"], [])


def test_section_scope_needs_regions_or_purposes(reg):
    edit(reg, r'^purposes = \["purpose:seed"\]$', "")
    assert "needs regions, purposes or grades" in problems(reg)


def test_section_scope_purpose_must_be_a_purpose_id(reg):
    edit(reg, r'^purposes = \["purpose:seed"\]$', 'purposes = ["seed"]')
    assert "is not a purpose id" in problems(reg)


@pytest.mark.skipif(not INDEX.exists(), reason="committed TNAU conversion not present")
def test_every_section_matches_exactly_one_heading():
    entry = read_entry(TNAU_ID)
    items = json.loads(INDEX.read_text(encoding="utf-8"))["items"]
    sections = [r.section for r in entry.default_scope if r.section] + entry.section_scope
    # a section named by a heading_fix exists only after the fix; check the fix's source heading
    fixed = {f.subsection or f.heading: f.match for f in entry.heading_fix}
    counts = {s.heading: heading_matches(s.model_copy(update={"heading": fixed.get(s.heading, s.heading)}),
                                         items) for s in sections}
    assert all(n == 1 for n in counts.values()), counts


# --- printed pages -------------------------------------------------------------------------

@pytest.mark.parametrize("pdf_page, printed", [
    (12, None), (13, "1"), (64, "52"), (146, "134"), (147, "136"), (380, "369"),
    (381, "385"), (459, "463"), (460, None)])
def test_printed_page_mapping(pdf_page, printed):
    entry = read_entry(TNAU_ID)
    assert entry.printed_page(pdf_page) == printed


def test_overlapping_printed_page_runs_fail(reg):
    edit(reg, r"pdf_pages = \[147, 380\]", "pdf_pages = [140, 380]")
    assert "printed_pages runs overlap at PDF page 140" in problems(reg)


def test_gaps_are_recorded_as_notes():
    entry = read_entry(TNAU_ID)
    assert any("135" in n for n in entry.notes) and any("370-384" in n for n in entry.notes)


# --- chapters and heading fixes ------------------------------------------------------------

def test_chapters_follow_the_printed_page_mapping():
    entry = read_entry(TNAU_ID)
    rice, wheat = (next(c for c in entry.chapters if c.title == t) for t in ("RICE", "WHEAT"))
    assert (rice.pdf_page, rice.printed_page, wheat.pdf_page, wheat.printed_page) == (13, 1, 134, 122)
    assert (rice.status, rice.crop_id, wheat.status, wheat.crop_id) == (
        "approved", "crop:rice", "approved", "crop:wheat")
    others = [c for c in entry.chapters if c.title not in ("RICE", "WHEAT")]
    assert len(entry.chapters) == 63 and all(c.status == "proposed" for c in others)


def test_chapter_page_that_disagrees_with_the_mapping_fails(reg):
    edit(reg, r'title = "WHEAT", printed_page = 122, pdf_page = 134',
         'title = "WHEAT", printed_page = 122, pdf_page = 133')
    assert "PDF p. 133 is printed p. 121, not 122" in problems(reg)


def test_heading_fix_must_split_its_match_exactly(reg):
    edit(reg, r'^heading = "1.1.1. Wet nursery"$', 'heading = "1.1.1. Wet"')
    assert "must equal heading" in problems(reg)


def test_heading_fixes_and_their_review_status():
    entry = read_entry(TNAU_ID)
    assert [(f.pdf_page, f.kind, f.heading, f.status) for f in entry.heading_fix] == [
        (29, "split", "1.1.1. Wet nursery", "approved"),
        (62, "split", "A) Pest management", "approved"),
        (13, "split", "CROP IMPROVEMENT", "approved"),
        (39, "restore", "1.3. Insect management: See Crop Protection Chapter", "approved"),
        (39, "restore", "1.4. Disease management: See Crop Protection Chapter", "approved"),
        (39, "restore", "1.5. Harvesting", "approved"),
        (46, "restore", "3.9. Insect management: See Crop Protection Chapter", "approved"),
        (46, "restore", "3.10. Disease management: See Crop Protection Chapter", "approved"),
        (49, "restore", "4.10. Insect management: See Crop Protection Chapter", "approved"),
        (51, "restore", "5.12. Disease management: See Crop Protection Chapter", "approved")]
    assert [(o.pdf_page, o.first, o.after[:30], o.status) for o in entry.reading_order_fix] == [
        (134, "Suitable Districts", "I. SEASON AND VARIETY", "approved"),
        (134, "CROP IMPROVEMENT", "Tropical and Sub tropical cool", "approved"),
        (74, ": NPK @ 150:50:60 kg / ha", "Medium duration", "approved")]
    [gap] = entry.acknowledged_gap
    assert (gap.chapter, gap.under, gap.missing, gap.pdf_page) == ("WHEAT", "I. SEASON AND VARIETY", ["1"], 134)


def test_acknowledged_gap_needs_missing_numbers(reg):
    edit(reg, r'^missing = \["1"\]$', "missing = []")
    assert "missing" in problems(reg)


def test_restore_fix_heading_must_be_a_number_plus_the_match(reg):
    edit(reg, r'^heading = "1.5. Harvesting"$', 'heading = "1.5. Harvest"')
    assert "must be a number followed by the match" in problems(reg)


def test_restore_fix_takes_no_subheading(reg):
    edit(reg, r'^heading = "1.5. Harvesting"$', 'heading = "1.5. Harvesting"\ninline_subheading = "x"')
    assert "a restore fix has no inline_subheading" in problems(reg)
