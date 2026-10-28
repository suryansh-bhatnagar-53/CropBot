"""Offline tests for kg.convert. The real conversion test is marked slow and skipped by default."""

import json

import pytest

from kg.convert import cache_key, convert, ocr_pages, output_dir, page_marker
from kg.convert.converter import settings, versions
from kg.convert.headers import running_headings
from kg.registry import read_entry


@pytest.fixture(scope="module")
def tnau():
    return read_entry("source:tnau_agriculture_2020")


def test_settings_come_from_the_registry(tnau):
    cfg = settings(tnau)
    assert (cfg["ocr_engine"], cfg["ocr"], cfg["ocr_lang"], cfg["page_range"]) == \
        ("easyocr", "auto", ["en"], None)
    assert settings(tnau, (13, 76))["page_range"] == [13, 76]


def test_pinned_docling_version():
    assert versions()["docling"] == "2.140.0"


def test_cache_key_changes_with_sha_versions_and_settings(tnau):
    base = cache_key(tnau.sha256, versions(), settings(tnau))
    assert base == cache_key(tnau.sha256, versions(), settings(tnau))
    assert base != cache_key("0" * 64, versions(), settings(tnau))
    assert base != cache_key(tnau.sha256, {**versions(), "docling": "2.115.0"}, settings(tnau))
    assert base != cache_key(tnau.sha256, versions(), settings(tnau, (13, 76)))
    assert base != cache_key(tnau.sha256, versions(), {**settings(tnau), "ocr": "force"})


def test_trial_runs_get_their_own_folder(tnau):
    full, trial = output_dir(tnau), output_dir(tnau, (13, 76))
    assert full.name == "tnau_agriculture_2020" and trial.name == "trial_p13-76"
    assert trial.parent == full


def test_page_marker_uses_printed_pages(tnau):
    assert page_marker(64, tnau.printed_page(64)) == "<!-- PDF p. 64 | printed p. 52 -->"
    assert page_marker(5, tnau.printed_page(5)) == "<!-- PDF p. 5 | printed p. none -->"


def test_running_headings_drop_frequent_short_headings_only():
    items = [("text", "x", p) for p in range(1, 41)]                     # a 40-page document
    items += [("section_header", "CROP PRODUCTION GUIDE", p) for p in range(1, 41)]
    items += [("section_header", "CROP PROTECTION", p) for p in (5, 18, 30)]
    items += [("section_header", "A heading that is far too long to be a running page header",
               p) for p in range(1, 41)]
    assert running_headings(items) == {"crop production guide"}


def test_ocr_pages_use_1_based_page_numbers():
    from types import SimpleNamespace as NS
    cell = lambda ocr: NS(from_ocr=ocr)
    page = lambda n, cells: NS(page_no=n, parsed_page=NS(textline_cells=cells))
    pages = [page(1, [cell(False)] * 3), page(2, []), page(7, [cell(True)] * 13),
             page(8, [cell(False), cell(True)])]
    assert ocr_pages(pages) == {"pages_with_ocr_text": [7, 8], "pages_without_text_layer": [7],
                                "pages_without_any_text": [2]}


@pytest.mark.slow
def test_two_page_conversion_and_cache(tnau, tmp_path, monkeypatch):
    """Converts PDF pp. 29-30 for real (downloads models on first use), then hits the cache."""
    import kg.convert as kc
    monkeypatch.setattr(kc, "OUT", tmp_path)
    out, meta, cached = convert(tnau, (29, 30))
    assert not cached and meta["pages"] == 2
    assert json.loads((out / "document.json").read_text(encoding="utf-8"))["pages"]
    assert "<!-- PDF p. 29 | printed p. 17 -->" in (out / "document.md").read_text(encoding="utf-8")
    assert convert(tnau, (29, 30))[2] is True
