"""Prompt v5 (schema v1.5 QualitySpec) in the raw model and the version rules: the new QualitySpec fields stay
out of v1-v4, and v5 drops authority and valid_for_season (code takes them from the registry)."""

from kg.extract.model import FACT
from kg.extract.versions import V5_FIELDS, field_names, source_version, version_problems
from kg.registry import read_entry

LIMIT = {"subtype": "QualitySpec", "summary_en": "s", "quote": "5. | Moisture content | 17.0",
         "commodity_form": "paddy", "parameter": "moisture", "parameter_raw": "Moisture content", "limit_type": "max",
         "limit_value": 17.0, "unit": "%", "raw": {"limit_value": "17.0"}}


def test_a_v5_limit_parses_and_keeps_the_printed_name():
    q = FACT.validate_python(LIMIT)
    assert (q.parameter, q.parameter_raw, q.limit_type, q.limit_inclusive, q.grades) == (
        "moisture", "Moisture content", "max", True, [])
    assert version_problems(LIMIT, "v5") == []


def test_versions_keep_their_quality_fields_apart():
    assert V5_FIELDS <= field_names("v5") and not V5_FIELDS & field_names("v4")
    assert any("commodity_form: not part of prompt v4" in p for p in version_problems(LIMIT, "v4"))
    old = {**LIMIT, "authority": "FCI", "valid_for_season": "KMS 2026-27"}
    problems = version_problems(old, "v5")
    assert any("authority: not part of prompt v5" in p for p in problems)
    assert any("valid_for_season: not part of prompt v5" in p for p in problems)


def test_dfpd_pins_v5_so_its_runs_are_read():
    from kg.extract.versions import LATEST
    assert source_version(read_entry("source:dfpd_uniform_spec_kms_2026_27")) == "v5" != LATEST   # pinned 2026-10-24
