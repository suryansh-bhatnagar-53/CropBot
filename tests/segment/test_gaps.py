"""Offline tests for acknowledged numbering gaps (kg.segment.split_gaps)."""

from types import SimpleNamespace

from kg.registry.model import AcknowledgedGap
from kg.segment import split_gaps

ACK = AcknowledgedGap(chapter="WHEAT", under="I. SEASON AND VARIETY", missing=["1"], pdf_page=134,
                      note="printed without 1.")
GAP = {"chapter": "WHEAT", "under": "I. SEASON AND VARIETY", "missing": ["1"]}
OTHER = {"chapter": "RICE", "under": "3. WET SEEDED", "missing": ["3.9"]}


def test_matching_gap_is_acknowledged_not_open():
    open_, acked, stale = split_gaps(SimpleNamespace(acknowledged_gap=[ACK]), [GAP, OTHER])
    assert open_ == [OTHER] and stale == []
    assert acked == [{**GAP, "pdf_page": 134, "note": "printed without 1."}]


def test_different_missing_numbers_stay_open_and_the_entry_is_stale():
    more = {**GAP, "missing": ["1", "3"]}                      # the page changed: never half-match
    open_, acked, stale = split_gaps(SimpleNamespace(acknowledged_gap=[ACK]), [more])
    assert open_ == [more] and acked == [] and [s["under"] for s in stale] == ["I. SEASON AND VARIETY"]


def test_entry_with_no_gap_is_stale():
    open_, acked, stale = split_gaps(SimpleNamespace(acknowledged_gap=[ACK]), [])
    assert (open_, acked, len(stale)) == ([], [], 1)
