"""Prompt v6 (schema v1.6): sowing windows in calendar words with window_for; earlier prompts keep their numbers."""

import pytest
from pydantic import ValidationError

from kg.extract.model import FACT
from kg.extract.versions import V6_DROPPED, V6_FIELDS, field_names, source_version, version_problems
from kg.registry import read_entry

WINDOW = {"subtype": "SowingWindow", "summary_en": "s", "quote": "Nursery sowing- 2 nd fortnight May to 1 st week of June",
          "window_for": "nursery_sowing", "start_raw": "2 nd fortnight May", "end_raw": "1 st week of June"}


def test_a_v6_window_keeps_the_calendar_words_and_no_numbers():
    w = FACT.validate_python(WINDOW)
    assert (w.window_for, w.start_raw, w.end_raw, w.start_month) == (
        "nursery_sowing", "2 nd fortnight May", "1 st week of June", None)
    assert version_problems(WINDOW, "v6") == []
    with pytest.raises(ValidationError, match="has no numbers"):
        FACT.validate_python({**WINDOW, "start_month": 5, "raw": {"start_month": "May"}})
    single = {**WINDOW, "end_raw": None}                       # "1 st Fortnight May": start_raw alone
    assert FACT.validate_python(single).end_raw is None


def test_v6_needs_window_for_and_start_raw():
    assert any("window_for: a SowingWindow needs it" in p for p in version_problems({**WINDOW, "window_for": None}, "v6"))
    with pytest.raises(ValidationError, match="start_month and end_month, or start_raw"):
        FACT.validate_python({**WINDOW, "start_raw": None, "end_raw": None})


def test_v6_fields_belong_to_v6_only_and_v6_drops_the_numbers():
    assert V6_FIELDS <= field_names("v6") and not V6_FIELDS & field_names("v5")
    assert V6_DROPPED <= field_names("v5") and not V6_DROPPED & field_names("v6")
    assert any("window_for: not part of prompt v5" in p for p in version_problems(WINDOW, "v5"))
    old = {"subtype": "SowingWindow", "summary_en": "s", "quote": "q", "start_month": 6, "end_month": 7,
           "raw": {"start_month": "June", "end_month": "July"}}
    assert FACT.validate_python(old).start_month == 6 and version_problems(old, "v5") == []
    assert any("start_month: not part of prompt v6" in p for p in version_problems(old, "v6"))


def test_gbpuat_pins_v6():
    assert source_version(read_entry("source:gbpuat_kharif_advisory_2020")) == "v6"
