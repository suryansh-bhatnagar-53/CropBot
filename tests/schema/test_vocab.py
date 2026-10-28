"""The vocabularies match the lists written in docs/schema_v1.3.md.

If the schema doc changes a list, these tests fail until vocab.py follows.
"""

import re
from pathlib import Path

from kg.schema.vocab import (CONDITION_VARIABLES, Anchor, Basis, CautionKind, ConcUnit, ConditionOp,
                             ExtractionFlag, InputKind, OnUnknown, OperationType, RepeatUnit,
                             SamplingObject, Status, Subtype, Unit, UseClass)

DOC = (Path(__file__).resolve().parents[2] / "docs" / "schema_v1.3.md").read_text(encoding="utf-8")


def values(enum):
    return {m.value for m in enum}


def doc_list(pattern, sep=r",\s*"):
    m = re.search(pattern, DOC)
    assert m, pattern
    return {v.strip() for v in re.split(sep, m.group(1)) if v.strip()}


def test_units():
    assert values(Unit) == doc_list(r"\| Units \| `([^`]+)`")


def test_bases():
    assert values(Basis) == doc_list(r"\| Basis \| `([^`]+)`")


def test_operation_types():
    assert values(OperationType) == doc_list(r"\| `OperationType` \| id \(`([^`]+)`\)")


def test_v13_lists():
    table = r"\s*\\\|\s*"
    assert values(InputKind) == doc_list(r"\| `Input` \| id, name\\_en, kind \(`([^`]+)`\)", table)
    assert values(UseClass) == doc_list(r"use\\_class \(`([^`]+)`, optional\)", table)
    assert values(ConcUnit) == doc_list(r"`conc_unit` \(`([^`]+)`\)", table)
    assert values(SamplingObject) == doc_list(r"`sampling_object` \(`([^`]+)`\)", table)
    assert values(RepeatUnit) == doc_list(r"`repeat_interval_unit` `([^`]+)`", r"\s*\|\s*")
    m = re.search(r"extraction_flags,\s*// list: ([^\n]+)\n\s*//\s+([^\n]+)\n\s*//\s+([^\n]+)", DOC)
    assert m
    pending_v15 = {"general_practice"}          # decided 2026-10-22, in CLAUDE.md "Pending for schema v1.5"
    assert values(ExtractionFlag) == {v.strip() for v in ",".join(m.groups()).split(",") if v.strip()} | pending_v15


def test_statuses():
    assert values(Status) == doc_list(r"status,\s*// ([^\n]+)", r"\s*\|\s*")


def test_caution_kinds():
    assert values(CautionKind) == doc_list(r"kind \(`(prohibition[^`]+)`\)", r"\s*\\\|\s*")


def test_anchors():
    m = re.search(r"anchor,\s*// ([^\n]+)\n\s*// \| ([^\n]+)", DOC)
    assert m
    assert values(Anchor) == {a.strip() for a in (m.group(1) + "|" + m.group(2)).split("|")}


def test_condition_ops():
    assert values(ConditionOp) == doc_list(r"// op: ([^\n]+)", r"\s+")


def test_subtype_count():
    assert len(Subtype) == 16   # "There are 16 subtypes."


def test_registry_covers_every_condition_variable_named_in_the_doc():
    line = next(l for l in DOC.splitlines() if "Condition variables come from" in l)
    examples = re.search(r"for example (.*?)\. ", line).group(1)      # the list, not the later prose
    named = set(re.findall(r"`([a-z_A-Z0-9]+)`", examples))
    assert named and named <= set(CONDITION_VARIABLES)
    table_names = {"sowing_date", "das", "variety", "purpose", "storage_months",
                   "pest_count", "spider_count_per_hill"}   # the "Missing data" table
    assert table_names <= set(CONDITION_VARIABLES)


def test_on_unknown_policies():
    policy = {name: v.on_unknown for name, v in CONDITION_VARIABLES.items()}
    assert policy["forecast_rain_mm_24h"] is OnUnknown.CONSERVATIVE
    assert policy["tmax_c"] is OnUnknown.CONSERVATIVE
    assert policy["pest_count"] is OnUnknown.ASK
    assert policy["spider_count_per_hill"] is OnUnknown.ASK
    assert policy["soil_N_rating"] is OnUnknown.ASK_THEN_BRANCH
    assert policy["grain_moisture_pct"] is OnUnknown.ASK_THEN_BRANCH
