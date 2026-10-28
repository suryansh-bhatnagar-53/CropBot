import json
from pathlib import Path

import pytest

from kg.schema import FACT, DryingSpec, PestThreshold, Source, StorageRule

from .examples import (BPH_THRESHOLD, DRYING_GRAIN, DRYING_LONG, DRYING_SEED_SHORT,
                       STORAGE_LONG, TNAU_SOURCE, WORKED_EXAMPLES)

INDEX = Path(__file__).resolve().parents[2] / "converted" / "tnau_agriculture.index.json"


@pytest.mark.parametrize("name", WORKED_EXAMPLES)
def test_worked_example_validates(name):
    FACT.validate_python(WORKED_EXAMPLES[name])


def test_source_validates():
    Source.model_validate(TNAU_SOURCE)


def test_bph_clauses_are_gated_by_spider_count():
    bph = FACT.validate_python(BPH_THRESHOLD)
    assert isinstance(bph, PestThreshold)
    gates = [(c.value, c.conditions[0].op.value) for c in bph.clauses]
    assert gates == [(1, "<"), (2, ">=")]


def test_seed_storage_conflict_is_kept_and_flagged():
    drying, storage = FACT.validate_python(DRYING_LONG), FACT.validate_python(STORAGE_LONG)
    assert isinstance(drying, DryingSpec) and isinstance(storage, StorageRule)
    assert drying.conflicts_with == [storage.id] and storage.conflicts_with == [drying.id]
    assert drying.status == storage.status == "needs_review"
    # "long term" with no months: the bot asks instead of guessing a mapping
    assert drying.storage_months_min is None and drying.storage_months_max is None


def test_grain_and_seed_drying_are_separate_facts():
    grain, seed = FACT.validate_python(DRYING_GRAIN), FACT.validate_python(DRYING_SEED_SHORT)
    assert grain.purpose_ids == ["purpose:grain"] and seed.purpose_ids == ["purpose:seed"]
    assert (grain.target_moisture_pct_min, grain.target_moisture_pct_max) == (12, 12)
    assert (seed.target_moisture_pct_min, seed.target_moisture_pct_max) == (12, 13)


@pytest.mark.skipif(not INDEX.exists(), reason="committed TNAU conversion not present")
@pytest.mark.parametrize("name", WORKED_EXAMPLES)
def test_quote_is_on_its_pdf_page(name):
    """Each example quote is real text from its stated page of the committed conversion."""
    items = json.loads(INDEX.read_text(encoding="utf-8"))["items"]
    for span in WORKED_EXAMPLES[name]["evidence"]:
        page_text = [it.get("t") or it.get("md") or "" for it in items
                     if it.get("pg") == span["pdf_page"]]
        assert any(span["quote"] in text for text in page_text), span["id"]
